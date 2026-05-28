# Changelog

All notable changes to File-Syncers are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [1.0.0] — 2026-05-28 — First Stable Release

### Added

- **`sync_files.py`** — core one-way file synchronization script.
- **SHA256 content hashing** — files are compared by content digest, not modification timestamp. Unchanged files are skipped even if their dates differ.
- **Automatic timestamped backups** — every project file that is about to be overwritten is first copied to the backup directory as `filename.YYYYMMDD_HHMMSS.bak`.
- **`--dry-run` mode** — previews all planned operations (`[PREVIEW]` log lines) without modifying, creating, or deleting any file.
- **`--show-diff` mode** — displays a per-file change summary table after the sync, showing added lines, removed lines, and the starting line of the first change, using `difflib.unified_diff`.
- **`--move` flag** — deletes source files from the source directory after a successful copy. Deletions are batched and applied only after all copies complete.
- **`--ignore-dirs`** — configurable list of directory names to skip during the project walk (defaults: `.git`, `node_modules`, `venv`, `__pycache__`).
- **`--log-level`** — controls logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`).
- **`--downloads-path`**, **`--project-path`**, **`--backup-path`** — fully configurable source, target, and backup directories via CLI.
- **Self-sync protection** — skips any file pair where `os.path.abspath(source) == os.path.abspath(destination)`.
- **Error resilience** — all file I/O is wrapped in `try/except`; per-file errors are logged and counted without stopping the rest of the run.
- **Cross-platform home directory detection** — uses `pathlib.Path.home()` for default path resolution, compatible with Windows, macOS, and Linux.
- **Zero external dependencies** — uses only the Python standard library (`os`, `shutil`, `hashlib`, `argparse`, `logging`, `difflib`, `pathlib`).
- `README.md`, `CONTRIBUTING.md`, `LICENSE` (MIT), `.gitignore`.
- `legacy/` folder preserving earlier script versions for historical reference.

---

## Unreleased

Features planned for future releases are tracked in the [Roadmap section of the README](README.md#roadmap).
