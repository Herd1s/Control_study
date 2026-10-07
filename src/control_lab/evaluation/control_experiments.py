"""Explicit classroom P/PI comparisons, separate from scored balance-v1."""
import csv
from dataclasses import asdict, replace
import json
import math
from pathlib import Path

from control_lab.controllers.p import PController
from control_lab.controllers.pid import VelocityPIController
from control_lab.controllers._common import finite_number
from control_lab.core.scenario import configuration_hash, get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.core.types import State
from control_lab.storage.records import save_recording
from .metrics import episode_metrics


def _intervals(rows, predicate, dt):
    result, start = [], None
    for index, row in enumerate(rows):
        active = predicate(row)
        if active and start is None:
            start = index*dt
        if not active and start is not None:
            result.append([start, index*dt])
            start = None
    if start is not None:
        result.append([start, len(rows)*dt])
    return result


def velocity_recovery_metrics(rows, *, switch_time_s=4., target_mps=.3, tolerance_mps=.03, dwell_s=1., dt_s=.02):
    after = [row for row in rows if row["simulation_time_s"] >= switch_time_s + dt_s/2]
    # Include both endpoints: 51 measured samples span 1 s at dt=.02 s.
    required = math.ceil(dwell_s/dt_s)+1
    recovery = None
    for index in range(max(0, len(after)-required+1)):
        if all(abs(row["true_state"]["v"]-target_mps) <= tolerance_mps for row in after[index:index+required]):
            recovery = after[index]["simulation_time_s"] - switch_time_s
            break
    return {"velocity_recovery_s": recovery,
            "post_switch_max_abs_velocity_error_m_s": max((abs(row["true_state"]["v"]-target_mps) for row in after), default=None),
            "recovery_definition": {"switch_time_s": switch_time_s, "target_mps": target_mps,
                                    "tolerance_mps": tolerance_mps, "dwell_s": dwell_s,
                                    "unrecovered": None, "uses": "true post-step velocity"}}


