import json
import os
from dataclasses import asdict, replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.core.scenario import ForcePulse, get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.desktop.panels.history import HistoryDialog
from control_lab.storage.records import save_recording
from control_lab.storage.replay import export_recording, load_recording


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def saved(tmp_path):
    spec = get_episode_spec("tilt_right")
    spec = replace(spec, scenario=replace(spec.scenario, disturbances=(ForcePulse(3, 2, .5),)))
    rows = []
    with EpisodeSession(spec) as session:
        for _ in range(10):
            before = session.true_state.as_dict()
            row = asdict(session.step(2.0))
            row["before_state"] = before
            row["diagnostics"] = {"p_n": 2.0}
            rows.append(row)
    return save_recording(tmp_path, "L10", spec, rows, code="raise RuntimeError('browsing must never execute this source')")


def test_saved_conditions_frames_and_source_are_read_without_execution(saved, tmp_path):
    recording = load_recording(saved)
    assert recording.spec.scenario.disturbances == (ForcePulse(3, 2, .5),)
    assert recording.rows[3]["disturbance_force_n"] == .5
    assert len(recording.rows) == 10
    assert recording.rows[-1]["simulation_time_s"] == .2
    assert "must never execute" in recording.code
    assert export_recording(recording, tmp_path / "experiment.zip").is_file()
    with pytest.raises(FileExistsError):
        export_recording(recording, tmp_path / "experiment.zip")
    (saved / "controller_snapshot.py").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="代码快照"):
        load_recording(saved)


def test_replay_slider_timer_and_reference_use_saved_frames(app, saved, tmp_path):
    panel = HistoryDialog(tmp_path)
    panel.show()
    reference = []
    panel.referenceRequested.connect(reference.append)
    assert panel.recording.folder == saved.resolve()
    panel.slider.setValue(3)
    assert panel.canvas.state == list(panel.recording.rows[3]["true_state"].values())
    assert panel.chart.cursor_time == .08
    panel.play_button.click()
    QTest.qWait(60)
    assert panel.slider.value() > 3
    panel.play_button.click()
    panel.export_button.click()
    assert (tmp_path / "exports" / f"{saved.name}.zip").is_file()
    panel.reference_button.click()
    assert reference[0].folder == saved.resolve()
    assert not panel.timer.isActive()
    panel.close()


def test_wrong_time_or_count_does_not_show_partial_success(app, saved, tmp_path):
    report_path = saved / "report.json"
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data["steps"] = 11
    report_path.write_text(json.dumps(data), encoding="utf-8")
    panel = HistoryDialog(tmp_path)
    assert not panel.play_button.isEnabled()
    assert "步数" in panel.notice.text()
    panel.close()


def test_explicit_configure_uses_the_recorded_physics_dt(saved):
    from control_lab.desktop.engine import TeachingSimulation
    recording = load_recording(saved)
    sim = TeachingSimulation()
    try:
        spec = replace(recording.spec, dt_s=.01)
        sim.configure_spec(spec)
        sim.start_scenario()
        assert sim.dt == sim.session.dt == .01
        assert sim.step(0)["elapsed"] == .01
        sim.configure("upright")
        assert sim.dt == .02
    finally:
        sim.close()
