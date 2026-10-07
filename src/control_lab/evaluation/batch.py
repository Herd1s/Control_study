"""Synchronous CPU evaluator for trusted controllers and frozen scenarios.

Every case, including a controller error, receives a report. The desktop runs
untrusted/possibly stalled edits in its separate timeout worker; this API does
not promise to interrupt arbitrary Python code inside act().
"""
import csv
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np
import sys

from control_lab import __version__
from control_lab.controllers._common import finite_number, state_values
from control_lab.inputs.adapters import FunctionControllerAdapter, LegacyControllerAdapter
from .metrics import METRICS_VERSION, aggregate_metrics, episode_metrics
from .protocol import canonical_hash, load_protocol


def _serializable(value, _seen=None, _depth=0):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _serializable(value.item(), _seen, _depth)
    if isinstance(value, np.ndarray):
        if value.size > 10000:
            raise ValueError("Large model arrays require an explicit evaluation_identity() with an artifact hash")
        return dict(dtype=str(value.dtype), shape=list(value.shape), values=value.tolist())
    if _seen is None:
        _seen = set()
    if id(value) in _seen or _depth >= 8:
        return f"<{type(value).__module__}.{type(value).__qualname__}: reference>"
    seen = _seen | {id(value)}
    if is_dataclass(value):
        return _serializable(vars(value), seen, _depth + 1)
    if isinstance(value, dict):
        return {str(k): _serializable(v, seen, _depth + 1) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serializable(item, seen, _depth + 1) for item in value]
    if hasattr(value, "__dict__"):
        return {name: _serializable(item, seen, _depth + 1) for name, item in vars(value).items()
                if not name.startswith("__") and not callable(item)
                and name not in ("diagnostics", "integral", "value", "previous", "module",
                                 "source", "source_filename", "source_sha256", "reset_hook")}
    return f"{type(value).__module__}.{type(value).__qualname__}"


def controller_identity(controller):
    target = getattr(controller, "controller", controller)
    source = getattr(controller, "source", None)
    sources = {}
    if source is not None:
        sources["student_controller.py"] = source.decode("utf-8-sig")
    else:
        module = inspect.getmodule(type(target))
        module_file = getattr(module, "__file__", None)
        if module_file and Path(module_file).is_file():
            sources[Path(module_file).name] = Path(module_file).read_text(encoding="utf-8")
        elif module is not None:
            try:
                sources["controller.py"] = inspect.getsource(type(target))
            except (OSError, TypeError):
                pass
    # Preserve reusable feedback helpers as well as the selected class source.
    if type(target).__module__.startswith("control_lab.controllers"):
        directory = Path(__file__).resolve().parents[1] / "controllers"
        for filename in directory.glob("*.py"):
            sources[filename.name] = filename.read_text(encoding="utf-8")
    identity_hook = getattr(target, "evaluation_identity", None)
    configuration = identity_hook() if callable(identity_hook) else _serializable(target)
    if not isinstance(configuration, dict):
        raise TypeError("evaluation_identity() must return a JSON object")
    canonical_hash(configuration)  # Validate JSON types and finite values now.
    bundle = dict(controller_class=f"{type(target).__module__}.{type(target).__qualname__}",
                  configuration=configuration, sources=sources,
                  control_lab_version=__version__)
    module = getattr(controller, "module", None)
    if module is not None:
        # Include explicit edits to simple module-level parameters made by a factory.
        globals_snapshot = {}
        for name, value in vars(module).items():
            if name.startswith("_") or not isinstance(value, (str, bool, int, float, list, tuple, dict, type(None))):
                continue
            try:
                json.dumps(value, allow_nan=False)
            except (TypeError, ValueError):
                continue
            globals_snapshot[name] = value
        bundle["configuration"]["module_globals"] = globals_snapshot
    if getattr(sys, "frozen", False):
        # Source .py files may be embedded in PYZ. Fingerprint the actual executable
        # rather than pretending an unavailable source snapshot was collected.
        bundle["frozen_executable_sha256"] = hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest()
    return canonical_hash(bundle), bundle


def _state_row(prefix, state):
    return dict(zip((prefix + "x_m", prefix + "v_m_s", prefix + "theta_rad", prefix + "omega_rad_s"),
                    state_values(state)))


