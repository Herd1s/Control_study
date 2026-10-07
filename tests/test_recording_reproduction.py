from dataclasses import replace
from pathlib import Path
import json
import subprocess
import sys

import pytest

from control_lab.core.scenario import ForcePulse, get_episode_spec
from control_lab.core.types import Action
from control_lab.desktop.engine import TeachingSimulation
from control_lab.evaluation.reproduce import reproduce_recording
from control_lab.inputs.adapters import controller_from_source
from control_lab.storage.records import save_recording
from control_lab.storage.replay import load_recording


PD = "def control(s, dt): return 60*s['theta'] + 12*s['omega'] + 2*s['x'] + 3*s['v']"
PI = """integral = 0
def reset():
    global integral
    integral = 0
def control(s, dt):
    global integral
    error = s['target_v'] - s['v']
    integral += error*dt
    return 2*error + integral
def diagnostics(): return {'i_n': integral, 'integral': integral}
"""


def gui_recording(root, spec, source, mode="force_n", steps=12):
    """Use the exact desktop physics facade; UI timer only supplies pacing."""
    simulation = TeachingSimulation()
    simulation.configure_spec(spec)
    simulation.start_scenario()
    controller = controller_from_source(source)
    controller.reset()
    rows = []
    try:
        for _ in range(steps):
            before = simulation.session.true_state.as_dict()
            value = controller.act(simulation.observation, simulation.dt, context=simulation.context)
            result = simulation.step(Action(value, mode))
            result["record"]["before_state"] = before
            result["record"]["diagnostics"] = controller.diagnostics
            rows.append(result["record"])
        return save_recording(root, "L10", simulation.session.spec, rows, code=source)
    finally:
        simulation.close()


@pytest.mark.parametrize("scenario,source,mode", [
    ("tilt_right", PD, "force_n"),
    ("tilt_left", "def control(s, dt): return .2 if s['time_s'] < .1 else -.1", "velocity_mps"),
    ("cart_velocity", PI, "force_n"),
    ("measurement_theta_noise", PD, "force_n"),
    ("observation_delay_2", PD, "force_n"),
])
def test_gui_configuration_and_code_reproduce_exact_measured_trajectory(tmp_path, scenario, source, mode):
    # Nondefault dt and a known impulse must survive serialization as well.
    base = get_episode_spec(scenario)
    spec = replace(base, dt_s=.015, scenario=replace(base.scenario, disturbances=(ForcePulse(3, 2, .4),)))
    original_dir = gui_recording(tmp_path / "gui", spec, source, mode)
    original_hashes = {p.name: p.read_bytes() for p in original_dir.iterdir()}
    result = reproduce_recording(original_dir, output_dir=tmp_path / "recomputed")
    assert result["reproduction"]["matches_saved_trajectory"]
    assert result["reproduction"]["maximum_numeric_difference"] == 0
    assert result["steps"] == 12
    restored = load_recording(tmp_path / "recomputed")
    assert restored.spec == spec and restored.report["configuration_hash"]
    assert restored.report["control_lab_version"]
    if mode == "velocity_mps":
        assert restored.report["input_assistance"]["gain_n_per_m_s"] == 8
    if source == PI:
        assert restored.rows[-1]["diagnostics"]["integral"] > 0
    assert all(p.read_bytes() == original_hashes[p.name] for p in original_dir.iterdir())
    with pytest.raises(FileExistsError):
        reproduce_recording(original_dir, output_dir=tmp_path / "recomputed")


def test_runtime_only_memory_is_reported_as_a_difference_not_success(tmp_path):
    original = gui_recording(tmp_path, get_episode_spec("tilt_right"), PD)
    # A valid source snapshot can be different from a prior module's runtime
    # globals. Re-hash it explicitly to model a recording with unrecoverable memory.
    code = "def control(s, dt): return 0"
    import hashlib
    (original / "controller_snapshot.py").write_text(code)
    report = json.loads((original / "report.json").read_text())
    report["controller_sha256"] = hashlib.sha256(code.encode()).hexdigest()
    (original / "report.json").write_text(json.dumps(report))
    result = reproduce_recording(original, output_dir=tmp_path / "difference")
    assert not result["reproduction"]["matches_saved_trajectory"]
    assert result["reproduction"]["first_differences"]
    assert result["status"] == "finished" and result["error"] is None


def test_cli_recomputes_saved_cart_velocity_and_reports_destination(tmp_path):
    original = gui_recording(tmp_path / "gui", get_episode_spec("cart_velocity"), PI)
    target = tmp_path / "cli"
    process = subprocess.run([sys.executable, "-m", "control_lab", "run-recording", str(original),
                              "--output-dir", str(target)], capture_output=True, timeout=20)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    report = json.loads(process.stdout.decode("utf-8"))
    assert report["matches_saved_trajectory"]
    assert Path(report["report"]).is_file()


def test_cancelled_reproduction_saves_partial_actual_steps(tmp_path):
    original = gui_recording(tmp_path / "gui", get_episode_spec("cart_velocity"), PI)
    calls = 0
    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 3
    result = reproduce_recording(original, output_dir=tmp_path / "partial", cancel_requested=cancelled)
    assert result["status"] == "cancelled" and result["steps"] == 3
    assert not result["reproduction"]["matches_saved_trajectory"]
    assert len(load_recording(tmp_path / "partial").rows) == 3
