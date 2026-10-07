"""Read saved interactive experiments without executing the saved student code."""
from dataclasses import dataclass
import csv
import hashlib
import json
import math
from pathlib import Path
import zipfile

from control_lab.core.scenario import ForcePulse, ScenarioConfig, TargetChange, configuration_hash
from control_lab.core.types import EpisodeSpec, State


@dataclass(frozen=True)
class Recording:
    folder: Path
    report: dict
    spec: EpisodeSpec
    rows: tuple
    code: str | None


def load_recording(folder):
    folder = Path(folder).resolve()
    report_path, trajectory_path = folder / "report.json", folder / "trajectory.csv"
    if report_path.stat().st_size > 1_000_000 or trajectory_path.stat().st_size > 32_000_000:
        raise ValueError("实验文件过大，请分段导入。")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or report.get("kind") != "interactive_experiment":
        raise ValueError("仅支持当前版本保存的交互实验。正式评分报告请在评估面板查看。")
    config = dict(report["spec"])
    scene = dict(config.pop("scenario"))
    scene["initial_state"] = State(**scene["initial_state"])
    scene["disturbances"] = tuple(ForcePulse(**pulse) for pulse in scene.get("disturbances", ()))
    scene["target_schedule"] = tuple(TargetChange(**change) for change in scene.get("target_schedule", ()))
    spec = EpisodeSpec(scenario=ScenarioConfig(**scene), **config)
    if report.get("configuration_hash") and report["configuration_hash"] != configuration_hash(spec):
        raise ValueError("实验配置 hash 不匹配，配置可能已改变。")
    rows = []
    names = ("x", "v", "theta", "omega")

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("轨迹包含非有限数值。")
        return result

    with trajectory_path.open(encoding="utf-8", newline="") as stream:
        for index, row in enumerate(csv.DictReader(stream)):
            if index >= 50_000:
                raise ValueError("单个回放最多支持 50000 步。")
            timestamp = number(row["simulation_time_s"])
            if int(row["step_id"]) != index or not math.isclose(timestamp, (index + 1) * spec.dt_s, abs_tol=1e-8):
                raise ValueError("轨迹步号或物理时间不连续。")
            parsed = dict(step_id=index, simulation_time_s=timestamp, input_mode=row["input_mode"])
            for prefix in ("before", "true", "observed"):
                parsed[f"{prefix}_state"] = {name: number(row[f"{prefix}_{name}"]) for name in names}
            for name in ("requested_force_n", "actuator_force_n", "disturbance_force_n", "net_force_n", "target_velocity_mps", "reward"):
                parsed[name] = number(row[name])
            parsed["diagnostics"] = {key: number(row[key]) for key in
                ("p_n", "d_n", "i_n", "centering_n", "unsaturated_n", "applied_n", "integral") if row.get(key)}
            rows.append(parsed)
    if len(rows) != report.get("steps"):
        raise ValueError("报告步数与轨迹长度不同。")
    if sorted({row["input_mode"] for row in rows}) != report.get("input_modes"):
        raise ValueError("报告输入模式与轨迹不同。")
    code = None
    source_path = folder / "controller_snapshot.py"
    if report.get("controller_sha256"):
        if source_path.stat().st_size > 1_000_000:
            raise ValueError("代码快照过大。")
        source = source_path.read_bytes()
        if hashlib.sha256(source).hexdigest() != report["controller_sha256"]:
            raise ValueError("代码快照已改变，无法确认它与原实验一致。")
        code = source.decode("utf-8")
    return Recording(folder, report, spec, tuple(rows), code)


def export_recording(recording, destination):
    """Export the existing evidence, never run code or overwrite another archive."""
    destination = Path(destination)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("report.json", "trajectory.csv", "controller_snapshot.py"):
            source = recording.folder / name
            if source.is_file():
                archive.write(source, arcname=name)
    return destination
