"""Read-only environment discovery and bounded external TITA simulation commands.

No Isaac/torch module is imported here. The basic desktop remains independent of
the optional Python 3.11 robotics environment and its existing source checkouts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import uuid


TASK_ID = "DDT-Velocity-Flat-Tita-v0"
PLAY_TASK_ID = "DDT-Velocity-Flat-Tita-Play-v0"
PROFILE_MARKER = "CONTROLLAB_TITA_PROFILE "

# Executed only by the configured external interpreter. AST inspection does not
# execute DDT task registration; the registry command performs runtime inspection.
PROFILE_PROBE = r'''
import ast, importlib.metadata as metadata, json, pathlib, platform, subprocess, sys
profile = json.loads(sys.argv[1])
report = {"python": platform.python_version(), "executable": sys.executable,
          "packages": {}, "repositories": {}, "task_registry": {}, "errors": []}
for name in ("isaacsim", "isaaclab", "isaaclab_rl", "ddt_lab", "torch", "gymnasium", "onnx"):
    try:
        report["packages"][name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        report["packages"][name] = None
for name, path in (("IsaacLab", profile["isaaclab_root"]), ("DDT_Lab", profile["ddt_root"]),
                   ("ddt_ros2_control", str(pathlib.Path(profile["ddt_root"]) / "ddt_ros2_control"))):
    item = {"path": path}
    try:
        commit = subprocess.run(["git", "-C", path, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10)
        status = subprocess.run(["git", "-C", path, "status", "--porcelain", "--untracked-files=no"],
                                capture_output=True, text=True, timeout=10)
        item.update(commit=commit.stdout.strip() if commit.returncode == 0 else None,
                    modified_tracked_files=status.stdout.splitlines() if status.returncode == 0 else None)
        if commit.returncode:
            item["error"] = commit.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        item["error"] = str(exc)
    report["repositories"][name] = item
source = pathlib.Path(profile["ddt_root"]) / "source/ddt_lab/ddt_lab/tasks/manager_based/locomotion/robots/tita/__init__.py"
ids = []
try:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "register":
            for keyword in node.keywords:
                if keyword.arg == "id" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    ids.append(keyword.value.value)
except (OSError, SyntaxError) as exc:
    report["errors"].append(str(exc))
report["task_registry"] = {"method": "static_registration_declarations", "source": str(source), "ids": sorted(ids)}
urdf = pathlib.Path(profile["ddt_root"]) / "ddt_ros2_control/urdfs/tita_description/urdf/robot.urdf"
report["urdf"] = {"path": str(urdf), "exists": urdf.is_file()}
report["ready_for_smoke"] = (platform.python_version_tuple()[:2] == ("3", "11")
    and all(report["packages"][name] for name in ("isaacsim", "isaaclab", "ddt_lab", "torch"))
    and "DDT-Velocity-Flat-Tita-v0" in ids and urdf.is_file())
print("CONTROLLAB_TITA_PROFILE " + json.dumps(report, ensure_ascii=False))
'''


@dataclass(frozen=True)
class TitaProfile:
    python_executable: str
    ddt_root: str
    isaaclab_root: str
    checkpoint_path: str = ""
    omniverse_eula_accepted: bool = False
    eula_source: str = ""
    schema_version: int = 1

    def __post_init__(self):
        for name in ("python_executable", "ddt_root", "isaaclab_root", "checkpoint_path", "eula_source"):
            if not isinstance(getattr(self, name), str) or "\x00" in getattr(self, name):
                raise ValueError(f"{name} must be plain path/text")
        if not isinstance(self.omniverse_eula_accepted, bool):
            raise TypeError("EULA acceptance must be boolean")
        if self.schema_version != 1:
            raise ValueError("unsupported TITA profile schema")


@dataclass(frozen=True)
class ExternalCommand:
    program: str
    arguments: tuple[str, ...]
    working_directory: str
    environment: dict[str, str]
    mode: str
    run_tag: str

    @property
    def argv(self):
        return [self.program, *self.arguments]

    def powershell(self):
        def quote(value):
            return "'" + str(value).replace("'", "''") + "'"
        lines = [f"Set-Location -LiteralPath {quote(self.working_directory)}"]
        lines.extend(f"$env:{key} = {quote(value)}" for key, value in self.environment.items())
        lines.append("& " + " ".join(quote(value) for value in self.argv))
        return "\n".join(lines)


def discover_profile(workspace=Path("E:/Workspace/Isaac_lab")):
    root = Path(workspace)
    learning = root / "tita_learning"
    config_path = learning / "local_config.json"
    config = {}
    if config_path.is_file():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            pass
    python = learning / ".venv/Scripts/python.exe"
    if not python.is_file():
        python = Path(config.get("base_python", ""))
    accepted = config.get("omniverse_eula_accepted") is True
    checkpoints = []
    checkpoint_root = root / "ddt_lab/logs/np3o/tita_setup_64"
    if checkpoint_root.is_dir():
        checkpoints = sorted(checkpoint_root.glob("*/model_10.pt"))
    return TitaProfile(
        str(python) if python.is_file() else "",
        str(root / "ddt_lab") if (root / "ddt_lab").is_dir() else "",
        str(root / "IsaacLab") if (root / "IsaacLab").is_dir() else "",
        str(checkpoints[-1]) if checkpoints else "", accepted,
        str(config_path) if accepted else "")


def profile_path(data_dir):
    return Path(data_dir) / "tita" / "profile.json"


def save_profile(data_dir, profile):
    if not isinstance(profile, TitaProfile):
        raise TypeError("profile must be TitaProfile")
    path = profile_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".profile-{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)
    return path


def load_profile(data_dir):
    path = profile_path(data_dir)
    if not path.is_file():
        return discover_profile()
    return TitaProfile(**json.loads(path.read_text(encoding="utf-8-sig")))


def validate_paths(profile, *, checkpoint=False):
    if not Path(profile.python_executable).is_file():
        raise FileNotFoundError("请选择外部 TITA 环境的 python.exe。")
    for name in ("ddt_root", "isaaclab_root"):
        if not getattr(profile, name) or not Path(getattr(profile, name)).is_dir():
            raise FileNotFoundError(f"找不到 {name}，请检查路径。")
    if checkpoint and (not profile.checkpoint_path or not Path(profile.checkpoint_path).is_file()
                       or Path(profile.checkpoint_path).suffix.lower() != ".pt"):
        raise FileNotFoundError("请先选择自己的 TITA 仿真 .pt checkpoint。")


def build_command(profile, mode, data_dir, *, run_tag=None):
    if mode not in ("inspect", "registry", "smoke", "play", "export"):
        raise ValueError("only inspect, registry, smoke, play and export are supported")
    validate_paths(profile, checkpoint=mode in ("play", "export"))
    if mode != "inspect" and not profile.omniverse_eula_accepted:
        raise ValueError("外部仿真环境尚未记录 NVIDIA 许可接受信息，请先完成该环境的许可设置。")
    tag = run_tag or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", tag):
        raise ValueError("invalid run tag")
    env = {"PYTHONUTF8": "1", "OMP_NUM_THREADS": "4", "MKL_NUM_THREADS": "4", "CUDA_VISIBLE_DEVICES": "0"}
    if profile.omniverse_eula_accepted:
        env.update(OMNI_KIT_ACCEPT_EULA="YES", ACCEPT_EULA="Y")
    root = Path(profile.ddt_root)
    if mode == "inspect":
        arguments = ("-u", "-c", PROFILE_PROBE, json.dumps(asdict(profile), ensure_ascii=False))
    elif mode == "registry":
        script = root / "scripts/list_envs.py"
        if not script.is_file():
            raise FileNotFoundError(script)
        arguments = ("-u", str(script))
    elif mode == "smoke":
        script = root / "scripts/np3o/train.py"
        if not script.is_file():
            raise FileNotFoundError(script)
        arguments = ("-u", str(script), "--task", TASK_ID, "--num_envs", "8",
                     "--max_iterations", "2", "--seed", "42", "--experiment_name",
                     "controllab_smoke_" + tag, "--headless")
    else:
        script = root / "scripts/np3o/play.py"
        if not script.is_file():
            raise FileNotFoundError(script)
        export_dir = Path(data_dir).resolve() / "tita/exports" / tag
        if export_dir.exists():
            raise FileExistsError("export destination already exists; choose another run tag")
        arguments = ("-u", str(script), "--task", PLAY_TASK_ID, "--num_envs", "1",
                     "--checkpoint", str(Path(profile.checkpoint_path).resolve()),
                     "--export_dir", str(export_dir))
        if mode == "export":
            arguments += ("--headless", "--export_policy")
    return ExternalCommand(str(Path(profile.python_executable).resolve()), arguments,
                           str(root.resolve()), env, mode, tag)


def parse_inspection_output(output):
    for line in reversed(output.splitlines()):
        if line.startswith(PROFILE_MARKER):
            return json.loads(line[len(PROFILE_MARKER):])
    raise ValueError("外部 Python 未返回有效的环境检查结果。")


def inspect_profile(profile, timeout=45):
    command = build_command(profile, "inspect", Path.cwd())
    process_env = os.environ.copy()
    process_env.update(command.environment)
    result = subprocess.run(command.argv, cwd=command.working_directory, env=process_env,
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return parse_inspection_output(result.stdout)


def write_run_record(data_dir, command, *, exit_code, status, log_path, inspection=None):
    folder = Path(data_dir) / "tita" / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    record = dict(schema_version=1, recorded_at_utc=datetime.now(timezone.utc).isoformat(),
                  mode=command.mode, run_tag=command.run_tag, command=command.argv,
                  working_directory=command.working_directory, environment=command.environment,
                  exit_code=exit_code, status=status, log_path=str(log_path), inspection=inspection,
                  hardware_control=False,
                  scope="8 envs / 2 iterations / headless" if command.mode == "smoke" else command.mode)
    target = folder / f"{command.run_tag}_{command.mode}.json"
    with target.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return target
