"""Tests for ftp_tree.tree — rendering logic using a mock FTP client."""

import io
import unittest
from unittest.mock import MagicMock

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
            is_target=False, no_color=True,
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

    def test_writable_dir_target_shows_badge(self):
        label = self._label(_entry("uploads", is_dir=True, writable=True), is_target=True)
        self.assertIn("[WRITABLE DIR]", label)

    def test_writable_file_target_shows_badge(self):
        label = self._label(_entry("config.php", writable=True), is_target=True)
        self.assertIn("[WRITABLE FILE]", label)

    def test_non_target_writable_dir_no_badge(self):
        # Without is_target, no badge even if entry.writable is True
        label = self._label(_entry("uploads", is_dir=True, writable=True), is_target=False)
        self.assertNotIn("[WRITABLE", label)


class TestFTPTreeViewerNormalMode(unittest.TestCase):
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
        # depth 1 = /a children, depth 2 = /a/b children — should be cut
        self.assertNotIn("deep.txt", out.getvalue())

    def test_symlinks_not_recursed(self):
        entries = {"/": [_entry("link", is_symlink=True, link_target="/other")]}
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        viewer.client.list_dir.assert_called_once_with("/")

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
        self.assertLess(output.index("alpha"), output.index("zebra.txt"))

    def test_tree_connectors_present(self):
        entries = {"/": [_entry("a.txt"), _entry("b.txt")]}
        viewer, out = _make_viewer(entries)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("├──", output)
        self.assertIn("└──", output)

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

    def test_permission_denied_dir_shows_error(self):
        from ftp_tree.client import FTPClientError
        client = MagicMock()
        client.server_os = ServerOS.UNIX
        client.list_dir.side_effect = FTPClientError("Permission denied")
        out = io.StringIO()
        viewer = FTPTreeViewer(client=client, no_color=True, out=out)
        viewer.render("/")
        self.assertIn("error", out.getvalue().lower())


class TestWritableDirsMode(unittest.TestCase):
    """--writable-dirs: filtered tree, only paths to writable directories."""

    def _entries(self):
        return {
            "/": [
                _entry("pub", is_dir=True),
                _entry("incoming", is_dir=True, writable=True),
                _entry("readme.txt"),
            ],
            "/pub": [
                _entry("uploads", is_dir=True, writable=True),
                _entry("docs", is_dir=True),
                _entry("index.html"),
            ],
            "/pub/uploads": [],
            "/pub/docs": [],
        }

    def test_writable_dir_appears(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("incoming", output)
        self.assertIn("uploads", output)

    def test_writable_dir_has_badge(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        self.assertIn("[WRITABLE DIR]", out.getvalue())

    def test_non_writable_dirs_pruned(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertNotIn("docs/", output)

    def test_files_pruned(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertNotIn("readme.txt", output)
        self.assertNotIn("index.html", output)

    def test_ancestor_path_shown(self):
        # pub/ is not writable itself but is an ancestor of writable uploads/
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        self.assertIn("pub/", out.getvalue())

    def test_summary_shows_writable_count(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("writable", output)
        self.assertIn("director", output)

    def test_no_findings_message(self):
        entries = {"/": [_entry("pub", is_dir=True)], "/pub": []}
        viewer, out = _make_viewer(entries, writable_dirs=True)
        viewer.render("/")
        self.assertIn("no writable targets found", out.getvalue())


class TestWritableFilesMode(unittest.TestCase):
    """--writable-files: filtered tree, only paths to writable files."""

    def _entries(self):
        return {
            "/": [
                _entry("pub", is_dir=True),
                _entry("config.php", writable=True),
                _entry("readme.txt"),
            ],
            "/pub": [
                _entry("shell.php", writable=True),
                _entry("index.html"),
                _entry("safe_dir", is_dir=True, writable=True),
            ],
            "/pub/safe_dir": [],
        }

    def test_writable_file_appears(self):
        viewer, out = _make_viewer(self._entries(), writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("config.php", output)
        self.assertIn("shell.php", output)

    def test_writable_file_has_badge(self):
        viewer, out = _make_viewer(self._entries(), writable_files=True)
        viewer.render("/")
        self.assertIn("[WRITABLE FILE]", out.getvalue())

    def test_writable_dirs_not_flagged_as_files(self):
        # safe_dir is writable but is a dir — should not appear with --writable-files
        viewer, out = _make_viewer(self._entries(), writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertNotIn("[WRITABLE DIR]", output)
        self.assertNotIn("safe_dir", output)

    def test_non_writable_files_pruned(self):
        viewer, out = _make_viewer(self._entries(), writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertNotIn("readme.txt", output)
        self.assertNotIn("index.html", output)

    def test_summary_shows_writable_file_count(self):
        viewer, out = _make_viewer(self._entries(), writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("writable", output)
        self.assertIn("file", output)


class TestWritableAllMode(unittest.TestCase):
    """writable_dirs=True + writable_files=True: both dirs and files found."""

    def _entries(self):
        return {
            "/": [
                _entry("uploads", is_dir=True, writable=True),
                _entry("config.php", writable=True),
                _entry("readme.txt"),
            ],
            "/uploads": [],
        }

    def test_both_writable_dir_and_file_appear(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True, writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("uploads", output)
        self.assertIn("config.php", output)
        self.assertIn("[WRITABLE DIR]", output)
        self.assertIn("[WRITABLE FILE]", output)

    def test_non_writable_file_pruned(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True, writable_files=True)
        viewer.render("/")
        self.assertNotIn("readme.txt", out.getvalue())

    def test_summary_shows_both_counts(self):
        viewer, out = _make_viewer(self._entries(), writable_dirs=True, writable_files=True)
        viewer.render("/")
        output = out.getvalue()
        self.assertIn("writable director", output)
        self.assertIn("writable file", output)


if __name__ == "__main__":
    unittest.main()
