"""Optional, explicit updates from a user-configured public GitHub repository."""
from .releases import RepositoryConfig, ReleaseClient, ReleaseInfo, UpdateError, UpdateCancelled
from .download import download_release
from .installer import launch_installer

__all__ = ["RepositoryConfig", "ReleaseClient", "ReleaseInfo", "UpdateError", "UpdateCancelled",
           "download_release", "launch_installer"]
