import csv
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.desktop.panels.signals import SignalsPanel


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_done(panel):
    deadline = time.monotonic()+10
    while panel._worker is not None:
        assert time.monotonic() < deadline, "signal worker timed out"
        QTest.qWait(20)


def test_real_threaded_signal_reports_and_errors(app, tmp_path):
    panel = SignalsPanel(tmp_path)
    results, errors = [], []
    panel.completed.connect(results.append)
    panel.error.connect(errors.append)
    assert not panel.analyze() and errors and not results
    assert panel.run_kick()
    assert not panel.shutdown()  # running worker cannot be destroyed
    assert not panel.run_kick()
    wait_done(panel)
    assert results[0]["kind"] == "kick"
    assert results[0]["metrics"]["error_d_at_jump_n"] == -12
    assert Path(results[0]["html"]).is_file()
    assert panel.open_button.isEnabled() and panel.shutdown()
    path = tmp_path / "trajectory.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["simulation_time_s", "observed_theta", "observed_omega", "true_theta", "true_omega"])
        writer.writerows([[i*.02, .002*(-1)**i, 0, 0, 0] for i in range(20)])
    panel.trajectory_path.setText(str(path))
    assert panel.analyze()
    wait_done(panel)
    assert results[1]["kind"] == "noise" and results[1]["samples"] == 20
    assert "rad/s" in panel.status.text()
    panel.dt.setValue(.01)
    assert panel.analyze()
    wait_done(panel)
    assert len(results) == 2 and "dt" in errors[-1]
    assert panel.shutdown() and panel.analyze_button.isEnabled()
    panel.close()


def test_signal_panel_has_no_horizontal_overflow_at_sidebar_width(app, tmp_path):
    panel = SignalsPanel(tmp_path)
    panel.resize(320, 650)
    panel.show()
    QTest.qWait(20)
    assert panel.minimumSizeHint().width() <= 320
    for widget in (panel.dt, panel.tau, panel.analyze_button, panel.kick_button):
        assert widget.geometry().right() <= panel.width()
    panel.close()
