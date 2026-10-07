"""Recompute a saved GUI experiment from its exact spec and source snapshot."""
from dataclasses import asdict
import json
import math
from pathlib import Path

from control_lab import __version__
from control_lab.core.session import EpisodeSession
from control_lab.core.types import Action
from control_lab.inputs.isolated import IsolatedControllerAdapter
from control_lab.inputs.velocity import VelocityController
from control_lab.storage.records import save_recording
from control_lab.storage.replay import load_recording


def reproduce_recording(folder, *, output_dir, cancel_requested=None,
                        execution_timeout=.5, startup_timeout=8.0):
    """Stop at the saved length, compare measured values, never replay fake state.

    Force/velocity student experiments are supported. Mouse assistance needs the
    original drag input trace, so it is available as read-only historical playback
    and is explicitly rejected here. State-dependent code is run anew once.
    """
    original = load_recording(folder)
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise FileExistsError(f"Reproduction never overwrites an existing directory: {output}")
    if not original.code or not original.rows:
        raise ValueError("Reproduction needs a saved controller source and at least one physical step")
    modes = original.report["input_modes"]
    if len(modes) != 1 or modes[0] not in {"force_n", "velocity_mps"}:
        raise ValueError("Only one force_n or velocity_mps code mode can be recomputed; mouse/mixed input remains historical playback")
    if modes[0] == "velocity_mps":
        assistance = original.report.get("input_assistance")
        expected = {"kind": "velocity-proportional-v1", "gain_n_per_m_s": VelocityController().gain,
                    "force_limit_n": original.spec.force_limit_n}
        if assistance is not None and assistance != expected:
            raise ValueError("Recorded velocity assistance differs from the installed implementation")
    rows, error, status = [], None, "finished"
    controller = IsolatedControllerAdapter(original.code, original.folder / "controller_snapshot.py",
                                            execution_timeout=execution_timeout, startup_timeout=startup_timeout)
    session = EpisodeSession(original.spec)
    try:
        controller.reset()
        for saved_row in original.rows:
            if cancel_requested is not None and cancel_requested():
                raise KeyboardInterrupt
            if session.finished:
                break
            before = session.true_state.as_dict()
            value = controller.act(session.observed_state, session.dt, context={
                "time_s": session.step_index * session.dt,
                "target_v": session.target_velocity_mps})
            result = session.step(Action(value, modes[0]))
            row = asdict(result)
            row["before_state"] = before
            row["diagnostics"] = controller.diagnostics
            rows.append(row)
    except KeyboardInterrupt:
        status = "cancelled"
    except (Exception, SystemExit) as exc:
        status = "error"
        error = {"type": type(exc).__name__, "message": str(exc), "phase": getattr(exc, "phase", None)}
    finally:
        session.close()
        controller.close()
    differences = []
    max_error = 0.0
    for index, (saved, actual) in enumerate(zip(original.rows, rows)):
        values = [(f"{key}.{name}", saved[key][name], actual[key][name])
                  for key in ("before_state", "true_state", "observed_state")
                  for name in ("x", "v", "theta", "omega")]
        values += [(key, saved[key], actual[key]) for key in
                   ("requested_force_n", "actuator_force_n", "disturbance_force_n", "net_force_n",
                    "target_velocity_mps", "reward", "simulation_time_s")]
        for field, expected, actual_value in values:
            max_error = max(max_error, abs(expected - actual_value))
            if not math.isclose(expected, actual_value, rel_tol=1e-10, abs_tol=1e-12) and len(differences) < 20:
                differences.append({"step_id": index, "field": field, "saved": expected, "recomputed": actual_value})
    matches = len(rows) == len(original.rows) and not differences and error is None and status != "cancelled"
    provenance = {"source_recording": str(original.folder), "source_configuration_hash": original.report.get("configuration_hash"),
                  "original_control_lab_version": original.report.get("control_lab_version"),
                  "recomputed_control_lab_version": __version__, "saved_steps": len(original.rows),
                  "recomputed_steps": len(rows), "matches_saved_trajectory": matches,
                  "comparison_tolerance": {"absolute": 1e-12, "relative": 1e-10},
                  "maximum_numeric_difference": max_error, "first_differences": differences,
                  "scope": "Recomputed once from source, not a benchmark score; runtime-only globals are not serialized"}
    save_recording(output.parent, original.report["lesson_id"], original.spec, rows, code=original.code,
                   destination=output, status=status, error=error, provenance=provenance)
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    report["recording_dir"] = str(output)
    return report
