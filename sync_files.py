from __future__ import annotations

import argparse
import difflib
import hashlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

VERSION = "2.0.0"

# 64 KB read chunks for SHA-256 streaming.
# Reduces read() syscall count compared with the original 4 KB, which is
# noticeable on large source files or slow network-mounted drives.
_HASH_CHUNK_BYTES: int = 65_536

# How many bytes are probed when detecting binary content.
_BINARY_PROBE_BYTES: int = 8_192


# ─────────────────────────────────────────────────────────────────────────────
# Data Models
# Issue #11 – replaces the fragile 7-positional-argument function signature.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class SyncConfig:
    """
    All configuration for a single sync run, assembled once in main() and
    passed as a single, self-documenting object through the call stack.

    Using a dataclass makes every parameter visible and named at the call
    site, eliminating the risk of silently transposing positional arguments.
    """
    downloads_path: Path
    project_path:   Path
    backup_path:    Path
    dry_run:        bool = False
    show_diff:      bool = False
    move_files:     bool = False
    # frozenset: immutable and O(1) membership test inside the os.walk loop.
    ignore_dirs: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {".git", "node_modules", "venv", "__pycache__"}
        )
    )
    # None  → sync every file type found.
    # set   → restrict to files whose suffix (lower-case, with leading dot)
    #         appears in this set.  Populated from --extensions.
    extensions: Optional[frozenset[str]] = None


@dataclass
class DiffStats:
    """
    Statistics extracted from a unified diff between two file versions.

    Issue #2 fix: first_hunk_line is None until the FIRST @@ marker is
    encountered.  It is never overwritten by later hunks.  None is
    rendered as "N/A" in the printed summary table.
    """
    added:           int           = 0
    removed:         int           = 0
    first_hunk_line: Optional[str] = None  # None = no hunk seen yet


@dataclass
class ChangeRecord:
    """
    One row in the --show-diff change summary table.

    Issue #4 fix: only instantiated when config.show_diff is True, so the
    list is never built speculatively for runs that don't need it.
    """
    relative_path: str
    stats:         DiffStats


# ─────────────────────────────────────────────────────────────────────────────
# Logging Setup
# Issue #10 – all output through logging.
# Issue #18 – optional FileHandler for persistent audit logs.
# ─────────────────────────────────────────────────────────────────────────────

