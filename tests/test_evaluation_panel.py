"""Exercise the actual CLI child process, without simulating in the Qt thread."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import time
import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from control_lab.desktop.panels.evaluation import EvaluationPanel


@pytest.fixture(scope="module")
def application():
    app = QApplication.instance() or QApplication([])
    yield app


def until(app, predicate, timeout=30):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("Qt child-process operation did not finish in time")


def test_real_validation_child_process_reports_all_cases(application, tmp_path):
    panel = EvaluationPanel(tmp_path)
    reports, errors = [], []
    panel.completed.connect(reports.append)
    panel.error.connect(errors.append)
    try:
        assert panel.split_box.findData("held_out") == -1
        panel.start_evaluation()
        assert panel.running
        until(application, lambda: bool(reports or errors))
        assert not errors
        assert reports[0]["aggregate"]["episodes"] == 20
        assert reports[0]["aggregate"]["completed_episodes"] == 20
        assert panel.results_table.rowCount() == 20
        assert (panel._output_dir / "report.json").is_file()
        assert panel.start_button.isEnabled() and not panel.stop_button.isEnabled()
    finally:
        panel.shutdown()
        panel.close()


def test_student_failure_rows_and_explicit_cancel_are_distinct(application, tmp_path):
    source = tmp_path / "broken.py"
    source.write_text('def control(state,dt): raise ValueError("intentional bug")\n')
    panel = EvaluationPanel(tmp_path)
    reports, errors = [], []
    panel.completed.connect(reports.append)
    panel.error.connect(errors.append)
    try:
        panel.set_controller_file(source)
        panel.start_evaluation()
        until(application, lambda: bool(reports or errors))
        assert not errors
        assert reports[0]["aggregate"]["controller_errors"] == 20
        assert panel.results_table.rowCount() == 20
        reports.clear()
        source.write_text('def control(state,dt):\n while True: pass\n')
        panel.start_evaluation()
        until(application, lambda: (panel._output_dir / "protocol.json").exists())
        panel.stop_evaluation()
        until(application, lambda: (panel._output_dir / "cancelled.json").exists())
        assert not panel.running
        assert not reports and not errors
        assert "已取消" in panel.status_label.text()
    finally:
        panel.shutdown()
        until(application, lambda: not panel.running)
        panel.close()
