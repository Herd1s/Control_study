"""Public GitHub Releases discovery with bounded HTTPS and redirect checks.

No access token is read, stored, or sent. SHA256 establishes integrity against
the configured release metadata; it is not a publisher signature.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class UpdateError(RuntimeError):
    pass


class UpdateCancelled(UpdateError):
    pass


def check_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise UpdateCancelled("操作已取消")


@dataclass(frozen=True)
class RepositoryConfig:
    owner: str
    repo: str

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", self.owner):
            raise ValueError("GitHub owner 只能包含字母、数字、短横线，长度 1–39")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", self.repo) or self.repo in (".", ".."):
            raise ValueError("GitHub repo 名称无效；请输入仓库名，不是网址")

    @property
    def full_name(self):
        return f"{self.owner}/{self.repo}"


DEFAULT_REPOSITORY = RepositoryConfig("Herd1s", "Control_study")


def load_config(data_dir):
    path = Path(data_dir) / "updates" / "repository.json"
    if not path.exists():
        return DEFAULT_REPOSITORY
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise UpdateError("更新设置格式不受支持；原文件已保留")
    return RepositoryConfig(data["owner"], data["repo"])


def save_config(data_dir, config: RepositoryConfig):
    directory = Path(data_dir) / "updates"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "repository.json"
    temporary = directory / "repository.json.tmp"
    temporary.write_text(json.dumps(dict(schema_version=1, **asdict(config)), indent=2), encoding="utf-8")
    temporary.replace(target)
    return target


def version_tuple(version):
    match = re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?", version)
    if not match:
        raise UpdateError(f"无法识别版本号：{version}")
    return tuple(int(part) for part in match.groups())


def validate_https_url(url, *, allow_api=False):
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise UpdateError("更新链接端口无效") from exc
    hosts = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
             "github-releases.githubusercontent.com"}
    if allow_api:
        hosts.add("api.github.com")
    if (parsed.scheme != "https" or parsed.hostname not in hosts or port not in (None, 443)
            or parsed.username is not None or parsed.password is not None or parsed.fragment):
        raise UpdateError("更新链接必须使用受支持的 GitHub HTTPS 来源")
    return parsed


def validate_asset_url(url, config, tag, filename):
    parsed = validate_https_url(url)
    expected = f"/{config.owner}/{config.repo}/releases/download/{tag}/{filename}"
    actual_parts, expected_parts = unquote(parsed.path).split("/"), expected.split("/")
    same_path = (len(actual_parts) == len(expected_parts)
                 and actual_parts[1:3] and [part.casefold() for part in actual_parts[1:3]] ==
                 [part.casefold() for part in expected_parts[1:3]]
                 and actual_parts[3:] == expected_parts[3:])
    if parsed.hostname != "github.com" or not same_path or parsed.query:
        raise UpdateError("安装文件不属于当前仓库及版本")
    return url


class _SafeRedirect(HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, request, fp, code, message, headers, new_url):
        validate_https_url(new_url, allow_api=urlsplit(request.full_url).hostname == "api.github.com")
        return super().redirect_request(request, fp, code, message, headers, new_url)


class GitHubTransport:
    def __init__(self, timeout_s=10.0):
        if not 0 < timeout_s <= 60:
            raise ValueError("Network timeout must be within (0, 60] seconds")
        self.timeout_s = float(timeout_s)
        self.opener = build_opener(_SafeRedirect())

    def open(self, url, *, api=False):
        validate_https_url(url, allow_api=api)
        headers = {"User-Agent": "ControlLab-Updater", "Accept": "application/vnd.github+json" if api else "application/octet-stream"}
        if api:
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        try:
            response = self.opener.open(Request(url, headers=headers), timeout=self.timeout_s)
            validate_https_url(response.geturl(), allow_api=api)
            return response
        except HTTPError as exc:
            if exc.code == 404:
                raise UpdateError("该仓库尚无可用的正式版本，或暂时无法访问") from exc
            if exc.code in (403, 429):
                raise UpdateError("GitHub 暂时限制请求，请稍后重试") from exc
            raise UpdateError(f"GitHub 请求失败（HTTP {exc.code}）") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise UpdateError(f"连接 GitHub 失败或超时：{exc}") from exc

    def read_bytes(self, url, *, max_bytes, cancel_event=None, api=False):
        check_cancelled(cancel_event)
        started = time.monotonic()
        chunks, count = [], 0
        with self.open(url, api=api) as response:
            while True:
                check_cancelled(cancel_event)
                if time.monotonic() - started > 30:
                    raise UpdateError("读取版本信息超过 30 秒，请稍后重试")
                chunk = response.read(min(65536, max_bytes + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                if count > max_bytes:
                    raise UpdateError("服务器响应超过允许大小")
                chunks.append(chunk)
        check_cancelled(cancel_event)
        return b"".join(chunks)


@dataclass(frozen=True)
class ReleaseInfo:
    repository: RepositoryConfig
    version: str
    tag: str
    release_url: str
    notes: str
    filename: str
    download_url: str
    size_bytes: int
    sha256: str
    checksum_source: str

    def __post_init__(self):
        version_tuple(self.version)
        if self.tag not in (self.version, "v" + self.version):
            raise UpdateError("版本标签与版本号不一致")
        if self.filename != f"ControlLab-Setup-{self.version}.exe":
            raise UpdateError("安装文件名不符合 ControlLab 发布约定")
        if not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise UpdateError("安装文件 SHA256 无效")
        if isinstance(self.size_bytes, bool) or not isinstance(self.size_bytes, int) or not 0 < self.size_bytes <= 2 * 1024**3:
            raise UpdateError("安装文件大小无效或超过 2 GiB")
        validate_asset_url(self.download_url, self.repository, self.tag, self.filename)
        page = validate_https_url(self.release_url)
        prefix = f"/{self.repository.full_name}/releases/tag/"
        if (page.hostname != "github.com" or page.query
                or not unquote(page.path).casefold().startswith(prefix.casefold())
                or unquote(page.path)[len(prefix):] != self.tag):
            raise UpdateError("版本说明链接不属于所配置的仓库")


def checksum_from_sums(text, filename):
    matches = []
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?([^\r\n]+)", line.strip())
        if match and match.group(2) == filename:
            matches.append(match.group(1).lower())
    if len(matches) != 1:
        raise UpdateError("同一版本的 SHA256SUMS 必须包含且仅包含一条安装文件校验值")
    return matches[0]


class ReleaseClient:
    def __init__(self, config, transport=None):
        self.config = config
        self.transport = transport or GitHubTransport()

    def check(self, current_version, cancel_event=None):
        check_cancelled(cancel_event)
        url = f"https://api.github.com/repos/{self.config.full_name}/releases/latest"
        raw = self.transport.read_bytes(url, max_bytes=2 * 1024**2, cancel_event=cancel_event, api=True)
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("draft") or data.get("prerelease"):
                return None
            tag = data["tag_name"]
            if not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", tag):
                raise UpdateError("仅支持明确的正式语义版本标签，例如 v0.2.0")
            version = tag.removeprefix("v")
            if version_tuple(version) <= version_tuple(current_version):
                return None
            filename = f"ControlLab-Setup-{version}.exe"
            matches = [item for item in data["assets"] if item["name"] == filename and item.get("state", "uploaded") == "uploaded"]
            if len(matches) != 1:
                raise UpdateError(f"版本中缺少唯一的 {filename} 安装文件")
            asset = matches[0]
            validate_asset_url(asset["browser_download_url"], self.config, tag, filename)
            digest = asset.get("digest") or ""
            if re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
                checksum, source = digest.split(":", 1)[1].lower(), "GitHub release asset digest"
            else:
                sums = [item for item in data["assets"] if item["name"] == "SHA256SUMS"]
                if len(sums) != 1:
                    raise UpdateError("版本缺少可信来源内的 SHA256 校验信息，暂不允许安装")
                sums_url = validate_asset_url(sums[0]["browser_download_url"], self.config, tag, "SHA256SUMS")
                content = self.transport.read_bytes(sums_url, max_bytes=256 * 1024, cancel_event=cancel_event)
                checksum, source = checksum_from_sums(content.decode("utf-8-sig"), filename), "SHA256SUMS in the same release"
            return ReleaseInfo(self.config, version, tag, data["html_url"], str(data.get("body") or ""),
                               filename, asset["browser_download_url"], asset["size"], checksum, source)
        except (KeyError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise UpdateError("GitHub 返回的版本信息格式无效") from exc
