"""Learner work survives navigation; disposable probes never change a live run."""

import json
import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.desktop.app import ControlLabWindow
from control_lab.lessons import LessonSession, load_lesson
from control_lab.storage.progress import ProgressStore


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = ControlLabWindow(data_dir=tmp_path)
    window.show()
    QTest.qWait(20)
    yield window
    window.close()
    window.deleteLater()
    app.processEvents()


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "Timed out waiting for the actual worker"


def test_centering_keeps_pole_survival_separate_and_records_real_dwell(window):
    window.select_lesson("L16")
    assert not window.editor_tabs.isTabVisible(1)
    assert window.centering_status.isHidden()
    window._go_to_step(1)
    assert not window.centering_status.isHidden()
    assert not window.editor_tabs.isTabVisible(1)
    window._go_to_step(2)
    assert window.editor_tabs.isTabVisible(1)
    window.timer.stop()
    for source, reaches in (
        ('def control(state, dt):\n    return 60*state["theta"] + 12*state["omega"]\n', False),
        (window.lesson_session.lesson.read_solution(), True),
    ):
        window.editor.setPlainText(source)
        window.run_code()
        deadline = time.monotonic() + 15
        while not window.fell and time.monotonic() < deadline:
            window.tick()
            QApplication.processEvents()
            time.sleep(.001)
        assert len(window._experiment_rows) == 500
        result = window._experiment_rows[-1]["centering"]
        assert result["pole_survived"]
        assert (result["first_reached_time_s"] is not None) == reaches
        if reaches:
            assert result["first_reached_time_s"] == pytest.approx(3.08)
            assert "3.08" in window.centering_status.text()
            assert any(event["event"] == "centering.reached" for event in window.lesson_session.events)
        else:
            assert "尚未达标" in window.centering_status.text()


def test_failed_installer_launch_restores_update_controls(window, monkeypatch, tmp_path):
    from control_lab.updates import installer
    window.open_updates()
    window.updates_panel._installer = tmp_path / "installer.exe"
    def failed_launch(*args):
        raise OSError("installer unavailable")
    monkeypatch.setattr(installer, "launch_installer", failed_launch)
    window._request_installation(window.updates_panel._installer)
    assert window.isVisible()
    assert window.timer.isActive()
    assert window._pending_installer is None
    assert not window.updates_panel._closing
    assert window.updates_panel.check_button.isEnabled()
    assert window.updates_panel.install_button.isEnabled()
    assert "installer unavailable" in window.status.text()


def test_predictions_drafts_and_evidence_survive_return_and_restart(window):
    window.select_lesson("L03")
    window._go_to_step(4)
    window.lesson_panel.reflection.setPlainText("经过中心时仍可能向左走。")
    window.lesson_panel.submit.click()
    window.lesson_panel.next_button.click()
    window.lesson_panel.reflection.setPlainText("这是一条还没提交的曲线笔记")
    window._go_to_step(4)
    assert window.lesson_panel.reflection.toPlainText() == "经过中心时仍可能向左走。"
    assert window.lesson_session.can_advance
    window._go_to_step(5)
    assert window.lesson_panel.reflection.toPlainText() == "这是一条还没提交的曲线笔记"
    assert not window.lesson_session.can_advance  # draft is not a submitted answer
    window.select_lesson("L05")
    window.select_lesson("L03")
    assert window.lesson_panel.reflection.toPlainText() == "这是一条还没提交的曲线笔记"
    window._go_to_step(4)
    assert window.lesson_session.responses["step_05"]["event"] == "prediction.submitted"
    assert window.lesson_panel.reflection.toPlainText() == "经过中心时仍可能向左走。"


def test_steps_reveal_position_before_velocity_and_curve(window):
    window.select_lesson("L03")
    assert window.metrics_by_name["x"].isVisible()
    assert not window.metrics_by_name["v"].isVisible()
    assert not window.chart.isVisible()
    window._go_to_step(2)
    assert window.metrics_by_name["v"].isVisible()
    assert not window.chart.isVisible()
    window._go_to_step(4)
    assert window.chart.isVisible()
    window.select_lesson("L04")
    assert window.metrics_by_name["theta"].isVisible()
    assert not window.metrics_by_name["omega"].isVisible()
    window._go_to_step(2)
    assert window.metrics_by_name["omega"].isVisible()


