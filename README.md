# 🔄 File-Syncers

**Safe, one-way file synchronization with SHA256 change detection, automatic backups, and visual diffs.**

[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)](LICENSE)
[![Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen?style=for-the-badge)](https://docs.python.org/3/library/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey?style=for-the-badge)]()

---

A command-line utility that compares files in a **source directory** against matching filenames in a **target project directory**, and selectively updates only what has actually changed — verified by SHA256 hash, not just timestamps. Every overwrite is backed up with a timestamped copy first. You can preview every operation before it runs.

---

## Why File-Syncers?

- **Content-aware sync** — SHA256 hashing means a file is only considered changed if its bytes are actually different, not just because its modification date is newer.
- **Automatic backups** — every file about to be overwritten gets a timestamped `.bak` copy saved to the backup directory before the new version lands. Nothing is silently destroyed.
- **Visual diff preview** — `--show-diff` prints a change summary table showing added lines, removed lines, and the starting line of the first change, per file.
- **Safe by default** — `--dry-run` previews every planned operation without touching a single file on disk.
- **Move or copy** — `--move` deletes the source file after a successful copy; without it, the source is left in place.
- **Self-sync protection** — if the resolved absolute path of the source and destination are identical, the file is skipped automatically.
- **Error-resilient** — all file I/O is wrapped in `try/except`; a failure on one file is logged and skipped, not a crash.

---

## How It Works

1. Scans the **source (downloads) directory** and builds a flat map of `filename → full path`.
2. Recursively walks the **target project directory** with `os.walk()`, skipping any directory names listed in `--ignore-dirs`.
3. For each project file whose name appears in the source map, it computes SHA256 hashes of both copies.
4. If the hashes are equal and `--move` is not active, the file is skipped (already identical).
5. If the hashes differ (or `--move` is active): backs up the project file → copies the source file over it → optionally records the source for deletion.
6. Source file deletions (for `--move`) are batched and applied only after all copy operations complete, to avoid partially transferring a file list.
7. With `--show-diff`, a `difflib.unified_diff` is computed on the text content of each changed pair and a summary table is printed at the end.

> **Note on `--move` and identical files:** When `--move` is active, the skip-if-identical check is bypassed. A backup and copy will still be performed before the source file is deleted, even if the content is the same.

---

## Quick Start

```bash
# Clone the repo
git clone https://github.com/SS-Sauron/File-Syncers.git
cd File-Syncers

# Always start with a dry-run to preview what would happen
python sync_files.py --downloads-path /path/to/source --project-path /path/to/project --dry-run --show-diff

# Live sync — copy changed files and create backups
python sync_files.py --downloads-path /path/to/source --project-path /path/to/project

# Live sync with move — delete source files after a successful copy
python sync_files.py --downloads-path /path/to/source --project-path /path/to/project --move
```

---

## Configuring Your Paths

The script has three built-in defaults that are set to the author's personal machine layout. **You will almost certainly need to override them using the CLI flags described below.**

| Default | Hardcoded Value | Override Flag |
|---|---|---|
| Source directory | `~/Downloads/project` | `--downloads-path` |
| Target project directory | `~/daleel` | `--project-path` |
| Backup directory | `~/Desktop/Project_Backups` | `--backup-path` |

If these directories do not exist when the script runs, it will log an error and exit (except for the backup directory, which is created automatically if it does not exist).

---

## All Flags

| Flag | Type | Default | Description |
|---|---|---|---|
| `--downloads-path` | `str` | `~/Downloads/project` | Source directory to scan for updated files |
| `--project-path` | `str` | `~/daleel` | Target project directory to sync into |
| `--backup-path` | `str` | `~/Desktop/Project_Backups` | Directory where pre-overwrite backups are stored |
| `--dry-run` | `flag` | `False` | Preview all planned operations without modifying anything |
| `--show-diff` | `flag` | `False` | Display a unified diff summary table (added/removed lines per file) |
| `--move` | `flag` | `False` | Delete source files from the source directory after a successful copy |
| `--ignore-dirs` | `str...` | `.git node_modules venv __pycache__` | Space-separated list of directory names to skip during the project walk |
| `--log-level` | `choice` | `INFO` | Logging verbosity: `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

---

## Example Output

```
--- 📂 Backup target set to: /home/user/Desktop/Project_Backups ---
2026-05-28 14:32:01,443 - INFO - Found 3 files in downloads directory.
2026-05-28 14:32:01,444 - INFO - --- LIVE SYNC ---
2026-05-28 14:32:01,451 - INFO - [SUCCESS] Updated & backed up: utils.py
2026-05-28 14:32:01,458 - INFO - [SUCCESS] Updated & backed up: config.py
2026-05-28 14:32:01,460 - INFO - Sync complete. Updated: 2, Skipped: 1, Errors: 0.

--- CHANGE SUMMARY ---
File Path                                          Added  Removed  Starting Line
-------------------------------------------------------------------------------------
src/utils.py                                       4      2        Line 18
src/config.py                                      1      0        Line 7
```

---

## Safety Features

- **Timestamped backups** — backup format: `filename.YYYYMMDD_HHMMSS.bak`. Multiple syncs in the same day create distinct backups.
- **Dry-run mode** — no file is created, modified, or deleted. Every planned action is logged with the `[PREVIEW]` prefix.
- **Error resilience** — all file I/O (`open`, `shutil.copy2`, `os.remove`) is wrapped in `try/except`. An error on one file is logged and skipped; the remaining files continue.
- **Same-file protection** — if `os.path.abspath(source)` equals `os.path.abspath(destination)`, the file is skipped silently, preventing accidental self-overwrites.
- **Batched deletes on move** — when `--move` is active, source file deletions are queued and applied only after all copies succeed, reducing the risk of data loss from a mid-sync failure.

---

## Tech Stack

Python 3.8+ with the standard library only — no `pip install` required.

| Module | Purpose |
|---|---|
| `pathlib` | Cross-platform home directory detection (`Path.home()`) |
| `hashlib` | SHA256 content hashing in 4096-byte chunks |
| `difflib` | Unified diff generation for `--show-diff` |
| `shutil` | File copy with metadata (`copy2`) |
| `argparse` | CLI flag parsing |
| `logging` | Structured, levelled output |
| `os` | Directory walking (`os.walk`), path resolution, file deletion |

---

## Legacy

The [`legacy/`](legacy/) folder contains earlier versions of the script, kept for reference. These versions are not maintained and should not be used in production. See [`legacy/README.md`](legacy/README.md) for details.

---

## Roadmap

The following are ideas for future development. **None of these are currently implemented.**

- [ ] Watch mode — auto-sync when files change in the source directory (via `watchdog`)
- [ ] Configuration file support (YAML or TOML) to store paths and preferences without CLI flags
- [ ] Multi-source sync — watch more than one source directory in a single run
- [ ] Notifications on sync completion (e.g., desktop notification, Slack/Telegram webhook)

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request.

---

## License

MIT License — see [LICENSE](LICENSE) for full text.