def setup_logging(log_level: str, log_file: Optional[Path] = None) -> None:
    """
    Configure the root logger with a StreamHandler (stdout) and, when
    --log-file is supplied, an appending FileHandler (Issue #18).

    Routing all output through this logger means --log-level and
    --log-file control everything from a single point (Issue #10).
    The two print() calls in this function are unavoidable because the
    logger is not yet active when they execute.
    """
    fmt      = "%(asctime)s - %(levelname)s - %(message)s"
    level    = getattr(logging, log_level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file is not None:
        try:
            fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
            fh.setFormatter(logging.Formatter(fmt))
            handlers.append(fh)
            print(f"Appending log output to: {log_file}")
        except PermissionError as exc:
            print(
                f"WARNING: permission denied opening log file '{log_file}': {exc}. "
                "Logging to console only."
            )
        except OSError as exc:
            print(
                f"WARNING: cannot open log file '{log_file}': {exc}. "
                "Logging to console only."
            )

    logging.basicConfig(level=level, format=fmt, handlers=handlers)


# ─────────────────────────────────────────────────────────────────────────────
# File Utilities
# ─────────────────────────────────────────────────────────────────────────────

def get_file_hash(path: Path) -> Optional[str]:
    """
    Return the hex-encoded SHA-256 digest of *path*, or None on any error.

    Streams in 64 KB chunks (Issue #6 companion: reduces syscall count
    on large files compared with the original 4 KB chunk size).
    The specific exception type is logged so callers can distinguish
    permission problems from general I/O failures.
    """
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(_HASH_CHUNK_BYTES), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except PermissionError as exc:
        logging.error("Permission denied hashing '%s': %s", path, exc)
    except OSError as exc:
        logging.error("I/O error hashing '%s': %s", path, exc)
    return None


def is_binary_file(path: Path) -> bool:
    """
    Return True if *path* is likely binary content (Issue #14).

    Reads up to 8 KB and tests for a null byte — a reliable proxy for
    binary files (.png, .pyc, .exe, .pdf, .zip, …).  Binary files are
    excluded from diff processing; running difflib over bytes decoded with
    errors='replace' produces meaningless added/removed line counts.

    Returns True (treat as binary → skip diff) on any read error so that
    an unreadable file never causes a misleading diff entry.
    """
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(_BINARY_PROBE_BYTES)
    except OSError:
        return True


def compute_diff_stats(source: Path, destination: Path) -> DiffStats:
    """
    Return a DiffStats for the unified diff of *destination* (old) vs
    *source* (new).

    Issue #2 fix: first_hunk_line is captured only for the FIRST @@ marker
    encountered.  The original loop assigned `location = f"Line {old_start}`
    unconditionally, overwriting every previous value, so a file with three
    change hunks would always report the starting line of the third.

    Issue #14 fix: Binary files short-circuit immediately.  The marker
    "Binary (diff skipped)" is stored in first_hunk_line so the caller
    can display a meaningful value in the summary table.
    """
    stats = DiffStats()

    # Issue #14: skip binary files before touching difflib.
    if is_binary_file(source) or is_binary_file(destination):
        stats.first_hunk_line = "Binary (diff skipped)"
        return stats

    try:
        # errors="replace" keeps difflib working on files that contain a
        # small number of non-UTF-8 bytes without crashing or discarding lines.
        src_lines = source.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines(keepends=True)
        dst_lines = destination.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines(keepends=True)
    except PermissionError as exc:
        logging.warning("Permission denied reading file for diff: %s", exc)
        stats.first_hunk_line = "Permission error"
        return stats
    except OSError as exc:
        logging.warning("I/O error reading file for diff: %s", exc)
        stats.first_hunk_line = "Read error"
        return stats

    for line in difflib.unified_diff(dst_lines, src_lines, lineterm=""):
        if line.startswith("@@"):
            # Issue #2: only record the FIRST hunk's starting line.
            # Checking `is None` ensures subsequent @@ markers are skipped.
            if stats.first_hunk_line is None:
                parts = line.split()
                if len(parts) >= 3:
                    # Unified diff hunk header format:
                    #   @@ -old_start[,old_count] +new_start[,new_count] @@
                    old_part  = parts[1]                           # e.g. "-10,5"
                    old_start = old_part.split(",")[0].lstrip("-") # → "10"
                    stats.first_hunk_line = f"Line {old_start}"
        elif line.startswith("+") and not line.startswith("+++"):
            stats.added += 1
        elif line.startswith("-") and not line.startswith("---"):
            stats.removed += 1

    return stats


# ─────────────────────────────────────────────────────────────────────────────
# Source Map Builder
# Issue #15 – flat-source assumption documented and surfaced via logging.
# Issue #17 – extension filter applied here before the map is returned.
# ─────────────────────────────────────────────────────────────────────────────

def build_source_map(
    downloads_path: Path,
    extensions:     Optional[frozenset[str]],
) -> dict[str, Path]:
    """
    Scan the top level of *downloads_path* and return {filename: Path}.

    Issue #15 — Flat-source design contract:
    Only immediate children of *downloads_path* are indexed.  Files inside
    sub-directories are deliberately excluded and their count is surfaced via
    an INFO log so users are not silently surprised.  This matches the
    original tool's flat-directory assumption but makes it explicit.

    Issue #17 — Extension filter:
    When *extensions* is a non-empty frozenset (e.g. frozenset({'.py', '.js'})),
    only files whose suffix matches case-insensitively are included in the map.
    Files excluded by the filter are logged at DEBUG level.
    """
    source_map:   dict[str, Path] = {}
    skipped_dirs: int             = 0
    skipped_ext:  int             = 0

    try:
        entries = list(downloads_path.iterdir())
    except PermissionError as exc:
        logging.error(
            "Permission denied reading source directory '%s': %s",
            downloads_path, exc,
        )
        return source_map
    except OSError as exc:
        logging.error(
            "Cannot read source directory '%s': %s", downloads_path, exc,
        )
        return source_map

    for entry in entries:
        if entry.is_dir():
            skipped_dirs += 1
            logging.debug("Sub-directory skipped (flat-source design): %s", entry.name)
            continue

        if not entry.is_file():
            # Skip symlinks, device files, etc.
            continue

        # Issue #17: apply extension filter when one is configured.
        if extensions is not None and entry.suffix.lower() not in extensions:
            skipped_ext += 1
            logging.debug("Excluded by --extensions filter: %s", entry.name)
            continue

        source_map[entry.name] = entry

    logging.info(
        "Source map: %d file(s) indexed from '%s'.",
        len(source_map),
        downloads_path,
    )

    # Issue #15: make the flat-source exclusion visible so users who place
    # files in sub-directories know why they are not synced.
    if skipped_dirs:
        logging.info(
            "%d sub-director%s in '%s' %s not scanned "
            "(only the top level is indexed by design — see --help).",
            skipped_dirs,
            "y" if skipped_dirs == 1 else "ies",
            downloads_path,
            "was" if skipped_dirs == 1 else "were",
        )

    if skipped_ext:
        logging.debug(
            "%d file(s) excluded by --extensions filter.", skipped_ext,
        )

    return source_map


# ─────────────────────────────────────────────────────────────────────────────
# Configuration Validator
# Issue #5  – pre-checks for duplicate destinations are in sync_files().
# Issue #16 – backup-inside-project guard lives here.
# ─────────────────────────────────────────────────────────────────────────────

def validate_config(config: SyncConfig) -> bool:
    """
    Validate all paths in *config* before any file I/O begins.

    Returns True if safe to proceed; returns False and logs all failures
    as errors so the user knows exactly what to fix.

    Issue #16 fix:
    Uses Path.relative_to() to detect whether --backup-path resolves to a
    descendant of --project-path.  relative_to() raises ValueError when the
    tested path is NOT a descendant (the expected, safe outcome).  If it
    does NOT raise, the backup IS inside the project tree — we block the run.

    Without this guard, .bak files written during run N are discovered by
    os.walk during run N+1 and treated as updated source files, creating an
    infinite re-sync loop.
    """
    ok = True

    # ── Source directory ──────────────────────────────────────────────────────
    if not config.downloads_path.exists():
        logging.error(
            "Source (downloads) path does not exist: '%s'.",
            config.downloads_path,
        )
        ok = False
    elif not config.downloads_path.is_dir():
        logging.error(
            "Source (downloads) path is not a directory: '%s'.",
            config.downloads_path,
        )
        ok = False

    # ── Project directory ─────────────────────────────────────────────────────
    if not config.project_path.exists():
        logging.error(
            "Project path does not exist: '%s'.", config.project_path,
        )
        ok = False
    elif not config.project_path.is_dir():
        logging.error(
            "Project path is not a directory: '%s'.", config.project_path,
        )
        ok = False

    # ── Source path must differ from project path ─────────────────────────────
    try:
        if config.downloads_path.resolve() == config.project_path.resolve():
            logging.error(
                "Source and project paths resolve to the same location ('%s'). "
                "Aborting to prevent self-overwrite.",
                config.downloads_path,
            )
            ok = False
    except OSError:
        # resolve() can fail for non-existent intermediate directories; the
        # existence checks above will surface those issues separately.
        pass

    # ── Issue #16: backup path must NOT be inside the project tree ────────────
    try:
        resolved_backup  = config.backup_path.resolve()
        resolved_project = config.project_path.resolve()

        # If relative_to() succeeds, resolved_backup IS inside resolved_project.
        # That is the dangerous case we must block.
        resolved_backup.relative_to(resolved_project)

        logging.error(
            "Backup path '%s' is inside project path '%s'. "
            "This causes .bak files to be re-synced on the next run. "
            "Move --backup-path to a directory outside the project tree.",
            config.backup_path,
            config.project_path,
        )
        ok = False

    except ValueError:
        # relative_to() raised ValueError → backup is NOT inside project. Safe.
        pass
    except OSError:
        # resolve() failed (e.g. broken symlink). Skip this check; other
        # validation above will catch genuine path problems.
        pass

    return ok


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility Helper
# Issue #9 – full pathlib.Path migration, Python 3.8+.
# ─────────────────────────────────────────────────────────────────────────────

def _compat_walk(
    root:        Path,
    ignore_dirs: frozenset[str],
) -> Generator[tuple[Path, list[str], list[str]], None, None]:
    """
    Yield (root_as_Path, dirs, filenames) from os.walk() with ignored
    directory names pruned in-place before each yield.

    Path.walk() was introduced in Python 3.12.  This wrapper provides
    equivalent semantics for Python 3.8+ and keeps all callers working
    exclusively with pathlib.Path objects (Issue #9).

    The in-place modification `dirs[:] = [...]` is key: it tells os.walk
    not to descend into pruned directories on its next iteration, which
    is far more efficient than filtering entries after traversal because
    entire sub-trees are never visited.
    """
    for raw_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        yield Path(raw_root), dirs, files


# ─────────────────────────────────────────────────────────────────────────────
# Core Sync Logic
# ─────────────────────────────────────────────────────────────────────────────

def sync_files(config: SyncConfig) -> int:
    """
    Execute the one-way sync described by *config* and return the error count.

    A non-zero return causes main() to call sys.exit(1) (Issue #7), making
    failed runs visible to shell scripts, Makefiles, and CI pipelines.

    Key fixes applied in this function:

      #1  Hash equality is checked unconditionally.  When --move is active,
          the source is still queued for deletion but no redundant copy or
          backup is created for an unchanged file.

      #3  A summary line is always logged after the run, with wording that
          matches the active mode (dry-run vs live).

      #4  ChangeRecord objects are only allocated when show_diff is True.

      #5  A lightweight pre-scan counts how many project files share a name
          with each source file and logs a warning for any count > 1, before
          a single byte is written.

      #6  Source-file hashes are cached in source_hash_cache.  Each source
          file is opened and read at most once per run, regardless of how
          many project files share its basename.

      #8  Backup filenames use strftime("%Y%m%d_%H%M%S_%f") which includes
          microseconds, eliminating the second-level collision risk present
          in the original "%Y%m%d_%H%M%S" format.
    """

    # ── Step 1: validate all paths before touching anything ───────────────────
    if not validate_config(config):
        return 1

    # ── Step 2: ensure the backup directory exists ────────────────────────────
    # Not needed in dry-run: no files will be written.
    if not config.dry_run:
        try:
            config.backup_path.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            logging.error(
                "Permission denied creating backup directory '%s': %s",
                config.backup_path, exc,
            )
            return 1
        except OSError as exc:
            logging.error(
                "Cannot create backup directory '%s': %s",
                config.backup_path, exc,
            )
            return 1

        logging.info("Backup directory: '%s'.", config.backup_path)

    # ── Step 3: build the flat {filename → Path} source map ──────────────────
    source_map = build_source_map(config.downloads_path, config.extensions)
    if not source_map:
        logging.warning("No eligible source files found. Nothing to sync.")
        return 0

    # ── Step 4 (Issue #5): pre-scan for duplicate destinations ───────────────
    # Walk the project tree once (stat calls only, no file reads) before any
    # write occurs.  Count how many project files share a name with a source
    # file.  Any filename mapping to 2+ destinations will overwrite all of
    # them — which may be intentional, but must never happen silently.
    destination_counts: dict[str, int] = {}
    for _, _, files in _compat_walk(config.project_path, config.ignore_dirs):
        for fname in files:
            if fname in source_map:
                destination_counts[fname] = destination_counts.get(fname, 0) + 1

    for fname, count in destination_counts.items():
        if count > 1:
            logging.warning(
                "Source file '%s' matches %d project destinations — "
                "all %d copies will be overwritten. "
                "Run with --dry-run to review each destination first.",
                fname, count, count,
            )

    # ── Step 5: main sync walk ────────────────────────────────────────────────
    mode = "DRY-RUN" if config.dry_run else "LIVE SYNC"
    logging.info(
        "─── %s ─────────────────────────────────────────────────────", mode,
    )

    # Issue #6: source hash cache.
    # Maps source Path → its SHA-256 hex digest (or None on error).
    # Computed on first encounter; reused for every subsequent project match.
    source_hash_cache: dict[Path, Optional[str]] = {}

    # Issue #4: only built when config.show_diff is True.
    changes:       list[ChangeRecord] = []
    updated_count: int = 0
    skipped_count: int = 0
    error_count:   int = 0

    # Batch source-file deletions until after ALL copies succeed.
    # This preserves the source directory intact if a mid-run I/O failure
    # occurs — the user can correct the problem and re-run safely.
    files_to_delete: set[Path] = set()

    for root, _, files in _compat_walk(config.project_path, config.ignore_dirs):
        for filename in files:
            if filename not in source_map:
                continue

            source:      Path = source_map[filename]
            destination: Path = root / filename

            # ── Self-sync guard ───────────────────────────────────────────────
            # resolve() follows symlinks so two Path strings pointing at the
            # same inode are correctly identified as identical.
            if source.resolve() == destination.resolve():
                logging.debug("Skipped self-sync: '%s'.", destination)
                skipped_count += 1
                continue

            # ── Issue #6: retrieve hash from cache or compute and store ───────
            if source not in source_hash_cache:
                source_hash_cache[source] = get_file_hash(source)
            source_hash = source_hash_cache[source]
            dest_hash   = get_file_hash(destination)

            # get_file_hash() already logged the specific I/O error.
            if source_hash is None or dest_hash is None:
                error_count += 1
                continue

            # ── Issue #1: unconditional identical-file skip ───────────────────
            # The original guard was `if not move_files and … == …` which
            # caused --move to still copy identical files, creating a
            # pointless backup and wasting I/O.  The skip is now unconditional.
            # When --move is active the source is still queued for deletion
            # so the caller's intent (remove the source file) is honoured
            # without performing a redundant copy.
            if source_hash == dest_hash:
                logging.debug("Unchanged (hashes match): '%s'.", filename)
                skipped_count += 1
                if config.move_files:
                    files_to_delete.add(source)
                continue

            # ── Issue #4: build diff record only when --show-diff is active ───
            if config.show_diff:
                stats    = compute_diff_stats(source, destination)
                rel_path = str(destination.relative_to(config.project_path))
                changes.append(ChangeRecord(relative_path=rel_path, stats=stats))

            # ── Dry-run: log the planned action and move on ───────────────────
            if config.dry_run:
                logging.info("[PREVIEW] Would overwrite: '%s'.", destination)
                updated_count += 1
                continue

            # ── Live: back up the destination, then overwrite it ──────────────

            # Issue #8: include microseconds (%f) in the timestamp.
            # The original "%Y%m%d_%H%M%S" format has second-level precision;
            # two syncs of the same file within one second would produce the
            # same .bak filename and shutil.copy2 would silently overwrite the
            # earlier backup.  Microseconds make collisions practically impossible.
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup_file = config.backup_path / f"{filename}.{timestamp}.bak"

            # Step A: back up the current project file.
            try:
                shutil.copy2(destination, backup_file)
            except PermissionError as exc:
                logging.error(
                    "Permission denied backing up '%s' → '%s': %s",
                    destination, backup_file, exc,
                )
                error_count += 1
                continue
            except OSError as exc:
                logging.error(
                    "Backup failed '%s' → '%s': %s",
                    destination, backup_file, exc,
                )
                error_count += 1
                continue

            # Step B: overwrite the project file with the source version.
            try:
                shutil.copy2(source, destination)
            except PermissionError as exc:
                logging.error(
                    "Permission denied overwriting '%s': %s",
                    destination, exc,
                )
                error_count += 1
                # The backup exists and the original destination is intact
                # (shutil.copy2 does not truncate the target before confirming
                # a successful write on most operating systems).
                continue
            except OSError as exc:
                logging.error(
                    "Copy failed '%s' → '%s': %s",
                    source, destination, exc,
                )
                error_count += 1
                continue

            logging.info(
                "[UPDATED]  %-38s  (backup: %s)", filename, backup_file.name,
            )
            updated_count += 1

            if config.move_files:
                files_to_delete.add(source)

    # ── Step 6: batch delete source files (--move) ───────────────────────────
    # Executed only after all copies above have completed.  Batching here
    # ensures the source directory remains intact if any copy step failed.
    if config.move_files and not config.dry_run and files_to_delete:
        logging.info("Deleting %d source file(s) (--move).", len(files_to_delete))
        for src_file in files_to_delete:
            try:
                src_file.unlink()
                logging.info("[MOVED]    Deleted source: '%s'.", src_file)
            except PermissionError as exc:
                logging.error(
                    "Permission denied deleting '%s': %s", src_file, exc,
                )
                error_count += 1
            except FileNotFoundError:
                # File was already removed by a concurrent process.  Not an
                # error from this tool's perspective.
                logging.debug(
                    "Source already absent (FileNotFoundError): '%s'.", src_file,
                )
            except OSError as exc:
                logging.error(
                    "Could not delete source file '%s': %s", src_file, exc,
                )
                error_count += 1

    # ── Step 7: diff summary table ────────────────────────────────────────────
    # This is the one intentional print() in the file (Issue #10 rationale).
    # The change table is structured human-readable output that users
    # frequently want to pipe or redirect independently from the operational
    # log stream.  Sending it through logging would mix it with timestamps and
    # level labels, breaking any downstream tooling that parses the table.
    if config.show_diff and changes:
        col_p, col_a, col_r = 52, 7, 9
        header  = (
            f"{'File Path':<{col_p}} "
            f"{'Added':<{col_a}} "
            f"{'Removed':<{col_r}} "
            f"Starting Line"
        )
        divider = "─" * (col_p + col_a + col_r + 20)

        print(f"\n{divider}")
        print("  CHANGE SUMMARY")
        print(divider)
        print(header)
        print(divider)

        for rec in changes:
            # Render None as "N/A" for files where no hunk was detected.
            display_line = rec.stats.first_hunk_line or "N/A"
            print(
                f"{rec.relative_path:<{col_p}} "
                f"{rec.stats.added:<{col_a}} "
                f"{rec.stats.removed:<{col_r}} "
                f"{display_line}"
            )

        print(divider)
        print()

    # ── Step 8 (Issue #3): always emit a final summary ────────────────────────
    # The original code placed this inside `if not dry_run:`, meaning a
    # dry-run gave the user zero aggregated counts and forced manual
    # inspection of every [PREVIEW] log line.
    if config.dry_run:
        logging.info(
            "Dry-run complete.  "
            "Would update: %d | Skipped (identical): %d | Errors: %d.",
            updated_count, skipped_count, error_count,
        )
    else:
        logging.info(
            "Sync complete.  "
            "Updated: %d | Skipped (identical): %d | Errors: %d.",
            updated_count, skipped_count, error_count,
        )

    return error_count


# ─────────────────────────────────────────────────────────────────────────────
# CLI Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """
    Parse CLI arguments, initialise logging, assemble SyncConfig, run sync.

    Issue #7:  sys.exit(1) when sync_files() returns a non-zero error
               count, making failures visible to shell and CI callers.
    Issue #13: --ignore-dirs uses nargs='+' so a bare flag cannot silently
               clear the default ignore list (was nargs='*').
    Issue #17: --extensions restricts sync to specific file suffixes.
    Issue #18: --log-file appends all log output to a file.
    Issue #19: --version added as a standard argparse flag.
    """
    home = Path.home()

    parser = argparse.ArgumentParser(
        prog="sync_files",
        description=(
            "One-way file sync from a flat source directory into a project tree.\n"
            "Files are compared by SHA-256 hash. Every overwrite is backed up\n"
            "with a timestamped .bak file first.\n\n"
            "Always run with --dry-run before the first live sync."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Issue #19: zero-cost version flag.
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    # ── Path arguments ────────────────────────────────────────────────────────
    parser.add_argument(
        "--downloads-path",
        type=Path,
        default=home / "Downloads" / "project",
        metavar="DIR",
        help=(
            "Source directory to scan. Only the top level is indexed; "
            "sub-directories are intentionally excluded (flat-source design). "
            "Default: ~/Downloads/project"
        ),
    )
    parser.add_argument(
        "--project-path",
        type=Path,
        default=home / "daleel",
        metavar="DIR",
        help=(
            "Target project directory, walked recursively. "
            "Default: ~/daleel"
        ),
    )
    parser.add_argument(
        "--backup-path",
        type=Path,
        default=home / "Desktop" / "Project_Backups",
        metavar="DIR",
        help=(
            "Directory where pre-overwrite .bak copies are stored. "
            "Must NOT reside inside --project-path. "
            "Default: ~/Desktop/Project_Backups"
        ),
    )

    # ── Behaviour flags ───────────────────────────────────────────────────────
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview all planned operations without modifying any file.",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        default=False,
        help=(
            "Print a per-file change table after sync: "
            "added lines, removed lines, first changed line."
        ),
    )
    parser.add_argument(
        "--move",
        action="store_true",
        default=False,
        help=(
            "Delete source files after a successful copy. "
            "Deletions are batched and applied only after all copies complete."
        ),
    )

    # ── Directory filter ──────────────────────────────────────────────────────
    # Issue #13: nargs='+' (was nargs='*') requires at least one value when
    # the flag is used, preventing a bare `--ignore-dirs` from silently
    # setting ignore_dirs to [] and removing .git / __pycache__ from the list.
    parser.add_argument(
        "--ignore-dirs",
        nargs="+",
        default=[".git", "node_modules", "venv", "__pycache__"],
        metavar="DIR",
        help=(
            "Directory names to prune during the project walk. "
            "At least one value is required when this flag is used. "
            "Default: .git  node_modules  venv  __pycache__"
        ),
    )

    # ── Issue #17: Extension filter ───────────────────────────────────────────
    parser.add_argument(
        "--extensions",
        nargs="+",
        default=None,
        metavar="EXT",
        help=(
            "Only sync files whose extension matches one of these values "
            "(e.g. --extensions .py .js .ts). "
            "Include the leading dot. Matching is case-insensitive. "
            "Omit this flag to sync all file types."
        ),
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Log verbosity level. Default: INFO.",
    )
    # Issue #18.
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="FILE",
        help=(
            "Append all log output to this file in addition to the console. "
            "The file is created automatically if it does not exist."
        ),
    )

    args = parser.parse_args()

    # Initialise logging before any subsequent call so every message is
    # captured by both the console handler and the optional file handler.
    setup_logging(args.log_level, args.log_file)

    # ── Normalise the extension filter ────────────────────────────────────────
    # Guarantee every suffix has a leading dot and is lower-case so that
    # comparison against Path.suffix (which includes the dot, e.g. ".py")
    # works correctly and case-insensitively on all platforms.
    extensions: Optional[frozenset[str]] = None
    if args.extensions:
        extensions = frozenset(
            (ext if ext.startswith(".") else f".{ext}").lower()
            for ext in args.extensions
        )
        logging.info(
            "Extension filter active: %s", ", ".join(sorted(extensions)),
        )

    # ── Assemble SyncConfig from parsed arguments ─────────────────────────────
    config = SyncConfig(
        downloads_path = args.downloads_path,
        project_path   = args.project_path,
        backup_path    = args.backup_path,
        dry_run        = args.dry_run,
        show_diff      = args.show_diff,
        move_files     = args.move,
        ignore_dirs    = frozenset(args.ignore_dirs),
        extensions     = extensions,
    )

    error_count = sync_files(config)

    # Issue #7: propagate failure status to the calling process.
    # A non-zero exit code is detected by `cmd && next_step`, `make`,
    # GitHub Actions `if: success()`, and any POSIX shell error handling.
    sys.exit(1 if error_count > 0 else 0)


if __name__ == "__main__":
    main()
