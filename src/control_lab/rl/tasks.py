"""Persistent detached training registry; no Qt, torch, or bare-PID termination."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
from uuid import uuid4

from .artifacts import atomic_json

ACTIVE = frozenset({"starting", "running", "stopping"})


def now():
    return datetime.now(timezone.utc).isoformat()


def process_identity(pid):
    """Return a creation-time identity, so a recycled PID never appears to be our job."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)]*4)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            creation, exit_time, kernel_time, user_time = (wintypes.FILETIME() for _ in range(4))
            if not kernel.GetProcessTimes(handle, *[ctypes.byref(item) for item in (creation, exit_time, kernel_time, user_time)]):
                return None
            return {"pid": pid, "created": (creation.dwHighDateTime << 32) | creation.dwLowDateTime}
        finally:
            kernel.CloseHandle(handle)
    try:
        fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "created": fields[19]}
    except (OSError, IndexError):
        return None


class TaskStore:
    def __init__(self, data_dir):
        self.root = Path(data_dir).resolve()/"training/tasks"

    def directory(self, task_id):
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{32}", task_id):
            raise ValueError("Invalid training task id")
        return self.root/task_id

    def launch(self, python, config):
        interpreter = Path(python).resolve()
        if not interpreter.is_file():
            raise ValueError("Independent RL Python does not exist")
        from .train import TrainConfig
        checked = TrainConfig(**config)
        if checked.output_dir.exists():
            raise FileExistsError("Training output already exists")
        task_id = uuid4().hex
        folder = self.directory(task_id)
        folder.mkdir(parents=True, exist_ok=False)
        payload = {key: str(value) if isinstance(value, Path) else value for key, value in vars(checked).items()}
        payload["stop_file"] = str(folder/"STOP")
        request = {"schema_version": 1, "task_id": task_id, "created_at": now(),
                   "python": str(interpreter), "config": payload, "kind": "train"}
        atomic_json(folder/"request.json", request)
        atomic_json(folder/"state.json", {"schema_version": 1, "task_id": task_id,
            "status": "starting", "created_at": request["created_at"], "updated_at": now()})
        environment = dict(os.environ, PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
        try:
            with (folder/"runner.log").open("ab", buffering=0) as log:
                process = subprocess.Popen([str(interpreter), "-m", "control_lab.rl.task_runner", "--request", str(folder/"request.json")],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=folder, env=environment,
                    close_fds=True, **options)
            identity = process_identity(process.pid)
            atomic_json(folder/"launch.json", {"process": identity, "pid": process.pid, "launched_at": now()})
        except OSError as exc:
            atomic_json(folder/"state.json", {"schema_version": 1, "task_id": task_id, "status": "failed",
                "updated_at": now(), "error": str(exc)})
            raise
        return task_id

    def read(self, task_id):
        folder = self.directory(task_id)
        request = json.loads((folder/"request.json").read_text(encoding="utf-8"))
        state = json.loads((folder/"state.json").read_text(encoding="utf-8"))
        if request.get("task_id") != task_id or state.get("task_id") != task_id:
            raise ValueError("Task identity does not match its directory")
        try:
            launch = json.loads((folder/"launch.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            launch = {}
        identity = state.get("process") or launch.get("process")
        alive = bool(identity and process_identity(identity.get("pid")) == identity)
        derived = dict(state)
        if state.get("status") in ACTIVE:
            if not alive and (identity or time.time()-(folder/"request.json").stat().st_mtime > 5):
                derived.update(status="interrupted", error="任务进程已退出且未写完成结果；已有日志和检查点保留。")
            elif (folder/"STOP").exists():
                derived["status"] = "stopping"
        return {**derived, "request": request, "directory": str(folder), "alive": alive,
                "stop_requested": (folder/"STOP").exists()}

    def list(self):
        if not self.root.exists():
            return []
        results = []
        for folder in self.root.iterdir():
            if folder.is_dir() and re.fullmatch(r"[a-f0-9]{32}", folder.name):
                try:
                    results.append(self.read(folder.name))
                except (OSError, ValueError, KeyError):
                    results.append({"task_id": folder.name, "status": "invalid", "alive": False,
                        "directory": str(folder), "error": "任务记录无法读取；未删除或重新启动任务。"})
        return sorted(results, key=lambda item: item.get("request", {}).get("created_at", ""), reverse=True)

    def request_stop(self, task_id):
        state = self.read(task_id)
        if state["status"] not in ACTIVE:
            return False
        # Only a task-specific file; no signal is sent to a PID from a stale record.
        (self.directory(task_id)/"STOP").write_text("Stop requested at "+now(), encoding="utf-8")
        return True

    def record_close_choice(self, task_id, choice):
        if choice not in {"keep", "stop", "cancel"}:
            raise ValueError("Unknown close choice")
        atomic_json(self.directory(task_id)/"gui-choice.json", {"choice": choice, "at": now()})
