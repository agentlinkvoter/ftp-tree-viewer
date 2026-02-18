"""Tree renderer: walks the FTP directory tree and prints it like the `tree` command."""

import re
import sys
from typing import Optional, TextIO

from .client import FTPClient
from .permissions import FileEntry

# Tree drawing characters (Unicode box-drawing)
_TEE  = "├── "
_LAST = "└── "
_PIPE = "│   "
_SPAC = "    "

# ANSI escape sequence pattern for stripping when writing to file
_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init()
    _HAS_COLOR = True
except ImportError:
    _HAS_COLOR = False


def _c(text: str, code: str, no_color: bool) -> str:
    """Wrap *text* in an ANSI color code, respecting the no_color flag."""
    if no_color or not _HAS_COLOR:
        return text
    return f"{code}{text}{Style.RESET_ALL}"


def _fmt_size(size: int) -> str:
    """Human-readable file size."""
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
    highlight_writable: bool,
    no_color: bool,
) -> str:
    parts = []

    if show_perms:
        if entry.permissions:
            perm_str = _c(f"[{entry.permissions}]", Fore.YELLOW if _HAS_COLOR else "", no_color)
        else:
            # Windows server — permissions unavailable
            perm_str = _c("[unavailable]", Fore.WHITE if _HAS_COLOR else "", no_color)
        parts.append(perm_str)

    if show_size:
        parts.append(_c(f"[{_fmt_size(entry.size):>6}]", Fore.CYAN if _HAS_COLOR else "", no_color))

    if show_modified and entry.modified:
        parts.append(_c(f"[{entry.modified}]", Fore.WHITE if _HAS_COLOR else "", no_color))

    # Colorize the filename by type
    name = entry.name
    if entry.is_symlink:
        name = _c(name, Fore.CYAN if _HAS_COLOR else "", no_color)
        if entry.link_target:
            name += _c(f" -> {entry.link_target}", Fore.CYAN if _HAS_COLOR else "", no_color)
    elif entry.is_dir:
        color = (Fore.RED if _HAS_COLOR else "") if (entry.writable and highlight_writable) else (Fore.BLUE if _HAS_COLOR else "")
        name = _c(name + "/", color, no_color)
    elif entry.name.startswith("."):
        name = _c(name, Fore.WHITE if _HAS_COLOR else "", no_color)

    parts.append(name)

    # Writable badge (only shown when --writable flag is active)
    if highlight_writable and entry.writable and entry.is_dir:
        badge = _c(" [WRITABLE]", Fore.RED if _HAS_COLOR else "", no_color)
        parts.append(badge)

    return " ".join(parts)


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
        highlight_writable: bool = False,
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
        self.highlight_writable = highlight_writable
        self.out = out
        self.file_out = file_out  # plain-text copy (ANSI stripped)

        self._dir_count = 0
        self._file_count = 0

    def _emit(self, line: str) -> None:
        print(line, file=self.out)
        if self.file_out:
            print(_ANSI_RE.sub("", line), file=self.file_out)

    def _walk(self, path: str, prefix: str, depth: int) -> None:
        if self.max_depth is not None and depth > self.max_depth:
            return

        try:
            entries = self.client.list_dir(path)
        except Exception as e:
            self._emit(f"{prefix}{_TEE}[error: {e}]")
            return

        if not self.show_hidden:
            entries = [e for e in entries if not e.name.startswith(".")]

        # Dirs first, then files — each group sorted alphabetically
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
                self.highlight_writable,
                self.no_color,
            )
            self._emit(f"{prefix}{connector}{label}")

            if entry.is_dir and not entry.is_symlink:
                self._dir_count += 1
                child_path = path.rstrip("/") + "/" + entry.name
                self._walk(child_path, child_prefix, depth + 1)
            else:
                self._file_count += 1

    def render(self, start_path: str = "/") -> None:
        root_label = _c(start_path, Fore.BLUE if _HAS_COLOR else "", self.no_color)
        self._emit(root_label)
        self._walk(start_path, "", 0)
        self._emit(f"\n{self._dir_count} director{'ies' if self._dir_count != 1 else 'y'}, "
                   f"{self._file_count} file{'s' if self._file_count != 1 else ''}")
