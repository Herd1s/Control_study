import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from control_lab.controllers import ZeroController
from control_lab.controllers.reference_pid import Controller
from control_lab.evaluation import evaluate, load_protocol
from control_lab.evaluation.control_experiments import teaching_scan
from control_lab.evaluation.project import export_project
from control_lab.evaluation.report_io import load_evaluation
from control_lab.storage.replay import load_recording


@pytest.fixture(scope="module")
def evidence(tmp_path_factory):
    root = tmp_path_factory.mktemp("formal-course-evidence")
    paths = []
    for name, factory in (("zero", ZeroController), ("angle", lambda: Controller(False)), ("center", Controller)):
        path = root / name
        evaluate(factory, load_protocol(split="practice"), output_dir=path, controller_name=name)
        paths.append(path)
    return paths


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def until(app, predicate, timeout=20):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(10)
    raise AssertionError("The real background operation did not finish")


def test_reader_validates_saved_case_path_and_never_executes_snapshot(evidence, tmp_path):
    original = load_evaluation(evidence[0], require_complete=True)
    case = original.report["episodes"][0]
    rows = original.case_rows(case["case_id"])
    assert len(rows) == case["episode_steps"] and rows[-1]["terminated"]
    assert rows[0]["time_s"] == .02
    original.report["episodes"][0]["trajectory_file"] = "../escape.csv"
    with pytest.raises(ValueError, match="inside"):
        original.case_rows(case["case_id"])


def test_project_package_hashes_and_commands_recompute_selected_methods(evidence, tmp_path):
    result = export_project(evidence, tmp_path / "project.zip", title="三个真实控制器", reflection="比较失败、漂移与用力。")
    assert result["method_count"] == 3
    unpacked = tmp_path / "unpacked"
    with zipfile.ZipFile(result["path"]) as archive:
        assert "README.md" in archive.namelist()
        archive.extractall(unpacked)
    manifest = json.loads((unpacked / "manifest.json").read_text(encoding="utf-8"))
    assert all(hashlib.sha256((unpacked / path).read_bytes()).hexdigest() == digest for path, digest in manifest["files"].items())
    for index, original_path in enumerate(evidence, 1):
        output = tmp_path / f"recomputed-{index}"
        process = subprocess.run([sys.executable, "-m", "control_lab", "evaluate", "--controller", "student",
                                  "--controller-file", str(unpacked / f"methods/{index:02d}/controller.py"),
                                  "--split", "practice", "--output-dir", str(output)], capture_output=True, timeout=20)
        assert process.returncode == 0, process.stderr.decode(errors="replace")
        original = load_evaluation(original_path).report
        reproduced = load_evaluation(output).report
        assert reproduced["aggregate"] == original["aggregate"]
    with pytest.raises(FileExistsError):
        export_project(evidence, tmp_path / "project.zip")
    with pytest.raises(ValueError, match="distinct"):
        export_project([evidence[0]]*3, tmp_path / "duplicate.zip")


def test_p_scan_keeps_same_nonzero_state_and_saves_all_candidates(tmp_path):
    result = teaching_scan("p", output_dir=tmp_path / "scan")
    assert result["status"] == "completed" and not result["scored_benchmark"]
    assert result["spec"]["protocol_id"] == "teaching-p-scan-primary-v1"
    assert len(result["candidates"]) == 5
    assert len({entry["configuration_hash"] for entry in result["candidates"]}) == 1
    records = [load_recording(tmp_path / "scan" / entry["recording"]) for entry in result["candidates"]]
    assert all(record.spec.scenario.initial_state.theta == .05 for record in records)
    assert all(record.rows[0]["before_state"] == records[0].rows[0]["before_state"] for record in records)
    assert len(list(csv.DictReader((tmp_path / "scan/scan.csv").open(encoding="utf-8-sig")))) == 5
    other = teaching_scan("p", condition="check", gains=[20., 60.], output_dir=tmp_path / "check")
    assert other["spec"]["scenario"]["initial_state"]["theta"] == -.03
    assert other["spec"]["scenario"]["initial_state"]["omega"] == .05
    assert other["configuration_hash"] != result["configuration_hash"]


