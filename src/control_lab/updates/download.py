"""Download to an isolated cache and publish only a size/hash-verified file."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import uuid
import time

from .releases import GitHubTransport, UpdateCancelled, UpdateError, check_cancelled


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_release(release, cache_dir, *, cancel_event=None, progress=None, transport=None):
    cache = Path(cache_dir).expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    # A unique version/hash folder avoids overwriting an existing download.
    folder = cache / f"{release.version}-{release.sha256[:12]}-{uuid.uuid4().hex[:8]}"
    folder.mkdir()
    temporary = folder / (release.filename + ".part")
    final = folder / release.filename
    transport = transport or GitHubTransport()
    digest, count = hashlib.sha256(), 0
    started = time.monotonic()
    try:
        check_cancelled(cancel_event)
        with transport.open(release.download_url) as response, temporary.open("xb") as stream:
            while True:
                check_cancelled(cancel_event)
                if time.monotonic() - started > 600:
                    raise UpdateError("下载超过 10 分钟，已停止；可稍后重试")
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > release.size_bytes:
                    raise UpdateError("下载内容超过版本公布的文件大小")
                stream.write(chunk)
                digest.update(chunk)
                if progress is not None:
                    progress(count, release.size_bytes)
        check_cancelled(cancel_event)
        if count != release.size_bytes:
            raise UpdateError("下载不完整，文件大小与版本信息不符")
        if digest.hexdigest() != release.sha256:
            raise UpdateError("SHA256 校验失败；安装文件不会运行")
        temporary.replace(final)
        manifest = dict(schema_version=1, status="verified", filename=release.filename,
                        release=asdict(release), verification="size and SHA256; not a publisher signature")
        (folder / "verified.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return final
    except BaseException:
        # Only this operation's own uniquely named cache files are removed.
        temporary.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
