"""Tree renderer: walks the FTP directory tree and prints it like the `tree` command.

In normal mode: streams and prints entries as they are discovered.
In writable mode (--writable-dirs / --writable-files / --writable-all):
  builds the full tree in memory, prunes it to only paths leading to writable
  targets, then renders the pruned tree with targets highlighted in red.
"""

import re
import sys
from dataclasses import dataclass, field as dc_field
from typing import List, Optional, TextIO

from .client import FTPClient
from .permissions import FileEntry

# Tree drawing characters (Unicode box-drawing)
_TEE  = "├── "
_LAST = "└── "
_PIPE = "│   "
_SPAC = "    "

# Strip ANSI escape sequences when writing to plain-text file
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

try:
    from colorama import Fore, Style
    try:
        # colorama 0.4.6+: enables native ANSI in the Windows console without
        # wrapping stdout — more reliable than init() on modern Windows.
        from colorama import just_fix_windows_console
        just_fix_windows_console()
    except ImportError:
        from colorama import init as _colorama_init
        _colorama_init()
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


def _c(text: str, code: str, no_color: bool) -> str:
    if no_color or not _HAS_COLOR:
        return text
    return f"{code}{text}{Style.RESET_ALL}"


def _fmt_size(size: int) -> str:
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size}{unit}"
        size //= 1024
    return f"{size}P"


def _build_label(
    entry: FileEntry,
    show_perms: bool,
    show_size: bool,
    show_modified: bool,
    is_target: bool,
    no_color: bool,
) -> str:
    """Build the display label for a single entry.

    is_target=True means this entry is a writable finding — rendered in red
    with a [WRITABLE DIR] or [WRITABLE FILE] badge.
    """
    parts = []

    if show_perms:
        if entry.permissions:
            parts.append(_c(f"[{entry.permissions}]", Fore.YELLOW if _HAS_COLOR else "", no_color))
        else:
            parts.append(_c("[unavailable]", Fore.WHITE if _HAS_COLOR else "", no_color))

    if show_size:
        parts.append(_c(f"[{_fmt_size(entry.size):>6}]", Fore.CYAN if _HAS_COLOR else "", no_color))

    if show_modified and entry.modified:
        parts.append(_c(f"[{entry.modified}]", Fore.WHITE if _HAS_COLOR else "", no_color))

    # Name — color depends on whether this is a target, a symlink, a dir, etc.
    name = entry.name
    if is_target:
        display = name + ("/" if entry.is_dir and not entry.is_symlink else "")
        name_str = _c(display, Fore.RED if _HAS_COLOR else "", no_color)
        if entry.is_symlink and entry.link_target:
            name_str += _c(f" -> {entry.link_target}", Fore.RED if _HAS_COLOR else "", no_color)
    elif entry.is_symlink:
        name_str = _c(name, Fore.CYAN if _HAS_COLOR else "", no_color)
        if entry.link_target:
            name_str += _c(f" -> {entry.link_target}", Fore.CYAN if _HAS_COLOR else "", no_color)
    elif entry.is_dir:
        name_str = _c(name + "/", Fore.BLUE if _HAS_COLOR else "", no_color)
    elif name.startswith("."):
        name_str = _c(name, Fore.WHITE if _HAS_COLOR else "", no_color)
    else:
        name_str = name

    parts.append(name_str)

    if is_target:
        kind = "DIR" if entry.is_dir else "FILE"
        parts.append(_c(f"[WRITABLE {kind}]", Fore.RED if _HAS_COLOR else "", no_color))

    return " ".join(parts)


# ---------------------------------------------------------------------------
# In-memory tree node — used only during writable-mode two-pass rendering
# ---------------------------------------------------------------------------

@dataclass
class _Node:
    path: str
    entry: FileEntry
    children: List["_Node"] = dc_field(default_factory=list)
    is_target: bool = False  # True = this node is a writable finding


# ---------------------------------------------------------------------------
# Main viewer class
# ---------------------------------------------------------------------------

