#!/usr/bin/env python3
"""
ftp-tree — visualize an FTP server as a directory tree.

Usage examples
--------------
  # Anonymous login, show everything at depth 3
  ftp-tree 192.168.1.1 --depth 3

  # Authenticated, show permissions + sizes + hidden files
  ftp-tree 192.168.1.1 -u admin -l -s -a

  # Highlight world/group-writable directories (useful for recon)
  ftp-tree 192.168.1.1 -u ftpuser --writable

  # FTPS (TLS), start at /var/www, save clean copy to file
  ftp-tree 192.168.1.1 --tls -p 990 --path /var/www -o report.txt

  # Find writable directories only (filtered path view)
  ftp-tree 192.168.1.1 -u ftpuser --writable-dirs

  # Find writable files only
  ftp-tree 192.168.1.1 -u ftpuser --writable-files

  # Find both writable dirs and files
  ftp-tree 192.168.1.1 -u ftpuser --writable-all

  # Full info dump
  ftp-tree 192.168.1.1 -u admin -l -s -m -a --writable-all --banner
"""

import argparse
import getpass
import sys

from ftp_tree.client import FTPClient, FTPClientError
from ftp_tree.tree import FTPTreeViewer


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ftp-tree",
        description="Visualize an FTP server as a directory tree.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Connection
    p.add_argument("host", help="FTP server hostname or IP address")
    p.add_argument("-p", "--port", type=int, default=21,
                   help="FTP port (default: 21; FTPS common default: 990)")
    p.add_argument("-u", "--user", default="anonymous",
                   help="Username (default: anonymous)")
    p.add_argument("-P", "--password", default=None,
                   help="Password — omit to be prompted securely")
    p.add_argument("--tls", action="store_true",
                   help="Use FTPS (explicit or implicit TLS)")
    p.add_argument("--active", action="store_true",
                   help="Use active mode instead of passive (default: passive)")
    p.add_argument("--timeout", type=int, default=30,
                   help="Connection timeout in seconds (default: 30)")

    # Navigation
    p.add_argument("--path", default="/",
                   help="Starting path on the server (default: /)")
    p.add_argument("-d", "--depth", type=int, default=None,
                   help="Maximum recursion depth (unlimited by default)")

    # Display
    p.add_argument("-a", "--all", dest="show_hidden", action="store_true",
                   help="Show hidden files and directories (names starting with '.')")
    p.add_argument("-l", "--permissions", action="store_true",
                   help="Show permissions (Unix servers) or [unavailable] (Windows)")
    p.add_argument("-s", "--size", action="store_true",
                   help="Show file sizes in human-readable format")
    p.add_argument("-m", "--modified", action="store_true",
                   help="Show last-modified timestamps")
    writable = p.add_mutually_exclusive_group()
    writable.add_argument("--writable-dirs", action="store_true",
                          help="Show only paths leading to world/group-writable directories, "
                               "highlighted in red")
    writable.add_argument("--writable-files", action="store_true",
                          help="Show only paths leading to world/group-writable files, "
                               "highlighted in red")
    writable.add_argument("--writable-all", action="store_true",
                          help="Show only paths leading to writable directories AND files")
    p.add_argument("--no-color", action="store_true",
                   help="Disable colored output")
    p.add_argument("--banner", action="store_true",
                   help="Print the server's welcome banner")

    # Output
    p.add_argument("-o", "--output", metavar="FILE",
                   help="Save a plain-text copy of the tree to FILE (ANSI codes stripped)")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve password
    password = args.password
    if password is None:
        if args.user.lower() in ("anonymous", "anon", "ftp", ""):
            password = "anonymous@"
        else:
            try:
                password = getpass.getpass(f"Password for {args.user}@{args.host}: ")
            except (KeyboardInterrupt, EOFError):
                print("\nAborted.", file=sys.stderr)
                sys.exit(1)

    # Open optional output file
    file_out = None
    if args.output:
        try:
            file_out = open(args.output, "w", encoding="utf-8")
        except OSError as e:
            print(f"Error: cannot open output file '{args.output}': {e}", file=sys.stderr)
            sys.exit(1)

    client = FTPClient(
        host=args.host,
        port=args.port,
        timeout=args.timeout,
        use_tls=args.tls,
        passive=not args.active,
    )

    try:
        print(
            f"[*] Connecting to {args.host}:{args.port}"
            f"{' (TLS)' if args.tls else ''} ...",
            file=sys.stderr,
        )
        client.connect(args.user, password)

        if args.banner:
            print(f"[*] Banner : {client.get_banner()}", file=sys.stderr)

        print(f"[*] Server OS  : {client.server_os.value}", file=sys.stderr)
        print(f"[*] Anonymous  : {'yes' if client.is_anonymous else 'no'}", file=sys.stderr)
        print(file=sys.stderr)

        viewer = FTPTreeViewer(
            client=client,
            show_hidden=args.show_hidden,
            show_perms=args.permissions,
            show_size=args.size,
            show_modified=args.modified,
            max_depth=args.depth,
            no_color=args.no_color,
            writable_dirs=args.writable_dirs or args.writable_all,
            writable_files=args.writable_files or args.writable_all,
            file_out=file_out,
        )
        viewer.render(args.path)

    except FTPClientError as e:
        print(f"[!] {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[!] Interrupted.", file=sys.stderr)
        sys.exit(0)
    finally:
        client.disconnect()
        if file_out:
            file_out.close()


if __name__ == "__main__":
    main()
