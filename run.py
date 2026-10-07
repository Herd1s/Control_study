"""Development entry point. Keep your control algorithm in examples/my_controller.py."""
import sys
from control_lab.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["run", *sys.argv[1:]]))
