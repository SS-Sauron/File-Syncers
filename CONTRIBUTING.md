# Contributing to File-Syncers

Thanks for your interest in contributing. Because this tool performs real, irreversible file operations (copying and optionally deleting files), there are specific testing and safety requirements before any code changes are submitted.

---

## Ground Rules

- **Always test with `--dry-run` first.** Any code path that touches the filesystem must be validated in dry-run mode before a live test.
- **Keep zero external dependencies.** The tool uses only the Python standard library. Do not introduce any `pip`-installable package. If a feature genuinely requires a third-party library, open an issue to discuss it before writing any code.
- **Preserve backward compatibility.** All CLI flags must remain unchanged in name and default behavior. Adding new flags is fine; renaming or removing existing ones is not.

---

## Setting Up a Test Environment

Do not test against your real project directories. Create a controlled fixture instead:

```bash
# Create a source and target directory with dummy files
mkdir -p /tmp/fs_test/source
mkdir -p /tmp/fs_test/project/subdir
mkdir -p /tmp/fs_test/backups

echo "version 1" > /tmp/fs_test/project/example.txt
echo "version 2" > /tmp/fs_test/source/example.txt

# Dry-run first
python sync_files.py \
  --downloads-path /tmp/fs_test/source \
  --project-path   /tmp/fs_test/project \
  --backup-path    /tmp/fs_test/backups \
  --dry-run --show-diff

# Live run
python sync_files.py \
  --downloads-path /tmp/fs_test/source \
  --project-path   /tmp/fs_test/project \
  --backup-path    /tmp/fs_test/backups \
  --show-diff
```

Verify that:
- A `.bak` file appears in `/tmp/fs_test/backups/`
- The content of `project/example.txt` is updated
- The source file is still present (unless `--move` was used)

---

## Testing Checklist

Before submitting a PR, confirm you have tested all of the following scenarios in a scratch directory:

- [ ] `--dry-run` with changed files — output shows `[PREVIEW]` lines, no files modified
- [ ] `--dry-run` with identical files — files are logged as skipped
- [ ] Live sync with changed files — backup created, project file updated
- [ ] Live sync with identical files — files skipped, no backup created
- [ ] `--move` flag — source file is deleted after a successful copy
- [ ] `--show-diff` — change summary table appears, added/removed counts are correct
- [ ] `--ignore-dirs` — a directory that should be ignored is not synced into
- [ ] `--log-level DEBUG` — verbose output is shown
- [ ] Non-existent `--downloads-path` — script logs an error and exits cleanly
- [ ] Non-existent `--project-path` — script logs an error and exits cleanly
- [ ] Same source and destination file (same `abspath`) — file is skipped, no backup created

---

## Code Style

- Follow [PEP 8](https://peps.python.org/pep-0008/). Max line length: 100 characters.
- Use f-strings (Python 3.6+) rather than `.format()` or `%` interpolation.
- All functions must have a docstring (even one-liners).
- Use `pathlib.Path` for new path manipulation code rather than raw `os.path` string joins.
- Do not use `print()` for operational output — use `logging.info()`, `logging.warning()`, or `logging.error()` so that `--log-level` controls it. The `--show-diff` summary table is the only acceptable use of `print()` in the current codebase.
- All file I/O must be wrapped in `try/except (OSError, IOError)`. Let the error counter increment; do not `raise` or `sys.exit()` from within the sync loop.

---

## Commit Message Convention

Use the following prefixes for commit messages:

| Prefix | When to use |
|---|---|
| `fix:` | Bug fixes |
| `feat:` | New features or flags |
| `docs:` | README, CONTRIBUTING, docstrings, inline comments |
| `refactor:` | Code changes with no behaviour change |
| `test:` | Adding or updating test fixtures or instructions |
| `chore:` | Maintenance (`.gitignore`, repo meta, etc.) |

Examples:
```
fix: skip identical files when --move is active only if source equals dest
feat: add --extensions flag to filter files by suffix
docs: clarify --move batching behaviour in README
```

---

## Pull Request Process

1. **Open an issue** describing your proposed change before writing code. This avoids wasted effort if the change conflicts with the project direction.
2. **Fork** the repository and create a branch from `master`:
   ```bash
   git checkout -b fix/your-fix-name
   # or
   git checkout -b feat/your-feature-name
   ```
3. **Write code and test it** using the fixture setup above. All checklist items applicable to your change must pass.
4. **Update documentation** — if your change adds or modifies a CLI flag, update the flags table in `README.md`. If it changes behaviour, update the relevant section of the README.
5. **Submit your PR** with:
   - A clear title following the commit convention above
   - A description of what changed and why
   - Which checklist items you tested and what your test setup looked like
   - Any known limitations

PRs that modify file-writing or file-deleting code paths without a documented test of the backup and dry-run behaviour will be asked to add it before merging.

---

## Reporting Issues

When reporting a bug, please include:

- Your operating system and Python version (`python --version`)
- The exact command you ran (redact real paths if needed)
- What you expected to happen
- What actually happened (paste the full terminal output)
- Whether `--dry-run` reproduces the issue or only the live run does

If a file was **unexpectedly deleted or overwritten**, that is a high-priority bug. Please include the backup directory contents if the backups still exist.
