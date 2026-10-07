"""Local anonymous progress, recoverable atomic writes, and exclusive homework saves."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from uuid import uuid4

from control_lab.paths import user_data_dir


class ProgressStore:
    schema_version = 1

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else user_data_dir()
        self.root = self.root.resolve()
        self.path = self.root / "progress" / "profile.json"
        self.backup_path = self.path.with_suffix(".json.bak")
        self.last_notice = ""

    def _empty(self):
        return {"schema_version": 1, "student_profile_id": "local", "lessons": {}, "last_lesson_id": "L01"}

    def _backup(self, source: Path, kind: str) -> Path:
        folder = self.root / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"progress-{kind}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}.json"
        shutil.copy2(source, target)
        return target

    def load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("进度不是对象")
        except (json.JSONDecodeError, UnicodeError, ValueError):
            damaged = self._backup(self.path, "damaged")
            if not self.backup_path.exists():
                self.last_notice = f"进度无法读取，原文件已保留：{damaged}；当前使用空白进度。"
                return self._empty()
            try:
                data = json.loads(self.backup_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("lessons"), dict):
                    raise ValueError("备份结构无效")
            except (json.JSONDecodeError, UnicodeError, ValueError):
                self.last_notice = f"进度与备份无法读取；原文件保留在 {damaged}。"
                return self._empty()
            self.last_notice = f"已从最近备份恢复进度；损坏文件保留在 {damaged}。"
            self._atomic(data, preserve_previous=False)
        version = data.get("schema_version", 0)
        if type(version) is not int or version not in (0, 1):
            raise ValueError("进度由更新的软件版本创建，当前版本不会覆盖它。")
        if version == 0:
            self._backup(self.path, "migration-v0")
            migrated = self._empty()
            if isinstance(data.get("lessons"), dict):
                migrated["lessons"] = data["lessons"]
            elif data.get("lesson_id"):
                migrated["lessons"][data["lesson_id"]] = data
            data = migrated
            self._atomic(data)
            self.last_notice = "旧进度已迁移；原始文件已备份。"
        if not isinstance(data.get("lessons"), dict):
            raise ValueError("进度课程列表结构无效，未覆盖文件。")
        return deepcopy(data)

    def _atomic(self, data: dict, preserve_previous=True):
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="profile-", suffix=".tmp", dir=self.path.parent)
        temp = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if preserve_previous and self.path.exists():
                # Only use a readable current document as the recovery copy.
                try:
                    current = json.loads(self.path.read_text(encoding="utf-8"))
                    valid = isinstance(current, dict) and isinstance(current.get("lessons"), dict)
                except (ValueError, UnicodeError):
                    valid = False
                if valid:
                    backup_temp = self.backup_path.with_suffix(".bak.tmp")
                    shutil.copy2(self.path, backup_temp)
                    os.replace(backup_temp, self.backup_path)
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def save(self, data: dict):
        if data.get("schema_version") != 1 or not isinstance(data.get("lessons"), dict):
            raise ValueError("无效进度格式")
        # Read first so an older app cannot overwrite a future-version profile.
        if self.path.exists():
            self.load()
        self._atomic(deepcopy(data))

    def get_lesson(self, lesson_id: str) -> dict:
        return self.load()["lessons"].get(lesson_id, {})

    def save_lesson(self, lesson_id: str, progress: dict):
        if not re.fullmatch(r"L\d{2}", lesson_id):
            raise ValueError("课程ID无效")
        data = self.load()
        data["lessons"][lesson_id] = deepcopy(progress)
        data["last_lesson_id"] = lesson_id
        self._atomic(data)

    def save_workspace(self, lesson_id: str, code: str, filename: str = "controller.py") -> Path:
        if not re.fullmatch(r"L\d{2}", lesson_id):
            raise ValueError("课程ID无效")
        if not isinstance(filename, str) or not re.fullmatch(r"[A-Za-z0-9_\-]+\.py", filename):
            raise ValueError("作业文件名仅使用字母数字下划线与.py扩展名")
        folder = (self.root / "workspace" / lesson_id).resolve()
        if not folder.is_relative_to(self.root):
            raise ValueError("作业目录越界")
        folder.mkdir(parents=True, exist_ok=True)
        for index in range(10000):
            target = folder / (filename if index == 0 else f"{Path(filename).stem}_{index:03d}.py")
            try:
                with target.open("x", encoding="utf-8", newline="\n") as handle:
                    handle.write(code)
                return target
            except FileExistsError:
                continue
        raise FileExistsError("同名作业版本过多，请使用新文件名")

    def preserve_template(self, lesson_id: str, version: int, code: str) -> Path:
        """Keep every encountered original template; an update never replaces it."""
        if not re.fullmatch(r"L\d{2}", lesson_id) or type(version) is not int or version < 1:
            raise ValueError("课程或模板版本无效")
        content = code.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        folder = self.root / "templates" / lesson_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"v{version}-{digest}.py"
        try:
            with path.open("xb") as handle:
                handle.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("已保存的原始模板被修改，请先保留并检查该文件。")
        return path