def test_probe_three_branches_uses_fresh_module_without_advancing_live_session(window):
    window.select_lesson("L07")
    window._go_to_step(3)
    source = window.lesson_session.lesson.read_solution()
    window.editor.setPlainText(source)
    before = window.sim.session.spec, window.state.copy(), window.sim.session.step_index
    for index, force in ((0, 1.), (1, 0.), (2, -1.)):
        window.probe_panel.case.setCurrentIndex(index)
        window.probe_panel.run_button.click()
        wait_for(lambda: not window.probe_panel._active)
        assert not window.probe_panel.worker.error
        event = window.lesson_session.events[-1]
        assert event["event"] == "code.probed"
        assert event["payload"]["force_n"] == force
        assert event["payload"]["lines"]
        assert window.editor.extraSelections()
    assert window.lesson_session.can_advance
    assert before == (window.sim.session.spec, window.state, window.sim.session.step_index)
    records = list(window.progress_store.root.glob("exercises/L07/*/probe.json"))
    assert len(records) == 3
    assert any(json.loads(path.read_text(encoding="utf-8"))["all_cases_correct"] for path in records)


def test_editing_draft_keeps_original_run_snapshot_and_backups(window):
    window.select_lesson("L05")
    source = "def control(state, dt):\n    return 0.1\n"
    window.editor.setPlainText(source)
    window.run_code()
    wait_for(lambda: len(window._experiment_rows) >= 3)
    assert not window.editor.isReadOnly()
    changed = "def control(state, dt):\n    return -0.8\n"
    window.editor.setPlainText(changed)
    wait_for(lambda: len(window._experiment_rows) >= 6)
    assert window._experiment_code == source
    assert all(row["requested_force_n"] == .1 for row in window._experiment_rows)
    window.stop_code()
    folder = window._archive_experiment()
    assert (folder / "controller_snapshot.py").read_text(encoding="utf-8") == source
    window.load_example()
    assert (window.progress_store.root / "workspace/L05/before_template.py").read_text(encoding="utf-8") == changed
    assert window._template_path.read_text(encoding="utf-8") == window.lesson_session.lesson.read_template()


def test_syntax_error_points_to_real_source_line(window):
    window.select_lesson("L05")
    window.editor.setPlainText("def control(state, dt)\n    return 0.1\n")
    window.run_code()
    wait_for(lambda: window.error_label.isVisible())
    assert "第 1 行" in window.error_label.text()
    assert "冒号" in window.error_label.text()
    assert window.editor.extraSelections()[0].cursor.blockNumber() == 0


def test_template_versions_are_immutable_and_do_not_touch_draft(tmp_path):
    store = ProgressStore(tmp_path)
    first = store.preserve_template("L07", 1, "original")
    store.save_lesson("L07", {"draft_code": "my work", "template_snapshot": str(first)})
    second = store.preserve_template("L07", 2, "new instructions")
    assert first != second and first.read_text() == "original"
    assert store.get_lesson("L07")["draft_code"] == "my work"
    second.write_text("edited", encoding="utf-8")
    with pytest.raises(ValueError, match="被修改"):
        store.preserve_template("L07", 2, "new instructions")


def test_updated_step_needs_new_evidence_but_old_work_is_kept():
    lesson = load_lesson("L03")
    old = LessonSession(lesson)
    old.emit("step.acknowledged")
    old.advance()
    old.go_to(4)
    old.emit("prediction.submitted", value="first explanation")
    old.emit("prediction.submitted", value="revised explanation")
    saved = old.snapshot()
    changed_step = replace(lesson.steps[0], instruction="New experiment requiring fresh observation")
    new = LessonSession(replace(lesson, content_version=lesson.content_version + 1,
                               steps=(changed_step, *lesson.steps[1:])), saved)
    assert "step_01" not in new.completed_step_ids
    assert "step_01" in new.prior_versions[-1]["completed_step_ids"]
    assert new.responses["step_05"]["value"] == "revised explanation"
    assert new.response_revisions["step_05"][0]["value"] == "first explanation"


def test_precomputed_clips_and_sign_cards_use_physics_and_keep_main_session(window):
    from control_lab.lessons.foundation_clips import make_comparison
    from control_lab.core.session import EpisodeSession
    from control_lab.core.scenario import ScenarioConfig
    from control_lab.core.types import EpisodeSpec, State
    data = make_comparison("L15")
    assert data == make_comparison("L15")
    assert data["clips"][0]["frames"][0]["state"] == [0, 0, .05, .15]
    for clip in data["clips"]:
        config = dict(clip["spec"])
        scene = dict(config.pop("scenario"))
        scene["initial_state"] = State(**scene["initial_state"])
        scene["disturbances"] = tuple(scene["disturbances"])
        scene["target_schedule"] = tuple(scene["target_schedule"])
        simulation = EpisodeSession(EpisodeSpec(scenario=ScenarioConfig(**scene), **config))
        try:
            assert list(simulation.step(0).true_state) == clip["frames"][1]["state"]
        finally:
            simulation.close()
    window.select_lesson("L03")
    window._go_to_step(6)
    before = window.state.copy(), window.sim.session.step_index
    panel = window.foundations_panel
    panel.play.click()
    wait_for(lambda: not panel.timer.isActive())
    assert before == (window.state, window.sim.session.step_index)
    assert not window.lesson_session.can_advance
    for pair, values in zip(panel.answers, ((1,-1), (-1,1), (0,0))):
        for combo, value in zip(pair, values):
            combo.setCurrentIndex(combo.findData(value))
    panel.check.click()
    assert window.lesson_session.can_advance
    assert window.lesson_session.events[-1]["payload"]["correct_count"] == 3
    window.select_lesson("L04")
    window._go_to_step(5)
    panel.convert_button.click()
    assert "0.0873" in panel.radians.text()
    assert window.lesson_session.can_advance


