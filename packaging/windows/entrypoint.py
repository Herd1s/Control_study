"""Frozen executable entry point. Unlike run.py this exposes all CLI commands."""
from control_lab.cli import main
from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
