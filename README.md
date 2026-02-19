# ftp-tree-viewer

Visualize an FTP server's directory structure as a tree, exactly like the `tree` command — with extra flags useful for security assessments.

```
/
├── pub/
│   ├── uploads/ [WRITABLE]
│   │   └── .hidden_file
│   └── readme.txt
├── incoming/ [WRITABLE]
└── .ftpquota

2 directories, 3 files
```

## Features

| Flag | Description |
|------|-------------|
| `-l` / `--permissions` | Show permissions (`rwxr-xr-x`). Auto-detects Unix vs Windows FTP servers. |
| `-a` / `--all` | Show hidden files (names starting with `.`) |
| `-s` / `--size` | Show human-readable file sizes |
| `-m` / `--modified` | Show last-modified timestamps |
| `--writable` | Highlight world/group-writable directories in red — key for recon |
| `--tls` | Connect over FTPS (TLS) |
| `-d` / `--depth N` | Limit recursion to N levels |
| `--banner` | Print the server's welcome banner |
| `-o FILE` | Save a plain-text copy (ANSI stripped) to a file |
| `--no-color` | Disable colored output |
| `--active` | Use FTP active mode instead of passive |

## Installation

```bash
pip install -r requirements.txt
# or install as a package (adds `ftp-tree` command):
pip install -e .
```

## Usage

```bash
# Anonymous login, default depth
ftp-tree 192.168.1.1

# Authenticated with permissions, sizes, hidden files
ftp-tree 192.168.1.1 -u admin -l -s -a

# Scan for writable directories (recon)
ftp-tree 192.168.1.1 -u ftpuser --writable

# FTPS on port 990, start at /var/www, save report
ftp-tree 192.168.1.1 --tls -p 990 --path /var/www -o report.txt

# Full info at depth 3, prompt for password
ftp-tree 192.168.1.1 -u admin -l -s -m -a --writable --banner -d 3
```

## OS Auto-detection

`ftp-tree` detects whether the server is Unix or Windows by inspecting the raw `LIST` output format:

- **Unix**: `drwxr-xr-x 2 owner group 4096 Jan  1 00:00 dirname`
- **Windows**: `11-01-21  01:00PM <DIR>  dirname`

On Windows servers, permissions are shown as `[unavailable]` since they are not exposed over FTP.

## Color key

| Color | Meaning |
|-------|---------|
| Blue | Directory |
| Red | Writable directory (when `--writable` is active) |
| Cyan | Symlink |
| White/dim | Hidden file (starts with `.`) |

## Running tests

```bash
python -m pytest tests/ -v
# or with unittest directly:
python -m unittest discover tests/
```

## Ethical use

This tool is intended for **authorized security assessments, CTF challenges, and network administration**. Only use it against FTP servers you own or have explicit written permission to test.