def teaching_scan(kind="p", *, gains=(0., 20., 40., 60., 100.), condition="primary",
                  output_dir, progress_callback=None, cancel_requested=None):
    if kind not in {"p", "pi"} or condition not in {"primary", "check"}:
        raise ValueError("Use p/pi and primary/check classroom conditions")
    output = Path(output_dir).expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("Scan output must be empty")
    if kind == "p":
        values = tuple(finite_number(gain, "kp") for gain in gains)
        if not 2 <= len(values) <= 12 or len(set(values)) != len(values) or any(abs(gain) > 300 for gain in values):
            raise ValueError("Provide 2–12 distinct finite Kp values between -300 and 300")
        spec = get_episode_spec("tilt_right")
        initial = State(theta=.05) if condition == "primary" else State(theta=-.03, omega=.05)
        spec = replace(spec, protocol_id=f"teaching-p-scan-{condition}-v1", allow_runtime_disturbances=False,
                       scenario=replace(spec.scenario, scenario_id=f"p-scan-{condition}", initial_state=initial))
        candidates = [(f"Kp={value:g}", {"kp": value}) for value in values]
    else:
        if condition != "primary":
            raise ValueError("PI comparison uses its explicit target-switch velocity scene")
        spec = replace(get_episode_spec("cart_velocity_windup"), protocol_id="teaching-pi-windup-v1", allow_runtime_disturbances=False)
        candidates = [("无保护", {"integral_limit": None, "anti_windup": False}),
                      ("积分限幅", {"integral_limit": 1., "anti_windup": False}),
                      ("条件积分", {"integral_limit": 1., "anti_windup": True})]
    output.mkdir(parents=True, exist_ok=True)
    results = []
    report = {"schema_version": 1, "kind": "teaching_control_scan", "scan_kind": kind,
              "condition": condition, "spec": asdict(spec), "configuration_hash": configuration_hash(spec),
              "scored_benchmark": False, "status": "running", "candidates": results}
    def persist():
        (output / "scan.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    persist()
    for index, (name, parameters) in enumerate(candidates):
        if cancel_requested and cancel_requested():
            report["status"] = "cancelled"
            break
        if kind == "p":
            controller = PController(**parameters, force_limit_n=spec.force_limit_n)
            source = f"def control(state, dt):\n    return {parameters['kp']!r} * state['theta']\n"
        else:
            controller = VelocityPIController(kp=2., ki=1., force_limit_n=spec.force_limit_n, **parameters)
            source = ("from control_lab.controllers.pid import VelocityPIController\n"
                      f"_controller = VelocityPIController(kp=2., ki=1., force_limit_n={spec.force_limit_n!r}, "
                      f"integral_limit={parameters['integral_limit']!r}, anti_windup={parameters['anti_windup']!r})\n"
                      "def reset():\n    _controller.reset()\n"
                      "def control(state, dt):\n    _controller.target_velocity_mps = state['target_v']\n"
                      "    return _controller.act([state[k] for k in ('x','v','theta','omega')], dt)\n"
                      "def diagnostics():\n    parts = dict(_controller.diagnostics)\n"
                      "    parts['frozen'] = parts.pop('integral_frozen', False)\n    return parts\n")
        rows, formal = [], []
        with EpisodeSession(spec) as session:
            controller.reset()
            while not session.finished:
                if cancel_requested and cancel_requested():
                    report["status"] = "cancelled"
                    break
                before = session.true_state.as_dict()
                if kind == "pi":
                    controller.target_velocity_mps = session.target_velocity_mps
                force = controller.act(session.observed_state, session.dt)
                result = session.step(force)
                row = asdict(result)
                row["before_state"] = before
                row["diagnostics"] = dict(controller.diagnostics)
                row["diagnostics"]["frozen"] = row["diagnostics"].get("integral_frozen", False)
                rows.append(row)
                formal.append({"true_theta_rad": result.true_state.theta, "true_x_m": result.true_state.x,
                               "true_v_m_s": result.true_state.v, "actuator_force_n": result.actuator_force_n,
                               "requested_force_n": result.requested_force_n, "reward": result.reward,
                               "terminated": result.terminated, "truncated": result.truncated})
        metrics = episode_metrics(formal, initial_state=spec.scenario.initial_state, dt_s=spec.dt_s,
                                  max_steps=spec.max_steps, force_limit_n=spec.force_limit_n,
                                  end_reason="cancelled" if report["status"] == "cancelled" else rows[-1]["end_reason"])
        intervals = {"saturation_intervals_s": _intervals(rows, lambda row: abs(row["requested_force_n"]) > spec.force_limit_n, spec.dt_s),
                     "integral_frozen_intervals_s": _intervals(rows, lambda row: row["diagnostics"]["frozen"], spec.dt_s)}
        if kind == "pi":
            metrics.update(velocity_recovery_metrics(rows, dt_s=spec.dt_s))
        folder = output / f"candidate-{index:02d}"
        save_recording(output, "L14" if kind == "p" else "L18", spec, rows, code=source,
                       destination=folder, status="cancelled" if report["status"] == "cancelled" else "finished")
        results.append({"name": name, "parameters": parameters, "configuration_hash": configuration_hash(spec),
                        "recording": folder.name, "metrics": metrics, **intervals})
        persist()
        if progress_callback:
            progress_callback(index+1, len(candidates), results[-1])
        if report["status"] == "cancelled":
            break
    else:
        report["status"] = "completed"
    fields = ["name", "kp", "episode_steps", "end_reason", "rms_theta_rad", "max_abs_x_m", "mean_abs_actuator_force_n",
              "saturation_fraction", "velocity_recovery_s", "post_switch_max_abs_velocity_error_m_s"]
    with (output / "scan.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for candidate in results:
            writer.writerow({"name": candidate["name"], **candidate["parameters"], **candidate["metrics"]})
    persist()
    return report
