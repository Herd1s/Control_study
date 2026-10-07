import csv
import json
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.desktop.panels.rewards import RewardsPanel
from control_lab.desktop.panels.training import TrainingPanel
from control_lab.lessons import load_lesson
from control_lab.lessons.rules import evaluate_rule


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_rewards_thread_save_declaration_and_training_selection(app, tmp_path):
    first, second = tmp_path/"first.csv", tmp_path/"second.csv"
    for index, path in enumerate((first, second), 1):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["simulation_time_s", "true_theta", "true_x", "actuator_force_n"])
            writer.writerows([[i*.02, .02, .1, index] for i in range(1, 21)])
    panel = RewardsPanel(tmp_path)
    training = TrainingPanel(tmp_path)
    results, paths = [], []
    panel.completed.connect(results.append)
    panel.configurationSaved.connect(paths.append)
    panel.configurationSaved.connect(training.set_reward_config)
    for field, path in zip(panel.trajectory_paths, (first, second)):
        field.setText(str(path))
    assert panel.analyze()
    assert not panel.shutdown()
    deadline = time.monotonic()+10
    while panel._worker is not None:
        assert time.monotonic() < deadline
        QTest.qWait(20)
    assert results[0]["trajectories"] == 2 and panel.table.rowCount() == 6
    assert panel.save_configuration()
    assert paths and Path(paths[0]).is_file()
    assert training.reward.currentData() == "balanced-effort-x10-v1"
    assert training.shutdown() and panel.shutdown()
    panel.close()
    training.close()


def test_l28_gui_sends_frozen_report_and_l25_has_actual_smoke(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    panel.set_lesson("L25")
    assert not panel.smoke_button.isHidden()
    assert panel.training_group.isHidden()
    panel.set_lesson("L28")
    model = tmp_path/"model"
    model.mkdir()
    (model/"metadata.json").write_text("{}", encoding="utf-8")
    (model/"policy.zip").write_bytes(b"test")
    panel.model_path.setText(str(model))
    panel.held_out.setChecked(True)
    assert not panel.evaluate_model()
    report = tmp_path/"validation.json"
    report.write_text("{}", encoding="utf-8")
    panel.validation_report_path.setText(str(report))
    launches = []
    panel._launch = lambda operation, args: launches.append((operation, args)) or True
    assert panel.evaluate_model()
    args = launches[0][1]
    assert args[args.index("--split")+1] == "held_out"
    assert args[args.index("--validation-report")+1] == report
    assert panel.comparison_table.columnCount() == 8
    panel.close()


def test_rl_operation_steps_require_real_events_and_seed_diversity():
    for lesson_id, step in (("L24", 0), ("L25", 4), ("L26", 2), ("L27", 5), ("L28", 2), ("L29", 0)):
        rule = load_lesson(lesson_id).steps[step].completion
        assert not evaluate_rule(rule, [{"event": "step.acknowledged", "payload": {}}])
    rule = load_lesson("L26").steps[5].completion
    assert not evaluate_rule(rule, [{"event": "training.completed", "payload": {"seed": 1}}]*2)
    assert evaluate_rule(rule, [{"event": "training.completed", "payload": {"seed": seed}} for seed in (1, 2)])
    rule = load_lesson("L27").steps[5].completion
    assert not evaluate_rule(rule, [{"event": "training.completed", "payload": {"reward_custom": False}}])
    assert evaluate_rule(rule, [{"event": "training.completed", "payload": {"reward_custom": True}}])