def evaluate(controller_factory, protocol=None, *, output_dir=None, controller_name=None,
             allow_held_out=False, expected_controller_sha256=None, progress_callback=None):
    from control_lab.core.session import EpisodeSession

    protocol = protocol or load_protocol()
    if protocol.split == "held_out" and (not allow_held_out or not expected_controller_sha256):
        raise ValueError("Held-out evaluation requires allow_held_out=True and a frozen expected_controller_sha256 from validation")
    output = Path(output_dir).expanduser().resolve() if output_dir is not None else None
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        if any(output.iterdir()):
            raise FileExistsError(f"Evaluation output must be an empty directory: {output}")
        (output / "protocol.json").write_text(protocol.definition_json, encoding="utf-8")
    controller, construction_error = None, None
    identity, bundle = None, None
    try:
        controller = controller_factory()
        if not callable(getattr(controller, "reset", None)) or not callable(getattr(controller, "act", None)):
            raise TypeError("controller_factory must return an object with reset() and act()")
        identity, bundle = controller_identity(controller)
        if expected_controller_sha256 is not None and identity != expected_controller_sha256:
            raise ValueError("Controller source/configuration differs from the frozen validation fingerprint")
    except (Exception, SystemExit) as exc:
        if expected_controller_sha256 is not None:
            raise
        construction_error = dict(type=type(exc).__name__, message=str(exc))
    if output is not None and bundle is not None:
        (output / "controller_snapshot.json").write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    episodes = []
    for case_index, case in enumerate(protocol.cases):
        rows, session, error, end_reason = [], None, construction_error, "controller_error" if construction_error else None
        try:
            if error is None:
                session = EpisodeSession(protocol.spec_for(case))
                controller.reset()
                while not session.finished:
                    observed = session.observed_state
                    # All library controllers and adapters accept the internal State.
                    # Bare legacy classes are supplied a copy of the original sequence.
                    argument = np.asarray(state_values(observed), dtype=np.float32).copy()
                    if isinstance(controller, (FunctionControllerAdapter, LegacyControllerAdapter)):
                        force = controller.act(argument, session.dt, context={
                            "time_s": session.step_index * session.dt,
                            "target_v": session.spec.scenario.target_at(session.step_index),
                        })
                    else:
                        force = controller.act(argument, session.dt)
                    requested = finite_number(force, "controller force")
                    result = session.step(requested)
                    row = dict(step_id=result.step_id, time_s=result.simulation_time_s,
                               **_state_row("true_", result.true_state),
                               **_state_row("observed_", observed),
                               requested_force_n=result.requested_force_n,
                               actuator_force_n=result.actuator_force_n,
                               disturbance_force_n=result.disturbance_force_n,
                               net_force_n=result.net_force_n, reward=result.reward,
                               terminated=result.terminated, truncated=result.truncated)
                    diagnostics = getattr(controller, "diagnostics", None)
                    if diagnostics:
                        for key, value in diagnostics.items():
                            row["controller_" + key] = value
                    rows.append(row)
                    end_reason = result.end_reason
        except (Exception, SystemExit) as exc:
            error = dict(type=type(exc).__name__, message=str(exc))
            end_reason = "controller_error"
        finally:
            if session is not None:
                session.close()
        metrics = episode_metrics(rows, initial_state=case.initial_state,
                                  max_steps=protocol.definition["max_steps"],
                                  dt_s=protocol.definition["physics"]["dt_s"],
                                  force_limit_n=protocol.definition["force_limit_n"],
                                  end_reason=end_reason, error=error)
        episode = dict(case.as_dict(), **metrics)
        if output is not None:
            case_dir = output / case.case_id
            case_dir.mkdir()
            fields = list(dict.fromkeys(key for row in rows for key in row))
            with (case_dir / "trajectory.csv").open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=fields or ["step_id", "time_s"])
                writer.writeheader()
                writer.writerows(rows)
            episode["trajectory_file"] = str(Path(case.case_id) / "trajectory.csv")
        episodes.append(episode)
        if progress_callback is not None:
            progress_callback(case_index + 1, len(protocol.cases), episode)
    report = dict(schema_version=1, control_lab_version=__version__,
                  created_at_utc=datetime.now(timezone.utc).isoformat(),
                  protocol_id=protocol.protocol_id, protocol_hash=protocol.protocol_hash,
                  cases_hash=protocol.cases_hash, split=protocol.split,
                  input_mode=protocol.definition["input_mode"],
                  observation_contract=protocol.definition["observation"],
                  reward_id=protocol.definition["reward_id"], metrics_version=METRICS_VERSION,
                  controller=controller_name or getattr(controller_factory, "__name__", "controller"),
                  controller_sha256=identity, controller_configuration=bundle["configuration"] if bundle else None,
                  episodes=episodes, aggregate=aggregate_metrics(episodes),
                  trajectory_timing="true state is post-action; observation is the pre-action controller input",
                  held_out_authorized=bool(allow_held_out and protocol.split == "held_out"))
    if output is not None:
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report
