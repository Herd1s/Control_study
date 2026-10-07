import csv
from dataclasses import asdict, replace
import json
import math

import pytest

from control_lab.controllers.filters import FirstOrderLowPass
from control_lab.core.scenario import get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.lessons import load_lesson
from control_lab.lessons.rules import evaluate_rule
from control_lab.lessons.signal_experiments import (
    analyze_trajectory, compare_recorded_signals, derivative_kick_signal,
    run_derivative_kick,
)
from control_lab.storage.records import save_recording


def write_signal(path, *, noise=.002, count=101, evaluation=False):
    rows = []
    dt = .02
    for i in range(count):
        # Quadratic true angle makes an accidental one-step reference error visible.
        observed_time = i*dt
        true_time = observed_time+dt if evaluation else observed_time
        theta = .03*observed_time**2
        values = {"step_id": i,
            ("time_s" if evaluation else "simulation_time_s"): true_time,
            ("observed_theta_rad" if evaluation else "observed_theta"): theta+noise*(-1)**i,
            ("observed_omega_rad_s" if evaluation else "observed_omega"): .06*observed_time,
            ("true_theta_rad" if evaluation else "true_theta"): .03*true_time**2,
            ("true_omega_rad_s" if evaluation else "true_omega"): .06*true_time}
        rows.append(values)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_same_record_difference_noise_causal_filter_and_units(tmp_path):
    record = write_signal(tmp_path / "input.csv")
    source_before = record.read_bytes()
    result = compare_recorded_signals(record)
    rows, metrics = result["rows"], result["metrics"]
    assert result["rollout_unchanged"] and result["samples"] == 101
    assert rows[0]["difference_omega_rad_s"] is None
    assert metrics["theta_noise_rms_rad"] == pytest.approx(.002)
    assert metrics["difference_noise_rms_rad_s"] == pytest.approx(.2)
    assert metrics["filtered_difference_noise_rms_rad_s"] < .08
    assert metrics["direct_omega_error_rms_rad_s"] == 0
    # The total error includes backward-difference approximation error too.
    assert metrics["difference_total_error_rms_rad_s"] != metrics["difference_noise_rms_rad_s"]
    assert record.read_bytes() == source_before
    prefix = compare_recorded_signals(write_signal(tmp_path / "prefix.csv", count=30))
    assert prefix["rows"] == rows[:30]  # Future samples never affect earlier results.
    passthrough = compare_recorded_signals(record, tau_s=0)
    for row in passthrough["rows"]:
        assert row["filtered_difference_omega_rad_s"] == row["difference_omega_rad_s"]


def test_evaluation_pre_observation_truth_is_aligned_and_unknown_excluded(tmp_path):
    report = compare_recorded_signals(write_signal(tmp_path / "eval.csv", noise=0, evaluation=True))
    assert report["source_schema"] == "evaluation-pre-observation-v1"
    assert report["rows"][0]["true_theta_rad"] is None
    assert report["rows"][0]["time_s"] == pytest.approx(0)
    assert report["rows"][1]["difference_noise_rad_s"] is None
    assert report["rows"][2]["difference_noise_rad_s"] == pytest.approx(0, abs=1e-12)
    assert report["metrics"]["theta_noise_rms_rad"] == pytest.approx(0, abs=1e-12)
    assert report["metrics"]["filtered_difference_noise_rms_rad_s"] == pytest.approx(0, abs=1e-12)
    assert report["metrics"]["direct_omega_error_rms_rad_s"] == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("problem", ["wrong_dt", "missing_sample", "nonfinite", "episodes"])
def test_invalid_record_cannot_create_misleading_report(tmp_path, problem):
    record = write_signal(tmp_path / "input.csv")
    if problem == "wrong_dt":
        with pytest.raises(ValueError, match="dt"):
            analyze_trajectory(record, tmp_path / "output", dt_s=.01)
    else:
        with record.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
        if problem == "missing_sample":
            del rows[10]
        elif problem == "nonfinite":
            rows[10]["observed_theta"] = "nan"
        else:
            for index, row in enumerate(rows):
                row["episode_id"] = "first" if index < 50 else "second"
        with record.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        with pytest.raises(ValueError):
            analyze_trajectory(record, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_target_kick_is_independent_unsaturated_and_matches_formula():
    report = derivative_kick_signal()
    assert report["plant_simulated"] is False and report["actuator_saturation_applied"] is False
    at_jump = report["rows"][50]
    assert at_jump["error_d_n"] == -12
    assert at_jump["measurement_d_n"] == 0
    assert at_jump["filtered_error_d_n"] == pytest.approx(-12*(1-math.exp(-.02/.05)))
    assert all(row["measured_theta_rad"] == 0 for row in report["rows"])
    assert report["rows"][49]["filtered_error_d_n"] == 0
    assert -12 < report["rows"][51]["filtered_error_d_n"] < 0  # causal tail after jump
    assert derivative_kick_signal(tau_s=0)["rows"][50]["filtered_error_d_n"] == -12
    with pytest.raises(ValueError, match="dt"):
        derivative_kick_signal(dt_s=.03)


def test_real_classroom_record_and_html_report_are_saved_without_overwrite(tmp_path):
    spec = replace(get_episode_spec("measurement_theta_noise"), max_steps=100)
    recorded = []
    with EpisodeSession(spec) as session:
        while not session.finished:
            state = session.observed_state
            before = asdict(session.true_state)
            force = 60*state.theta+12*state.omega+2*state.x+3*state.v
            result = session.step(force)
            recorded.append({**asdict(result), "before_state": before})
    recording = save_recording(tmp_path, "L20", spec, recorded, code="reference feedback")
    output = analyze_trajectory(recording / "trajectory.csv", tmp_path / "analysis")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["samples"] == 100
    assert report["metrics"]["difference_noise_rms_rad_s"] > .05
    html = (output / "report.html").read_text(encoding="utf-8")
    assert "mousemove" in html and "<canvas>" in html and "__PAYLOAD__" not in html
    assert "https://" not in html and "http://" not in html
    before = (output / "report.json").read_bytes()
    with pytest.raises(FileExistsError):
        analyze_trajectory(recording / "trajectory.csv", output)
    assert (output / "report.json").read_bytes() == before
    kick = run_derivative_kick(tmp_path / "kick")
    assert all((kick / name).is_file() for name in ("signals.csv", "report.json", "report.html"))


def test_course_templates_match_library_filter_reset_and_actual_rules():
    lesson = load_lesson("L20")
    for source in (lesson.read_template(), lesson.read_solution()):
        namespace = {"__name__": "student_controller"}
        exec(source, namespace)
        namespace["reset"]()
        library = FirstOrderLowPass(namespace["tau"])
        for omega in (.1, -.1, .3):
            force = namespace["control"]({"x": 0, "v": 0, "theta": 0, "omega": omega}, .02)
            assert force == pytest.approx(12*library.update(omega, .02))
        namespace["reset"]()
        namespace["omega_source"] = "difference"
        assert namespace["control"]({"x": 0, "v": 0, "theta": .02, "omega": .8}, .02) == pytest.approx(1.2)
        namespace["reset"]()
        assert namespace["last_theta"] is None and namespace["filtered_omega"] is None
    for index, name in ((2, "signal.analysis.completed"), (5, "signal.kick.completed")):
        rule = lesson.steps[index].completion
        assert not evaluate_rule(rule, [{"event": "step.acknowledged", "payload": {}}])
        assert not evaluate_rule(rule, [{"event": "experiment.saved", "payload": {}}])
        assert evaluate_rule(rule, [{"event": name, "payload": {}}])
