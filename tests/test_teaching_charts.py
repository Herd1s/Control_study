import math
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from control_lab.desktop.ui_widgets import FlowIndicator, SignalChart


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_velocity_force_and_noise_use_gated_paired_curves_and_shared_scale(app):
    chart = SignalChart()
    chart.append([0, .3, .02, .1], 10, true_state=[0, .3, .019, .1],
                 target_v=4, requested_force=14, time_s=.02)
    chart.channel = "v"
    assert [series[0] for series in chart.series()] == ["v"]
    chart.available_channels = {"v", "target_v", "force", "requested_force", "theta", "true_theta"}
    assert [series[0] for series in chart.series()] == ["v", "target_v"]
    assert chart.ranges()[3] >= 4
    chart.channel = "force"
    assert [series[0] for series in chart.series()] == ["force", "requested_force"]
    assert chart.ranges()[3] >= 14
    chart.channel = "theta"
    assert [series[0] for series in chart.series()] == ["theta", "true_theta"]
    chart.resize(500, 150)
    assert not chart.grab().isNull()
    chart.close()


def test_reference_survives_new_run_and_contains_a_frozen_snapshot(app):
    chart = SignalChart()
    for step in range(600):
        chart.append([0, .2, .01, 0], 1, time_s=(step+1)*.02)
    assert len(chart.history) == 600  # L18's target change at four seconds remains available.
    assert chart.pin_reference("A：旧参数")
    chart.clear()
    assert len(chart.history) == 0
    assert len(chart.reference_history) == 600
    chart.append([0, .1, .02, 0], 2, time_s=.02)
    assert chart.reference_history[0]["force"] == 1
    assert chart.series()[-1][1] == "A：旧参数"
    assert chart.ranges()[1] == 12
    chart.clear_reference()
    assert not chart.reference_history
    chart.close()


def test_absent_diagnostics_are_unavailable_instead_of_fabricated_zero(app):
    chart = SignalChart()
    chart.append([0, 0, 0, 0], time_s=.02)
    chart.channel = "integral"
    assert chart.history[-1]["integral"] is None
    chart.append([0, 0, 0, 0], time_s=.04, diagnostics={"integral": .03, "i_n": .03})
    assert chart.history[-1]["integral"] == .03
    assert chart.history[-1]["d"] is None
    chart.close()


def test_flow_animates_without_advancing_or_changing_physics(app):
    flow = FlowIndicator()
    flow.display_step([0, .1, .05, 0], 3, .02)
    assert flow.stage == 0
    deadline = time.monotonic() + 1
    while flow.stage == 0 and time.monotonic() < deadline:
        QTest.qWait(10)
    assert flow.stage >= 1
    while flow.stage < 2 and time.monotonic() < deadline:
        QTest.qWait(10)
    assert flow.stage == 2
    assert flow.step_count == 1
    assert flow.dt == .02 and flow.force == 3
    flow.resize(550, 100)
    assert not flow.grab().isNull()
    flow.clear()
    assert flow.stage == -1 and flow.step_count == 0
    flow.close()


def test_cursor_compares_identical_physical_time_without_extending_short_run(app):
    chart = SignalChart()
    chart.channel = "force"
    chart.append([0, 0, 0, 0], 1, time_s=.02)
    chart.append([0, 0, 0, 0], 2, time_s=.04)
    chart.pin_reference("实验 A")
    chart.clear()
    for step in range(1, 4):
        chart.append([0, 0, 0, 0], 3, time_s=step * .02)
    assert "实验 A：+2 N" in chart.readout_at(.04)
    assert "实际推力：+3 N" in chart.readout_at(.04)
    assert "实验 A：该时刻无记录" in chart.readout_at(.06)
    chart.close()
