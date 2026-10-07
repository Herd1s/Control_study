"""Natural classroom controls: no synthetic success events, isolated student files."""
from pathlib import Path
import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from control_lab.desktop.app import ControlLabWindow


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture
def window(application, tmp_path):
    window = ControlLabWindow(data_dir=tmp_path)
    window.show()
    QTest.qWait(20)
    yield window
    window.close()
    window.deleteLater()
    application.processEvents()


def choose_lesson(window, lesson_id):
    index = window.lesson_combo.findData(lesson_id)
    assert index >= 0
    window.lesson_combo.setCurrentIndex(index)
    assert window.lesson_session.lesson.id == lesson_id


def wait_for(window, predicate, seconds=10):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        QTest.qWait(10)
    pytest.fail(window.error_label.text() or window.status.text() or "classroom action timed out")


def test_first_lesson_drag_progress_and_reflection_use_real_widget_actions(window):
    panel = window.lesson_panel
    assert window.lesson_session.step.id == "step_01"
    panel.acknowledge.click()  # Explicit learner acknowledgement, not automatic mastery.
    panel.next_button.click()
    assert window.lesson_session.step.id == "step_02"
    start = window.canvas.cart_rect().center().toPoint() + QPoint(14, 0)
    QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(window.canvas, start + QPoint(14, 0))
    QTest.qWait(60)
    QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=start + QPoint(14, 0))
    assert window.lesson_session.can_advance
    assert window.sim.session.step_index > 0
    assert window.sim.session.true_state.x > 0
    panel.next_button.click()
    assert window.lesson_session.step.id == "step_03"


def test_l03_can_explicitly_save_an_experiment_before_python_lessons(window, tmp_path):
    choose_lesson(window, "L03")
    assert window.export_button.isVisible()
    window.challenge_button.click()
    wait_for(window, lambda: len(window._experiment_rows) >= 3)
    window.pause_button.click()
    window.export_button.click()
    reports = list((tmp_path / "runs").glob("*/report.json"))
    assert reports
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert report["lesson_id"] == "L03"
    assert report["steps"] >= 3
    assert report["scored_benchmark"] is False


def test_l07_positive_and_negative_cases_make_conditional_direction_observable(window):
    choose_lesson(window, "L07")
    assert window.scenario_combo.findData("position_right") >= 0
    assert window.scenario_combo.findData("position_left") >= 0
    window.editor.setPlainText("def control(state, dt):\n    if state['x'] > 0.2:\n        return -1.0\n    if state['x'] < -0.2:\n        return 1.0\n    return 0.0\n")
    for scenario, force in (("position_right", -1), ("position_left", 1)):
        window.scenario_combo.setCurrentIndex(window.scenario_combo.findData(scenario))
        window.run_button.click()
        wait_for(window, lambda: len(window._experiment_rows) >= 2)
        window.stop_button.click()
        assert window._experiment_rows[0]["requested_force_n"] == force


def test_l11_velocity_run_records_its_input_kind_and_actual_target(window, tmp_path):
    choose_lesson(window, "L11")
    window.output_mode.setCurrentIndex(1)
    window.editor.setPlainText("def control(state, dt):\n    return 0.5\n")
    window.run_button.click()
    wait_for(window, lambda: len(window._experiment_rows) >= 3)
    window.stop_button.click()
    assert window._experiment_rows[0]["input_mode"] == "velocity_mps"
    assert window._experiment_rows[0]["target_velocity_mps"] == .5
    window.export_button.click()
    reports = list((tmp_path / "runs").glob("*/report.json"))
    assert json.loads(reports[-1].read_text(encoding="utf-8"))["input_modes"] == ["velocity_mps"]


def test_l16_idle_single_step_runs_the_visible_controller_once(window):
    choose_lesson(window, "L16")
    window.scenario_combo.setCurrentIndex(window.scenario_combo.findData("upright"))
    window.scenario_combo.setCurrentIndex(window.scenario_combo.findData("offset_right"))
    window.editor.setPlainText("def control(state, dt):\n    return 60*state['theta'] + 12*state['omega'] + 2*state['x'] + 3*state['v']\n")
    assert window.paused and not window.code_running
    window.step_button.click()
    wait_for(window, lambda: len(window._experiment_rows) == 1)
    assert window.paused
    QTest.qWait(100)
    assert len(window._experiment_rows) == 1
    assert window._experiment_rows[0]["requested_force_n"] == pytest.approx(.4, abs=1e-6)


def test_l17_loaded_and_unloaded_variants_retain_same_target_and_model(window):
    choose_lesson(window, "L17")
    unloaded = window.scenario_combo.findData("cart_velocity_unloaded")
    assert unloaded >= 0
    expected_target = window.sim.session.target_velocity_mps
    window.scenario_combo.setCurrentIndex(unloaded)
    assert window.sim.session.spec.scenario.constant_force_n == 0
    assert window.sim.session.target_velocity_mps == expected_target == .3
    assert window.sim.session.spec.scenario.velocity_drag_ns_m == .5
    assert not window.canvas.show_pole


