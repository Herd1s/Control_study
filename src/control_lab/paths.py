"""Keep experiment data and editable code outside the installed application."""

from pathlib import Path
import sys


def user_data_dir() -> Path:
    documents = Path.home() / "Documents"
    if sys.platform == "win32":
        # Resolve the user's Documents folder, including OneDrive/redirection.
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0:
            documents = Path(buffer.value)
    return documents / "ControlLab"


def default_controller_file() -> Path:
    if not getattr(sys, "frozen", False):
        project = Path(__file__).resolve().parents[2]
        example = project / "examples" / "my_controller.py"
        if (project / "pyproject.toml").is_file() and example.is_file():
            return example
    return user_data_dir() / "workspace" / "my_controller.py"
