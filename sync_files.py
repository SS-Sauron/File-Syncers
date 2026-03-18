import os
import shutil
import hashlib
import argparse
import logging
import difflib
from datetime import datetime
from pathlib import Path  # Added for better path handling

def get_file_hash(path):
    """Generate a SHA256 hash to check if file content differs."""
    try:
        hasher = hashlib.sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, IOError) as e:
        logging.error(f"Error hashing file {path}: {e}")
        return None

def sync_files(downloads_path, project_path, backup_path, dry_run, ignore_dirs, show_diff, move_files):
    """Sync files from downloads to project with backups."""
    if not os.path.exists(downloads_path):
        logging.error(f"Downloads path does not exist: {downloads_path}")
        return
    if not os.path.exists(project_path):
        logging.error(f"Project path does not exist: {project_path}")
        return

    if not dry_run and not os.path.exists(backup_path):
        try:
            os.makedirs(backup_path)
            logging.info(f"Created backup directory: {backup_path}")
        except OSError as e:
            logging.error(f"Failed to create backup directory {backup_path}: {e}")
            return

    # Get map of filename -> full path for downloads
    try:
        new_files = {f: os.path.join(downloads_path, f)
                     for f in os.listdir(downloads_path)
                     if os.path.isfile(os.path.join(downloads_path, f))}
        logging.info(f"Found {len(new_files)} files in downloads directory.")
    except OSError as e:
        logging.error(f"Error reading downloads directory {downloads_path}: {e}")
        return

    mode = "DRY RUN MODE" if dry_run else "LIVE SYNC"
    logging.info(f"--- {mode} ---")

    changes = []
    updated_count = 0
    skipped_count = 0
    error_count = 0
    files_to_delete = set()

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]

        for filename in files:
            if filename in new_files:
                source = new_files[filename]
                destination = os.path.join(root, filename)

                if os.path.abspath(source) == os.path.abspath(destination):
                    skipped_count += 1
                    continue

                source_hash = get_file_hash(source)
                dest_hash = get_file_hash(destination)
                if source_hash is None or dest_hash is None:
                    error_count += 1
                    continue
                
                if not move_files and source_hash == dest_hash:
                    skipped_count += 1
                    continue

                added = 0
                removed = 0
                location = "N/A"
                
                if show_diff:
                    try:
                        with open(source, 'r', encoding='utf-8', errors='ignore') as f:
                            source_lines = f.readlines()
                        with open(destination, 'r', encoding='utf-8', errors='ignore') as f:
                            dest_lines = f.readlines()
                        diff_lines = list(difflib.unified_diff(dest_lines, source_lines, lineterm=''))
                        for line in diff_lines:
                            if line.startswith('@@'):
                                parts = line.split()
                                if len(parts) >= 3:
                                    old_part = parts[1]
                                    old_start = old_part.split(',')[0][1:] if ',' in old_part else old_part[1:]
                                    location = f"Line {old_start}"
                            elif line.startswith('+') and not line.startswith('+++'):
                                added += 1
                            elif line.startswith('-') and not line.startswith('---'):
                                removed += 1
                    except (OSError, IOError, UnicodeDecodeError):
                        location = "Error reading diff"

                changes.append({
                    'file': os.path.relpath(destination, project_path),
                    'added': added,
                    'removed': removed,
                    'location': location 
                })

                if dry_run:
                    logging.info(f"[PREVIEW] Would overwrite: {destination}")
                else:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_file = os.path.join(backup_path, f"{filename}.{timestamp}.bak")
                    try:
                        shutil.copy2(destination, backup_file)
                        shutil.copy2(source, destination)
                        logging.info(f"[SUCCESS] Updated & backed up: {filename}")
                        updated_count += 1
                        
                        if move_files:
                            files_to_delete.add(source)
                    except (OSError, IOError) as e:
                        logging.error(f"Error updating {filename}: {e}")
                        error_count += 1

    if move_files and not dry_run:
        for src_file in files_to_delete:
            try:
                os.remove(src_file)
                logging.info(f"[MOVED] Deleted from source: {src_file}")
            except OSError as e:
                logging.error(f"Error deleting source file {src_file}: {e}")

    if show_diff and changes:
        print("\n--- CHANGE SUMMARY ---")
        print(f"{'File Path':<50} {'Added':<6} {'Removed':<8} {'Starting Line'}")
        print("-" * 85)
        for change in changes:
            print(f"{change['file']:<50} {change['added']:<6} {change['removed']:<8} {change['location']}")
        print()

    if not dry_run:
        logging.info(f"Sync complete. Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}.")

def main():
    # Automatically detect the user's home directory (e.g., C:\Users\Isaac)
    home = Path.home()
    
    # New default path for the standard Desktop
    default_backup = str(home / "Desktop" / "Project_Backups")
    default_downloads = str(home / "Downloads" / "project")
    default_project = str(home / "daleel")

    parser = argparse.ArgumentParser(description="Sync files from downloads to project with backups.")
    parser.add_argument('--downloads-path', default=default_downloads,
                        help='Path to the downloads directory.')
    parser.add_argument('--project-path', default=default_project,
                        help='Path to the project directory.')
    parser.add_argument('--backup-path', default=default_backup,
                        help='Path to the backup directory.')
    parser.add_argument('--dry-run', action='store_true', default=False,
                        help='Run in dry-run mode.')
    parser.add_argument('--ignore-dirs', nargs='*', default=['.git', 'node_modules', 'venv', '__pycache__'],
                        help='Directories to ignore.')
    parser.add_argument('--show-diff', action='store_true', default=False,
                        help='Show a summary table of changes.')
    parser.add_argument('--move', action='store_true', default=False,
                        help='Move files instead of copying.')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO',
                        help='Set logging level.')

    args = parser.parse_args()

    logging.basicConfig(level=getattr(logging, args.log_level.upper()),
                        format='%(asctime)s - %(levelname)s - %(message)s')

    # Final check: Print where the backup is going so you can see it in the terminal
    if not args.dry_run:
        print(f"--- 📂 Backup target set to: {args.backup_path} ---")

    sync_files(args.downloads_path, args.project_path, args.backup_path,
               args.dry_run, set(args.ignore_dirs), args.show_diff, args.move)

if __name__ == "__main__":
    main()