class FTPTreeViewer:
    def __init__(
        self,
        client: FTPClient,
        show_hidden: bool = False,
        show_perms: bool = False,
        show_size: bool = False,
        show_modified: bool = False,
        max_depth: Optional[int] = None,
        no_color: bool = False,
        writable_dirs: bool = False,
        writable_files: bool = False,
        out: TextIO = sys.stdout,
        file_out: Optional[TextIO] = None,
    ):
        self.client = client
        self.show_hidden = show_hidden
        self.show_perms = show_perms
        self.show_size = show_size
        self.show_modified = show_modified
        self.max_depth = max_depth
        self.no_color = no_color
        self.writable_dirs = writable_dirs
        self.writable_files = writable_files
        self.out = out
        self.file_out = file_out

        self._dir_count = 0
        self._file_count = 0

    @property
    def _writable_mode(self) -> bool:
        return self.writable_dirs or self.writable_files

    def _emit(self, line: str) -> None:
        print(line, file=self.out)
        if self.file_out:
            print(_ANSI_RE.sub("", line), file=self.file_out)

    # ------------------------------------------------------------------
    # Normal (streaming) walk — used when no writable flags are active
    # ------------------------------------------------------------------

    def _stream_walk(self, path: str, prefix: str, depth: int) -> None:
        if self.max_depth is not None and depth > self.max_depth:
            return

        try:
            entries = self.client.list_dir(path)
        except Exception as e:
            self._emit(f"{prefix}{_TEE}[error: {e}]")
            return

        if not self.show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = _LAST if is_last else _TEE
            child_prefix = prefix + (_SPAC if is_last else _PIPE)

            label = _build_label(
                entry,
                self.show_perms,
                self.show_size,
                self.show_modified,
                is_target=False,
                no_color=self.no_color,
            )
            self._emit(f"{prefix}{connector}{label}")

            if entry.is_dir and not entry.is_symlink:
                self._dir_count += 1
                self._stream_walk(path.rstrip("/") + "/" + entry.name, child_prefix, depth + 1)
            else:
                self._file_count += 1

    # ------------------------------------------------------------------
    # Writable mode: build full tree → mark targets → prune → render
    # ------------------------------------------------------------------

    def _build_tree(self, path: str, depth: int) -> List[_Node]:
        """Recursively collect all entries under *path* into _Node objects."""
        if self.max_depth is not None and depth > self.max_depth:
            return []

        try:
            entries = self.client.list_dir(path)
        except Exception:
            return []

        if not self.show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))

        nodes = []
        for entry in entries:
            child_path = path.rstrip("/") + "/" + entry.name
            node = _Node(path=child_path, entry=entry)
            if entry.is_dir and not entry.is_symlink:
                node.children = self._build_tree(child_path, depth + 1)
            nodes.append(node)
        return nodes

    def _mark_targets(self, nodes: List[_Node]) -> None:
        """Mark nodes that are writable findings based on active flags."""
        for node in nodes:
            e = node.entry
            if self.writable_dirs and e.is_dir and not e.is_symlink and e.writable:
                node.is_target = True
                self._dir_count += 1
            elif self.writable_files and not e.is_dir and not e.is_symlink and e.writable:
                node.is_target = True
                self._file_count += 1
            self._mark_targets(node.children)

    def _prune(self, nodes: List[_Node]) -> List[_Node]:
        """Keep only nodes that are targets or ancestors of targets."""
        result = []
        for node in nodes:
            node.children = self._prune(node.children)
            if node.is_target or node.children:
                result.append(node)
        return result

    def _render_nodes(self, nodes: List[_Node], prefix: str) -> None:
        for i, node in enumerate(nodes):
            is_last = i == len(nodes) - 1
            connector = _LAST if is_last else _TEE
            child_prefix = prefix + (_SPAC if is_last else _PIPE)

            label = _build_label(
                node.entry,
                self.show_perms,
                self.show_size,
                self.show_modified,
                is_target=node.is_target,
                no_color=self.no_color,
            )
            self._emit(f"{prefix}{connector}{label}")

            if node.children:
                self._render_nodes(node.children, child_prefix)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def render(self, start_path: str = "/") -> None:
        root_label = _c(start_path, Fore.BLUE if _HAS_COLOR else "", self.no_color)
        self._emit(root_label)

        if self._writable_mode:
            nodes = self._build_tree(start_path, 0)
            self._mark_targets(nodes)
            nodes = self._prune(nodes)
            self._render_nodes(nodes, "")

            if self._dir_count == 0 and self._file_count == 0:
                self._emit("  (no writable targets found)")
            else:
                parts = []
                if self.writable_dirs:
                    parts.append(
                        f"{self._dir_count} writable "
                        f"director{'ies' if self._dir_count != 1 else 'y'}"
                    )
                if self.writable_files:
                    parts.append(
                        f"{self._file_count} writable "
                        f"file{'s' if self._file_count != 1 else ''}"
                    )
                self._emit("\n" + ", ".join(parts) + " found")
        else:
            self._stream_walk(start_path, "", 0)
            self._emit(
                f"\n{self._dir_count} "
                f"director{'ies' if self._dir_count != 1 else 'y'}, "
                f"{self._file_count} file{'s' if self._file_count != 1 else ''}"
            )
