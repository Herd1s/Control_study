"""Read formal evaluation evidence without importing any controller source."""
import csv
from dataclasses import dataclass
import json
import math
from pathlib import Path

from .protocol import EvaluationProtocol, canonical_hash
from .compare import compare_reports


@dataclass(frozen=True)
class EvaluationRecord:
    folder: Path
    report: dict
    protocol: EvaluationProtocol
    snapshot: dict | None

    def case_rows(self, case_id):
        episode = next((entry for entry in self.report["episodes"] if entry["case_id"] == case_id), None)
        if episode is None:
            raise ValueError("Case is not present in this report")
        relative = Path(episode["trajectory_file"])
        path = (self.folder / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(self.folder):
            raise ValueError("Trajectory must be inside the selected evaluation folder")
        if path.stat().st_size > 8_000_000:
            raise ValueError("Trajectory is too large")
        parsed = []
        numeric_fields = [f"{prefix}_{field}" for prefix in ("true", "observed")
                          for field in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")]
        numeric_fields += ["time_s", "requested_force_n", "actuator_force_n", "disturbance_force_n", "net_force_n", "reward"]
        with path.open(encoding="utf-8", newline="") as stream:
            for index, raw in enumerate(csv.DictReader(stream)):
                if index >= self.protocol.definition["max_steps"] or int(raw["step_id"]) != index:
                    raise ValueError("Invalid formal trajectory step sequence")
                row = {key: float(raw[key]) for key in numeric_fields}
                if not all(math.isfinite(value) for value in row.values()):
                    raise ValueError("Formal trajectory contains nonfinite values")
                if not math.isclose(row["time_s"], (index+1)*self.protocol.definition["physics"]["dt_s"], abs_tol=1e-10):
                    raise ValueError("Formal trajectory physical time differs from its protocol")
                row["step_id"] = index
                for key in ("terminated", "truncated"):
                    if raw[key] not in ("True", "False", "true", "false", "0", "1"):
                        raise ValueError("Invalid termination flag")
                    row[key] = raw[key].lower() in ("true", "1")
                diagnostics = {}
                for key, value in raw.items():
                    if key.startswith("controller_") and value:
                        if value.lower() in ("true", "false"):
                            diagnostics[key.removeprefix("controller_")] = value.lower() == "true"
                        else:
                            number = float(value)
                            if not math.isfinite(number):
                                raise ValueError("Nonfinite controller diagnostic")
                            diagnostics[key.removeprefix("controller_")] = number
                row["diagnostics"] = diagnostics
                parsed.append(row)
        if len(parsed) != episode["episode_steps"]:
            raise ValueError("Trajectory length differs from recorded case metrics")
        return tuple(parsed)


def load_evaluation(path, *, require_complete=False):
    path = Path(path).expanduser().resolve()
    folder = path.parent if path.name == "report.json" else path
    report_path = folder / "report.json"
    if report_path.stat().st_size > 16_000_000:
        raise ValueError("Evaluation report is too large")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or report.get("kind") == "interactive_experiment":
        raise ValueError("Select a formal benchmark report, not an interactive experiment")
    protocol_path = folder / "protocol.json"
    if protocol_path.stat().st_size > 1_000_000:
        raise ValueError("Protocol file is too large")
    protocol = EvaluationProtocol(protocol_path.read_text(encoding="utf-8"), report["split"])
    if report["protocol_hash"] != protocol.protocol_hash or report["cases_hash"] != protocol.cases_hash:
        raise ValueError("Report protocol/case hashes do not match the frozen configuration")
    for key, expected_value in (("protocol_id", protocol.protocol_id),
                                ("input_mode", protocol.definition["input_mode"]),
                                ("observation_contract", protocol.definition["observation"]),
                                ("reward_id", protocol.definition["reward_id"])):
        if report.get(key) != expected_value:
            raise ValueError(f"Report {key} disagrees with its protocol")
    expected = [case.as_dict() for case in protocol.cases]
    actual = [{key: episode[key] for key in ("case_id", "split", "seed", "initial_state")}
              for episode in report["episodes"]]
    if actual != expected[:len(actual)]:
        raise ValueError("Report case order or explicit initial conditions differ")
    complete = report.get("is_complete", True) and report.get("status", "completed") == "completed"
    if complete or require_complete:
        compare_reports([report, report])
    snapshot_path = folder / "controller_snapshot.json"
    snapshot = None
    if snapshot_path.is_file():
        if snapshot_path.stat().st_size > 8_000_000:
            raise ValueError("Controller snapshot is too large")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if canonical_hash(snapshot) != report.get("controller_sha256"):
            raise ValueError("Controller snapshot fingerprint mismatch")
        if snapshot["configuration"] != report.get("controller_configuration"):
            raise ValueError("Controller report configuration differs from its snapshot")
    return EvaluationRecord(folder, report, protocol, snapshot)