def test_three_pi_methods_show_measured_recovery_and_actual_frozen_intervals(tmp_path):
    result = teaching_scan("pi", output_dir=tmp_path / "pi")
    assert result["spec"]["scenario"]["environment"] == "cart_velocity"
    assert result["spec"]["force_limit_n"] == 1 and not result["scored_benchmark"]
    candidates = result["candidates"]
    assert len(candidates) == 3 and all(entry["metrics"]["episode_steps"] == 600 for entry in candidates)
    assert all(entry["saturation_intervals_s"] for entry in candidates)
    assert not candidates[0]["integral_frozen_intervals_s"]
    assert candidates[2]["integral_frozen_intervals_s"]
    assert candidates[2]["metrics"]["velocity_recovery_s"] is not None
    assert (candidates[0]["metrics"]["velocity_recovery_s"] is None or
            candidates[0]["metrics"]["velocity_recovery_s"] > candidates[2]["metrics"]["velocity_recovery_s"])


def test_formal_player_uses_common_time_without_extending_failed_method(app, evidence):
    from control_lab.desktop.panels.evaluation_history import EvaluationReportDialog
    parent = QWidget()
    parent.resize(853, 480)
    parent.show()
    dialog = EvaluationReportDialog(evidence[2], parent)
    events = []
    dialog.caseViewed.connect(events.append)
    try:
        dialog.show()
        dialog.set_comparison(evidence[0])
        app.processEvents()
        assert dialog.width() <= 853 and dialog.height() <= 480
        assert len(dialog.rows) == 500 and len(dialog.comparison_rows) < 500
        dialog.slider.setValue(499)
        app.processEvents()
        assert "无后续样本" in dialog.comparison_label.text()
        assert "该时刻无记录" in dialog.chart.readout_at(10.)
        assert len(dialog.chart.reference_history) == len(dialog.comparison_rows)
        assert events[-1]["compared"] and events[-1]["time_s"] == 10.
        assert dialog.content_scroll.verticalScrollBar().maximum() > 0
        dialog.content_scroll.ensureWidgetVisible(dialog.compare_button)
        app.processEvents()
        assert dialog.compare_button.isVisible()
    finally:
        dialog.close()
        parent.close()


def test_evaluation_comparison_and_project_signals_require_real_artifacts(app, evidence, tmp_path):
    from control_lab.desktop.panels.evaluation import EvaluationPanel
    panel = EvaluationPanel(tmp_path)
    panel.resize(853, 480)
    panel.show()
    comparisons, exports = [], []
    panel.comparisonCompleted.connect(comparisons.append)
    panel.projectExported.connect(exports.append)
    try:
        dialog = panel.compare_paths(evidence)
        assert dialog and len(comparisons) == 1 and comparisons[0]["method_count"] == 3
        assert Path(comparisons[0]["path"]).is_file()
        project = panel.open_project()
        for path in evidence:
            project.add_report(path / "report.json")
        project.reflection.setPlainText("零输入失败。PD与回中的漂移有区别。")
        result = project.export_to(tmp_path / "selected.zip")
        assert result and len(exports) == 1 and Path(exports[0]["path"]).is_file()
        assert panel.compare_paths([evidence[0], evidence[0]]) is None
        assert len(comparisons) == 1
    finally:
        panel.shutdown()
        panel.close()


def test_scan_panel_runs_actual_background_cli_and_emits_real_completion(app, tmp_path):
    from control_lab.desktop.panels.sweep import SweepPanel
    panel = SweepPanel(tmp_path)
    completed, errors = [], []
    panel.completed.connect(completed.append)
    panel.error.connect(errors.append)
    panel.show()
    try:
        panel.gains.setText("20,60,100")
        QTest.mouseClick(panel.start_button, Qt.MouseButton.LeftButton)
        until(app, lambda: bool(completed or errors))
        assert not errors
        assert completed[0]["candidate_count"] == 3
        assert panel.table.rowCount() == 3 and len(panel.chart.candidates) == 3
        assert Path(completed[0]["path"]).is_file()
        panel.set_kind("pi")
        QTest.mouseClick(panel.start_button, Qt.MouseButton.LeftButton)
        until(app, lambda: len(completed) == 2 or bool(errors))
        assert not errors and completed[1]["kind"] == "pi"
        assert panel.chart.channel == "v" and len(panel.chart.candidates) == 3
    finally:
        panel.shutdown()
        panel.close()
