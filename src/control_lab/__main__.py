"""Allow ``python -m control_lab`` and frozen launchers to share one entry point."""

from control_lab.cli import main
from multiprocessing import freeze_support

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