def test_small_logical_screen_keeps_lab_and_guide_reachable(window):
    window.select_lesson("L07")
    window.resize(853, 480)  # 1280x720 display at 150 percent scaling
    QTest.qWait(30)
    assert (window.width(), window.height()) == (853, 480)
    assert window.workspace_tabs.isVisible()
    assert not window.sidebar.isVisible()
    assert window.compact_tools.isVisible()
    window.workspace_tabs.setCurrentIndex(1)
    assert window.editor.isVisible()
    window.resize(1380, 860)
    QTest.qWait(30)
    assert window.sidebar.isVisible()
    assert window.editor.isVisible() and window.canvas.isVisible()


def test_save_failure_prevents_navigation_and_close_without_losing_notes(window, monkeypatch):
    window.select_lesson("L03")
    window._go_to_step(4)
    window.lesson_panel.reflection.setPlainText("这段话尚未成功写盘")
    session = window.lesson_session
    def fail(*args, **kwargs):
        raise OSError("simulated disk failure")
    original = window.progress_store.save_lesson
    monkeypatch.setattr(window.progress_store, "save_lesson", fail)
    assert window.select_lesson("L05") is False
    assert window.lesson_session is session
    assert window.lesson_combo.currentData() == "L03"
    assert window.close() is False
    assert window.isVisible()
    assert session.response_text() == "这段话尚未成功写盘"
    monkeypatch.setattr(window.progress_store, "save_lesson", original)
    assert window._save_progress()
    assert window.progress_store.get_lesson("L03")["response_drafts"]["step_05"] == session.response_text()


def test_recording_failure_prevents_reset_switch_and_close(window, monkeypatch):
    import control_lab.storage.records as records
    window.select_lesson("L01")
    window.single_step()
    rows = list(window._experiment_rows)
    assert rows
    def fail(*args, **kwargs):
        raise OSError("simulated recording failure")
    original = records.save_recording
    monkeypatch.setattr(records, "save_recording", fail)
    assert window.reset_experiment() is False
    assert window.select_lesson("L03") is False
    assert window.close() is False
    assert window._experiment_rows == rows
    assert window.isVisible()
    monkeypatch.setattr(records, "save_recording", original)
    assert window.select_lesson("L03") is True
    assert window.progress_store.get_lesson("L01")["attempt_refs"]


def test_successful_probes_and_quiz_attempt_unlock_reference_answer():
    for event in ("code.probed", "answer.checked"):
        session = LessonSession(load_lesson("L07"))
        assert not session.has_attempt
        session.emit(event, correct=False)
        assert session.has_attempt  # a real unsuccessful attempt also deserves help


@pytest.mark.parametrize("lesson,expected", [("L08", [1., -1.]), ("L10", [-1., 0.]), ("L12", [.2, -.2])])
def test_state_probe_teaches_velocity_position_and_angle(window, lesson, expected):
    window.select_lesson(lesson)
    window.editor.setPlainText(window.lesson_session.lesson.read_template() if lesson == "L12"
                              else window.lesson_session.lesson.read_solution())
    initial = window.state.copy(), window.sim.session.step_index
    for index, force in enumerate(expected):
        window.probe_panel.case.setCurrentIndex(index)
        window.probe_panel.run_button.click()
        wait_for(lambda: not window.probe_panel._active)
        assert not window.probe_panel.worker.error
        event = window.lesson_session.events[-1]
        assert event["payload"]["force_n"] == pytest.approx(force)
    assert initial == (window.state, window.sim.session.step_index)
    assert event["payload"]["all_cases_correct"]


def test_short_force_runs_pause_after_same_ten_physics_steps(window):
    window.select_lesson("L05")
    window._go_to_step(1)
    final = []
    for force in (1., -1.):
        window.editor.setPlainText(f"def control(state, dt):\n    return {force}\n")
        window.short_run_button.click()
        wait_for(lambda: window.paused and len(window._experiment_rows) == 10)
        assert window.sim.session.step_index == 10
        assert window._experiment_rows[-1]["simulation_time_s"] == pytest.approx(.2)
        final.append(window.state.copy())
        QTest.qWait(80)
        assert window.state == final[-1] and len(window._experiment_rows) == 10
    assert final[0] == pytest.approx([-value for value in final[1]])
    assert window.lesson_session.can_advance
