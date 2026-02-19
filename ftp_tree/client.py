"""FTP client wrapper that handles connection, listing, and OS detection."""

import ftplib
from typing import List, Optional

from .permissions import FileEntry, ServerOS, detect_server_os, parse_line


class FTPClientError(Exception):
    pass


class FTPClient:
    def __init__(
        self,
        host: str,
        port: int = 21,
        timeout: int = 30,
        use_tls: bool = False,
        passive: bool = True,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.use_tls = use_tls
        self.passive = passive
        self._ftp: Optional[ftplib.FTP] = None
        self.server_os: ServerOS = ServerOS.UNKNOWN
        self.is_anonymous: bool = False

    def connect(self, username: str = "anonymous", password: str = "anonymous@") -> None:
        try:
            if self.use_tls:
                self._ftp = ftplib.FTP_TLS()
            else:
                self._ftp = ftplib.FTP()

            self._ftp.connect(self.host, self.port, timeout=self.timeout)
            self._ftp.login(username, password)

            if self.use_tls:
                self._ftp.prot_p()  # Upgrade data connection to TLS

            self._ftp.set_pasv(self.passive)
            self.is_anonymous = username.lower() in ("anonymous", "anon", "ftp", "")
            self._detect_os()

        except ftplib.error_perm as e:
            raise FTPClientError(f"Authentication failed: {e}") from e
        except OSError as e:
            raise FTPClientError(f"Could not connect to {self.host}:{self.port}: {e}") from e

    def _detect_os(self) -> None:
        """Detect server OS from the root directory listing."""
        try:
            lines: List[str] = []
            self._ftp.retrlines("LIST", lines.append)
            self.server_os = detect_server_os(lines)
        except Exception:
            self.server_os = ServerOS.UNKNOWN

    def list_dir(self, path: str) -> List[FileEntry]:
        """Return parsed directory entries for *path*. Returns [] on permission errors."""
        lines: List[str] = []
        try:
            self._ftp.retrlines(f"LIST {path}", lines.append)
        except ftplib.error_perm as e:
            code = str(e)[:3]
            if code in ("550", "553", "530"):
                return []   # permission denied / not found — skip silently
            raise FTPClientError(str(e)) from e

        entries = []
        for line in lines:
            entry = parse_line(line, self.server_os)
            if entry is not None:
                entries.append(entry)
        return entries

    def get_banner(self) -> str:
        return self._ftp.getwelcome() if self._ftp else ""

    def disconnect(self) -> None:
        if self._ftp:
            try:
                self._ftp.quit()
            except Exception:
                self._ftp.close()
            self._ftp = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.disconnect()
