"""
Parse FTP LIST output lines for both Unix and Windows FTP servers.

Unix LIST line format:
  -rwxr-xr-x 1 owner group 1234 Jan  1 00:00 filename
  drwxr-x--- 2 owner group 4096 Dec 31 23:59 dirname
  lrwxrwxrwx 1 owner group   12 Jan  1 00:00 link -> target

Windows LIST line format:
  11-01-21  01:00PM       1234 filename.txt
  11-01-21  01:00PM <DIR>      dirname
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ServerOS(Enum):
    UNIX = "unix"
    WINDOWS = "windows"
    UNKNOWN = "unknown"


@dataclass
class FileEntry:
    name: str
    is_dir: bool
    is_symlink: bool
    size: int
    # Unix: "rwxr-xr-x" (9 chars, no leading type char). None on Windows.
    permissions: Optional[str]
    owner: Optional[str]
    group: Optional[str]
    modified: Optional[str]
    raw_line: str
    # True if world-writable or group-writable (Unix only)
    writable: bool = False
    link_target: Optional[str] = None


# Matches Unix-style LIST lines
_UNIX_RE = re.compile(
    r'^([dlrwxsStT\-]{10})\s+'   # permissions (10 chars)
    r'(\d+)\s+'                    # link count
    r'(\S+)\s+'                    # owner
    r'(\S+)\s+'                    # group
    r'(\d+)\s+'                    # size
    r'(\w{3}\s+\d{1,2}\s+[\d:]+)' # modified date/time
    r'\s+(.+)$'                    # filename (possibly "name -> target")
)

# Matches Windows-style LIST lines
_WIN_RE = re.compile(
    r'^(\d{2}-\d{2}-\d{2}\s+\d{2}:\d{2}[AP]M)'  # date/time
    r'\s+(<DIR>|\d+)'                               # <DIR> or size
    r'\s+(.+)$'                                     # filename
)


def detect_server_os(lines: list) -> ServerOS:
    """Infer the server OS type from a sample of LIST output lines."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if _UNIX_RE.match(line):
            return ServerOS.UNIX
        if _WIN_RE.match(line):
            return ServerOS.WINDOWS
    return ServerOS.UNKNOWN


def _is_writable(perm_str: str) -> bool:
    """Return True if the entry is group- or world-writable.

    perm_str is the full 10-char permission string, e.g. "drwxrwxr-x".
    Index 5 = group write, index 8 = other write.
    """
    return len(perm_str) >= 10 and (perm_str[5] == 'w' or perm_str[8] == 'w')


def parse_unix_line(line: str) -> Optional[FileEntry]:
    match = _UNIX_RE.match(line.strip())
    if not match:
        return None

    perm_str, _links, owner, group, size, modified, name_part = match.groups()

    type_char = perm_str[0]
    is_symlink = type_char == 'l'
    is_dir = type_char == 'd'

    link_target = None
    name = name_part.strip()
    if is_symlink and ' -> ' in name:
        name, link_target = name.split(' -> ', 1)

    return FileEntry(
        name=name,
        is_dir=is_dir,
        is_symlink=is_symlink,
        size=int(size),
        permissions=perm_str[1:],  # strip leading type char, keep 9 perm chars
        owner=owner,
        group=group,
        modified=modified.strip(),
        raw_line=line,
        writable=_is_writable(perm_str),
        link_target=link_target,
    )


def parse_windows_line(line: str) -> Optional[FileEntry]:
    match = _WIN_RE.match(line.strip())
    if not match:
        return None

    modified, size_or_dir, name = match.groups()
    is_dir = size_or_dir == '<DIR>'

    return FileEntry(
        name=name.strip(),
        is_dir=is_dir,
        is_symlink=False,
        size=0 if is_dir else int(size_or_dir),
        permissions=None,   # Windows FTP servers don't expose Unix permissions
        owner=None,
        group=None,
        modified=modified.strip(),
        raw_line=line,
        writable=False,     # Cannot determine from Windows listing
    )


def parse_line(line: str, server_os: ServerOS) -> Optional[FileEntry]:
    """Parse a single LIST output line according to the detected server OS."""
    if server_os == ServerOS.UNIX:
        return parse_unix_line(line)
    if server_os == ServerOS.WINDOWS:
        return parse_windows_line(line)
    # Unknown: try both
    return parse_unix_line(line) or parse_windows_line(line)
