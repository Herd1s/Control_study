"""Save actual interactive trajectories separately from scored benchmark reports."""

import csv
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4


def save_recording(root, lesson_id, spec, rows, *, code=None, status="paused", error=None):
    folder = Path(root) / "runs" / f"{datetime.now():%Y%m%d_%H%M%S}_{lesson_id}_{uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    source_hash = None
    if code is not None:
        source = code.encode("utf-8")
        (folder / "controller_snapshot.py").write_bytes(source)
        source_hash = hashlib.sha256(source).hexdigest()
    fields = ["episode_id", "step_id", "simulation_time_s", "input_mode", "requested_force_n",
              "actuator_force_n", "disturbance_force_n", "net_force_n", "target_velocity_mps",
              "reward", "terminated", "truncated", "end_reason"]
    fields += [f"{prefix}_{field}" for prefix in ("before", "true", "observed")
               for field in ("x", "v", "theta", "omega")]
    fields += ["p_n", "d_n", "i_n", "centering_n", "unsaturated_n", "applied_n", "integral", "frozen"]
    with (folder / "trajectory.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            flattened = {key: row.get(key) for key in fields if key in row}
            for prefix, key in (("before", "before_state"), ("true", "true_state"), ("observed", "observed_state")):
                flattened.update({f"{prefix}_{name}": value for name, value in row.get(key, {}).items()})
            flattened.update({key: value for key, value in row.get("diagnostics", {}).items() if key in fields})
            writer.writerow(flattened)
    report = {"schema_version": 1, "kind": "interactive_experiment", "lesson_id": lesson_id,
              "created_at": datetime.now(timezone.utc).isoformat(), "status": status, "error": error,
              "spec": asdict(spec), "steps": len(rows), "controller_sha256": source_hash,
              "input_modes": sorted({row["input_mode"] for row in rows}),
              "timing": "before_state precedes the action; true/observed state and simulation_time_s follow it",
              "scored_benchmark": False}
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return folder