def test_l20_noise_selection_does_not_change_truth_or_simulation_clock(window):
    choose_lesson(window, "L20")
    snapshots = []
    for name in ("balance_practice", "measurement_theta_noise", "measurement_omega_noise"):
        index = window.scenario_combo.findData(name)
        assert index >= 0
        window.scenario_combo.setCurrentIndex(index)
        window.challenge_button.click()
        window.pause_button.click()
        snapshots.append((window.sim.session.true_state, window.sim.session.observed_state))
    assert snapshots[0][0] == snapshots[1][0] == snapshots[2][0]
    assert snapshots[0][1].theta != snapshots[1][1].theta
    assert snapshots[0][1].omega != snapshots[2][1].omega
    assert window.canvas.state == list(window.sim.session.true_state)


def test_l08_five_single_steps_use_real_worker_and_show_one_flow_per_step(window):
    choose_lesson(window, "L08")
    assert window.flow_indicator.isVisible()
    window.lesson_panel.acknowledge.click()
    window.lesson_panel.next_button.click()
    assert window.lesson_session.step.id == "step_02"
    window.editor.setPlainText("def control(state, dt):\n    return -2 * state['v']\n")
    window.step_button.click()
    wait_for(window, lambda: window.sim.session.step_index == 1)
    assert window.lesson_session.can_advance
    assert window.flow_indicator.step_count == 1
    assert window.flow_indicator.dt == .02
    window.lesson_panel.next_button.click()
    assert window.lesson_session.step.id == "step_03"
    for count in range(1, 6):
        window.step_button.click()
        wait_for(window, lambda: window.sim.session.step_index == count + 1)
        assert window.lesson_session.can_advance is (count == 5)
    assert window.paused and window.flow_indicator.step_count == 6
    assert window.sim.session.simulation_time_s == pytest.approx(.12)
    window.playback_combo.setCurrentIndex(0)
    QTest.qWait(120)
    assert window.sim.session.step_index == 6
    assert window.sim.dt == .02


def test_l10_reference_button_preserves_curve_across_run_but_not_lesson(window):
    choose_lesson(window, "L10")
    assert window.pin_button.isVisible()
    window.editor.setPlainText("def control(state, dt):\n    return 1.0\n")
    window.run_button.click()
    wait_for(window, lambda: len(window.chart.history) >= 3)
    window.stop_button.click()
    window.pin_button.click()
    pinned = tuple(dict(row) for row in window.chart.reference_history)
    assert len(pinned) >= 3
    window.editor.setPlainText("def control(state, dt):\n    return 2.0\n")
    window.run_button.click()
    wait_for(window, lambda: len(window.chart.history) >= 3)
    window.stop_button.click()
    assert tuple(window.chart.reference_history) == pinned
    assert window.chart.history[0]["force"] == 2
    choose_lesson(window, "L11")
    assert not window.chart.reference_history


def test_l18_velocity_and_saturation_pairs_are_enabled_by_lesson_resources(window):
    choose_lesson(window, "L18")
    window.editor.setPlainText("def control(state, dt):\n    return 8 * (state['target_v'] - state['v'])\n")
    window.step_button.click()
    wait_for(window, lambda: len(window.chart.history) == 1)
    for channel, partner in (("v", "target_v"), ("force", "requested_force")):
        window.channel_combo.setCurrentIndex(window.channel_combo.findData(channel))
        assert [series[0] for series in window.chart.series()][:2] == [channel, partner]
    assert window.chart.history[0]["requested_force"] == 32
    assert window.chart.history[0]["force"] == 1
    assert window.chart.ranges()[3] >= 32


def test_l08_compact_window_keeps_plot_and_cart_layout_valid_and_code_reachable(window):
    window.resize(1280, 720)  # Logical size; 150% corresponds to a 1920x1080 screen.
    choose_lesson(window, "L08")
    QTest.qWait(30)
    assert window.chart.geometry().bottom() < window.chart.parentWidget().height()
    assert window.canvas.geometry().bottom() <= window.flow_indicator.geometry().top()
    assert window.flow_indicator.geometry().bottom() < window.experiment_panel.height()
    window.editor_tabs.setCurrentIndex(0)
    area = window.editor_tabs.currentWidget()
    area.ensureWidgetVisible(window.editor)
    assert window.editor.isVisible() and not window.editor.isReadOnly()
    area.ensureWidgetVisible(window.run_button)
    center = window.run_button.mapTo(area.viewport(), window.run_button.rect().center())
    assert area.viewport().rect().contains(center)


def test_l10_history_restore_retains_explicit_conditions_and_reproduces_actions(window, tmp_path):
    from control_lab.desktop.panels.history import HistoryDialog
    choose_lesson(window, "L10")
    source = "def control(state, dt):\n    return 2.0\n"
    window.editor.setPlainText(source)
    window.run_button.click()
    wait_for(window, lambda: len(window._experiment_rows) >= 5)
    window.stop_button.click()
    expected = [dict(row) for row in window._experiment_rows[:5]]
    window.export_button.click()
    window.editor.setPlainText("def control(state, dt):\n    return -3.0\n")
    panel = HistoryDialog(tmp_path, window)
    panel.restoreRequested.connect(window._restore_recording)
    panel.restore_button.click()
    assert window.paused and not window.code_running
    assert window.editor.toPlainText() == source
    assert window.sim.session.spec == panel.recording.spec
    window.run_button.click()
    wait_for(window, lambda: len(window._experiment_rows) >= 5)
    window.stop_button.click()
    for first, restored in zip(expected, window._experiment_rows):
        assert first["requested_force_n"] == restored["requested_force_n"]
        assert first["true_state"] == restored["true_state"]
        assert first["observed_state"] == restored["observed_state"]
    panel.close()
