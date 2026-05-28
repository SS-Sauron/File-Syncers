# legacy/

This folder contains earlier versions of the File-Syncers script, preserved for historical reference.

## Purpose

These files represent the development history of the tool before the v1.0 refactor. They are kept here so that the evolution of the design — from the initial approach to the current architecture — remains visible and accessible.

## Status

**These scripts are not maintained and should not be used in production.**

They may lack:
- The SHA256 content-hashing check (only timestamp or filename comparison)
- Timestamped backups before overwriting
- The `--dry-run` safeguard
- Error handling around file I/O
- Cross-platform path resolution

## Current Version

The production script is [`sync_files.py`](../sync_files.py) at the repository root. See the main [`README.md`](../README.md) for full usage documentation.
