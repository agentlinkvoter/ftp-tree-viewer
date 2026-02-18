"""Tests for ftp_tree.permissions — line parsing and OS detection."""

import unittest
from ftp_tree.permissions import (
    FileEntry,
    ServerOS,
    detect_server_os,
    parse_line,
    parse_unix_line,
    parse_windows_line,
)


class TestDetectServerOS(unittest.TestCase):
    def test_detects_unix(self):
        lines = [
            "drwxr-xr-x 2 ftpuser ftpgroup 4096 Jan  1 00:00 pub",
            "-rw-r--r-- 1 ftpuser ftpgroup  512 Jan  1 00:00 readme.txt",
        ]
        self.assertEqual(detect_server_os(lines), ServerOS.UNIX)

    def test_detects_windows(self):
        lines = [
            "11-01-21  01:00PM <DIR>          pub",
            "11-01-21  01:30PM             1234 readme.txt",
        ]
        self.assertEqual(detect_server_os(lines), ServerOS.WINDOWS)

    def test_unknown_on_empty(self):
        self.assertEqual(detect_server_os([]), ServerOS.UNKNOWN)

    def test_ignores_blank_lines(self):
        lines = ["", "  ", "drwxr-xr-x 2 u g 4096 Jan  1 00:00 pub"]
        self.assertEqual(detect_server_os(lines), ServerOS.UNIX)


class TestParseUnixLine(unittest.TestCase):
    def _parse(self, line):
        entry = parse_unix_line(line)
        self.assertIsNotNone(entry, f"Failed to parse: {line!r}")
        return entry

    def test_regular_file(self):
        line = "-rw-r--r-- 1 ftpuser ftpgroup  1024 Jan  1 12:00 file.txt"
        e = self._parse(line)
        self.assertEqual(e.name, "file.txt")
        self.assertFalse(e.is_dir)
        self.assertFalse(e.is_symlink)
        self.assertEqual(e.size, 1024)
        self.assertEqual(e.permissions, "rw-r--r--")
        self.assertEqual(e.owner, "ftpuser")
        self.assertEqual(e.group, "ftpgroup")
        self.assertFalse(e.writable)

    def test_directory(self):
        line = "drwxr-xr-x 2 ftpuser ftpgroup 4096 Jan  1 00:00 pub"
        e = self._parse(line)
        self.assertTrue(e.is_dir)
        self.assertFalse(e.is_symlink)
        self.assertEqual(e.name, "pub")
        self.assertFalse(e.writable)  # no group/world write bit

    def test_world_writable_directory(self):
        line = "drwxrwxrwx 2 ftpuser ftpgroup 4096 Jan  1 00:00 uploads"
        e = self._parse(line)
        self.assertTrue(e.is_dir)
        self.assertTrue(e.writable)

    def test_group_writable_directory(self):
        line = "drwxrwxr-x 2 ftpuser ftpgroup 4096 Jan  1 00:00 shared"
        e = self._parse(line)
        self.assertTrue(e.writable)

    def test_symlink(self):
        line = "lrwxrwxrwx 1 ftpuser ftpgroup   12 Jan  1 00:00 link -> /etc/passwd"
        e = self._parse(line)
        self.assertTrue(e.is_symlink)
        self.assertFalse(e.is_dir)
        self.assertEqual(e.name, "link")
        self.assertEqual(e.link_target, "/etc/passwd")

    def test_symlink_without_target(self):
        line = "lrwxrwxrwx 1 ftpuser ftpgroup   12 Jan  1 00:00 brokenlink"
        e = self._parse(line)
        self.assertTrue(e.is_symlink)
        self.assertIsNone(e.link_target)

    def test_hidden_file(self):
        line = "-rw-r--r-- 1 ftpuser ftpgroup 100 Jan  1 00:00 .hidden"
        e = self._parse(line)
        self.assertEqual(e.name, ".hidden")

    def test_returns_none_for_garbage(self):
        self.assertIsNone(parse_unix_line("total 8"))
        self.assertIsNone(parse_unix_line(""))
        self.assertIsNone(parse_unix_line("11-01-21  01:00PM <DIR> pub"))

    def test_large_file(self):
        line = "-rw-r--r-- 1 u g 1073741824 Dec 31 23:59 bigfile.iso"
        e = self._parse(line)
        self.assertEqual(e.size, 1073741824)

    def test_year_in_modified(self):
        line = "-rw-r--r-- 1 u g 100 Jan  1 2023 archive.tar.gz"
        e = self._parse(line)
        self.assertIn("2023", e.modified)


class TestParseWindowsLine(unittest.TestCase):
    def _parse(self, line):
        entry = parse_windows_line(line)
        self.assertIsNotNone(entry, f"Failed to parse: {line!r}")
        return entry

    def test_file(self):
        line = "11-01-21  01:30PM             1234 readme.txt"
        e = self._parse(line)
        self.assertEqual(e.name, "readme.txt")
        self.assertFalse(e.is_dir)
        self.assertFalse(e.is_symlink)
        self.assertEqual(e.size, 1234)
        self.assertIsNone(e.permissions)
        self.assertFalse(e.writable)

    def test_directory(self):
        line = "11-01-21  01:00PM <DIR>          pub"
        e = self._parse(line)
        self.assertEqual(e.name, "pub")
        self.assertTrue(e.is_dir)
        self.assertEqual(e.size, 0)

    def test_am_time(self):
        line = "01-15-22  09:00AM             5678 data.csv"
        e = self._parse(line)
        self.assertIn("09:00AM", e.modified)

    def test_returns_none_for_garbage(self):
        self.assertIsNone(parse_windows_line(""))
        self.assertIsNone(parse_windows_line("total 8"))
        self.assertIsNone(parse_windows_line("drwxr-xr-x 2 u g 4096 Jan  1 00:00 pub"))


class TestParseLineDispatch(unittest.TestCase):
    def test_dispatches_to_unix(self):
        line = "-rw-r--r-- 1 u g 100 Jan  1 00:00 file.txt"
        e = parse_line(line, ServerOS.UNIX)
        self.assertIsNotNone(e)
        self.assertEqual(e.name, "file.txt")

    def test_dispatches_to_windows(self):
        line = "11-01-21  01:00PM             100 file.txt"
        e = parse_line(line, ServerOS.WINDOWS)
        self.assertIsNotNone(e)
        self.assertEqual(e.name, "file.txt")

    def test_unknown_tries_both(self):
        unix_line = "-rw-r--r-- 1 u g 100 Jan  1 00:00 file.txt"
        e = parse_line(unix_line, ServerOS.UNKNOWN)
        self.assertIsNotNone(e)

        win_line = "11-01-21  01:00PM             100 file.txt"
        e = parse_line(win_line, ServerOS.UNKNOWN)
        self.assertIsNotNone(e)


if __name__ == "__main__":
    unittest.main()
