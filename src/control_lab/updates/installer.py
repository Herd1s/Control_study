"""Installer handoff after the GUI explicitly saves and stops active work."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from .download import file_sha256
from .releases import ReleaseInfo, RepositoryConfig, UpdateError


def verify_cached_installer(path, cache_dir):
    path, cache = Path(path).resolve(), Path(cache_dir).resolve()
    if not path.is_relative_to(cache) or path.suffix.lower() != ".exe" or not path.is_file():
        raise UpdateError("安装文件必须来自本软件的校验缓存目录")
    try:
        manifest = json.loads((path.parent / "verified.json").read_text(encoding="utf-8"))
        if manifest.get("schema_version") != 1 or manifest.get("status") != "verified":
            raise UpdateError("找不到有效的下载校验记录")
        values = dict(manifest["release"])
        values["repository"] = RepositoryConfig(**values["repository"])
        release = ReleaseInfo(**values)
        if path.name != release.filename or manifest["filename"] != path.name:
            raise UpdateError("安装文件名与校验记录不一致")
        if path.stat().st_size != release.size_bytes or file_sha256(path) != release.sha256:
            raise UpdateError("安装前重新校验失败，文件可能已被改动")
        return release
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError(f"无法验证安装文件：{exc}") from exc


def launch_installer(path, cache_dir, *, popen=None):
    """Show the per-user install wizard; never silently install or force restart.

    The caller saves edits, stops workers, invokes this function, then exits.
    Inno Setup handles files still held while the current process is exiting.
    """
    release = verify_cached_installer(path, cache_dir)
    if sys.platform != "win32" and popen is None:
        raise UpdateError("Windows 安装器只能在 Windows 中运行")
    path = Path(path).resolve()
    log = path.parent / "installer.log"
    launcher = popen or subprocess.Popen
    try:
        process = launcher([str(path), "/NORESTART", f"/LOG={log}"], cwd=str(path.parent), close_fds=True)
    except OSError as exc:
        raise UpdateError(f"安装器未能启动，当前软件可继续使用：{exc}") from exc
    (path.parent / "handoff.json").write_text(json.dumps(dict(
        schema_version=1, status="installer_started", version=release.version,
        process_id=process.pid, started_at_utc=datetime.now(timezone.utc).isoformat(),
        completed=False, log_file=str(log),
    ), ensure_ascii=False, indent=2), encoding="utf-8")
    return process


def confirm_installation(cache_dir, app_dir, current_version):
    """Confirm previous handoffs only after Inno's successful-install marker.

    Call on a later installed-app startup (or after its finish page closes).
    Merely starting the installer, or running a source checkout of the same
    version, does not create a completion record.
    """
    marker = Path(app_dir) / "installation.json"
    if not marker.is_file():
        return []
    try:
        completed = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if completed != dict(schema_version=1, status="installed_successfully", version=current_version):
        return []
    confirmed = []
    for path in Path(cache_dir).glob("*/handoff.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if record.get("status") != "installer_started" or record.get("version") != current_version:
                continue
            started = datetime.fromisoformat(record["started_at_utc"]).timestamp()
            if marker.stat().st_mtime < started:
                continue  # A marker from an earlier installation is not this attempt's receipt.
            record.update(status="completed", completed=True,
                          confirmed_at_utc=datetime.now(timezone.utc).isoformat(),
                          installed_directory=str(Path(app_dir).resolve()))
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            confirmed.append(path)
        except (OSError, ValueError, KeyError):
            continue
    return confirmed
