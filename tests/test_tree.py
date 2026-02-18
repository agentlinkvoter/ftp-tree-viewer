"""Tests for ftp_tree.tree — rendering logic using a mock FTP client."""

import io
import unittest
from unittest.mock import MagicMock, patch

from ftp_tree.permissions import FileEntry, ServerOS
from ftp_tree.tree import FTPTreeViewer, _fmt_size, _build_label


def _entry(
    name,
    is_dir=False,
    is_symlink=False,
    size=0,
    permissions="rw-r--r--",
    writable=False,
    link_target=None,
    modified="Jan  1 00:00",
):
    return FileEntry(
        name=name,
        is_dir=is_dir,
        is_symlink=is_symlink,
        size=size,
        permissions=permissions,
        owner="ftpuser",
        group="ftpgroup",
        modified=modified,
        raw_line="",
        writable=writable,
        link_target=link_target,
    )


def _make_viewer(entries_by_path, **kwargs):
    """Create an FTPTreeViewer backed by a mock client."""
    client = MagicMock()
    client.server_os = ServerOS.UNIX
    client.list_dir.side_effect = lambda path: entries_by_path.get(path, [])

    out = io.StringIO()
    viewer = FTPTreeViewer(client=client, no_color=True, out=out, **kwargs)
    return viewer, out


class TestFmtSize(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(_fmt_size(512), "512B")

    def test_kilobytes(self):
        self.assertEqual(_fmt_size(2048), "2K")

    def test_megabytes(self):
        self.assertEqual(_fmt_size(3 * 1024 * 1024), "3M")

    def test_gigabytes(self):
        self.assertEqual(_fmt_size(2 * 1024 ** 3), "2G")

    def test_zero(self):
        self.assertEqual(_fmt_size(0), "0B")


class TestBuildLabel(unittest.TestCase):
    def _label(self, entry, **kwargs):
        defaults = dict(
            show_perms=False, show_size=False, show_modified=False,
            highlight_writable=False, no_color=True
        )
        defaults.update(kwargs)
        return _build_label(entry, **defaults)

    def test_plain_file(self):
        label = self._label(_entry("file.txt", size=100))
        self.assertIn("file.txt", label)

    def test_dir_has_trailing_slash(self):
        label = self._label(_entry("mydir", is_dir=True))
        self.assertIn("mydir/", label)

    def test_symlink_shows_target(self):
        label = self._label(_entry("link", is_symlink=True, link_target="/etc/passwd"))
        self.assertIn("link", label)
        self.assertIn("->", label)
        self.assertIn("/etc/passwd", label)

    def test_permissions_shown(self):
        label = self._label(_entry("file.txt", permissions="rw-r--r--"), show_perms=True)
        self.assertIn("rw-r--r--", label)

    def test_permissions_unavailable_on_windows(self):
        e = _entry("file.txt")
        e.permissions = None
        label = self._label(e, show_perms=True)
        self.assertIn("unavailable", label)

    def test_size_shown(self):
        label = self._label(_entry("file.txt", size=2048), show_size=True)
        self.assertIn("2K", label)

    def test_modified_shown(self):
        label = self._label(_entry("file.txt", modified="Jan  1 12:00"), show_modified=True)
        self.assertIn("Jan  1 12:00", label)

    def test_writable_badge_shown_when_flag_on(self):
        label = self._label(
            _entry("uploads", is_dir=True, writable=True),
            highlight_writable=True,
        )
        self.assertIn("[WRITABLE]", label)

    def test_writable_badge_hidden_when_flag_off(self):
        label = self._label(
            _entry("uploads", is_dir=True, writable=True),
            highlight_writable=False,
        )
        self.assertNotIn("[WRITABLE]", label)


class TestFTPTreeViewer(unittest.TestCase):
    def test_renders_root_path(self):
        viewer, out = _make_viewer({"/": []})
        viewer.render("/")
        self.assertIn("/", out.getvalue())

    def test_renders_files(self):
        entries = {
            "/": [
                _entry("readme.txt", size=100),
                _entry("pub", is_dir=True),
            ],
            "/pub": [],
        }
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("readme.txt", output)
        self.assertIn("pub/", output)

    def test_summary_line(self):
        entries = {
            "/": [
                _entry("file.txt"),
                _entry("subdir", is_dir=True),
            ],
            "/subdir": [],
        }
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("director", output)
        self.assertIn("file", output)

    def test_hidden_files_excluded_by_default(self):
        entries = {"/": [_entry(".hidden"), _entry("visible.txt")]}
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        self.assertNotIn(".hidden", output)
        self.assertIn("visible.txt", output)

    def test_hidden_files_shown_with_flag(self):
        entries = {"/": [_entry(".hidden"), _entry("visible.txt")]}
        viewer, out = _make_viewer(entries, show_hidden=True)
        viewer.render("/")
        self.assertIn(".hidden", out.getvalue())

    def test_max_depth_respected(self):
        entries = {
            "/": [_entry("a", is_dir=True)],
            "/a": [_entry("b", is_dir=True)],
            "/a/b": [_entry("deep.txt")],
        }
        viewer, out = _make_viewer(entries, max_depth=1)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("a/", output)
        # depth 0 = root children, depth 1 = /a children, depth 2 = /a/b children
        # With max_depth=1 we should NOT descend into /a/b
        self.assertNotIn("deep.txt", output)

    def test_symlinks_not_recursed(self):
        entries = {
            "/": [_entry("link", is_symlink=True, link_target="/other")],
        }
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        # Should not try to list /link
        viewer.client.list_dir.assert_called_once_with("/")

    def test_output_written_to_file_out(self):
        entries = {"/": [_entry("file.txt")]}
        client = MagicMock()
        client.server_os = ServerOS.UNIX
        client.list_dir.side_effect = lambda path: entries.get(path, [])
        out = io.StringIO()
        file_out = io.StringIO()
        viewer = FTPTreeViewer(client=client, no_color=True, out=out, file_out=file_out)
        viewer.render("/")
        self.assertIn("file.txt", file_out.getvalue())

    def test_dirs_sorted_before_files(self):
        entries = {
            "/": [
                _entry("zebra.txt"),
                _entry("alpha", is_dir=True),
            ],
            "/alpha": [],
        }
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        alpha_pos = output.index("alpha")
        zebra_pos = output.index("zebra.txt")
        self.assertLess(alpha_pos, zebra_pos)

    def test_tree_connectors_present(self):
        entries = {
            "/": [_entry("a.txt"), _entry("b.txt")],
        }
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("├──", output)
        self.assertIn("└──", output)

    def test_permission_denied_dir_shows_error(self):
        from ftp_tree.client import FTPClientError
        client = MagicMock()
        client.server_os = ServerOS.UNIX
        client.list_dir.side_effect = FTPClientError("Permission denied")
        out = io.StringIO()
        viewer = FTPTreeViewer(client=client, no_color=True, out=out)
        # Should not raise; should print an error line
        viewer.render("/")
        self.assertIn("error", out.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
