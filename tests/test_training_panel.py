import json
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.desktop.panels.training import TrainingPanel


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    return application


def wait_until(predicate, timeout=60):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("Qt operation timed out")
        QTest.qWait(20)


def test_missing_environment_and_invalid_model_leave_courses_usable(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    errors = []
    panel.error.connect(errors.append)
    panel.python_path.setText(str(tmp_path / "missing-python.exe"))
    assert not panel.start_training()
    assert errors and "其他课程" in errors[-1]
    assert not panel.is_running and panel.shutdown()
    assert not panel.evaluate_model()
    assert "模型包" in errors[-1]
    panel.close()


def test_json_messages_replay_and_progress_are_validated(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    states, errors = [], []
    panel.replayState.connect(lambda state, force: states.append((state, force)))
    panel.error.connect(errors.append)
    panel._consume_line('{"type":"progress","additional_steps":128,"requested_steps":256}')
    assert panel.progress.value() == 50
    panel._consume_line('{"type":"replay_state","state":[0,0,0.1,0],"force":2.0}')
    assert states == [([0, 0, .1, 0], 2.0)]
    panel._consume_line('{"type":"replay_state","state":[0,0,NaN,0],"force":2.0}')
    assert len(states) == 1 and errors
    panel.python_path.setText("C:/my-course/python.exe")
    panel._save_settings()
    other = TrainingPanel(tmp_path)
    assert other.python_path.text() == "C:/my-course/python.exe"
    panel.close()
    other.close()


def test_lesson_features_open_gradually_and_reports_compare(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    panel.set_lesson("L25")
    assert panel.training_group.isHidden() and panel.model_group.isHidden()
    panel.set_lesson("L26")
    assert not panel.training_group.isHidden() and panel.model_group.isHidden()
    assert panel.resume_button.isHidden() and panel.replay_button.isHidden()
    panel.set_lesson("L27")
    assert not panel.resume_button.isHidden() and not panel.replay_button.isHidden()
    panel.set_lesson("L28")
    assert panel.training_group.isHidden() and not panel.compare_button.isHidden()
    from control_lab.evaluation import evaluate, load_protocol
    class Reference:
        def reset(self):
            pass
        def act(self, observation, dt):
            x, v, theta, omega = observation
            return 60*theta+12*omega+2*x+3*v
    reports = []
    for name in ("reference-a", "reference-b"):
        report = evaluate(Reference, load_protocol(split="practice"), controller_name=name)
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        reports.append(path)
    result = panel.compare_report_files(reports)
    assert result["type"] == "comparison" and Path(result["path"]).is_file()
    assert panel.comparison_table.rowCount() == 2
    changed = json.loads(reports[1].read_text())
    changed["input_mode"] = "velocity_mps"
    reports[1].write_text(json.dumps(changed), encoding="utf-8")
    assert panel.compare_report_files(reports) is None
    panel.close()


RL_PYTHON = Path(__file__).resolve().parents[1] / ".venv-rl" / "Scripts" / "python.exe"


@pytest.mark.skipif(not RL_PYTHON.is_file(), reason="optional standalone RL environment is not installed")
def test_real_qprocess_train_evaluate_resume_replay(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    panel.python_path.setText(str(RL_PYTHON))
    panel.steps.setValue(256)
    completed, errors, states = [], [], []
    panel.completed.connect(completed.append)
    panel.error.connect(errors.append)
    panel.replayState.connect(lambda state, force: states.append((state, force)))
    try:
        assert panel.check_environment()
        wait_until(lambda: not panel.is_running)
        assert not errors, panel.log.toPlainText()
        assert completed[-1]["type"] == "doctor"
        assert panel.start_training()
        wait_until(lambda: not panel.is_running)
        assert not errors, panel.log.toPlainText()
        first = Path(panel.model_path.text())
        metadata = json.loads((first / "metadata.json").read_text())
        assert metadata["training"]["actual_timesteps"] == 256
        assert panel.evaluate_model()
        wait_until(lambda: not panel.is_running)
        assert not errors, panel.log.toPlainText()
        assert completed[-1]["type"] == "evaluation"
        assert completed[-1]["aggregate"]["episodes"] == 20
        assert panel.start_training(resume=True)
        wait_until(lambda: not panel.is_running)
        assert not errors, panel.log.toPlainText()
        metadata = json.loads((Path(panel.model_path.text()) / "metadata.json").read_text())
        assert metadata["training"]["actual_timesteps"] == 512
        assert panel.replay_model()
        wait_until(lambda: not panel.is_running)
        assert not errors, panel.log.toPlainText()
        assert states and len(states[0][0]) == 4
        assert completed[-1]["type"] == "replay_completed"
        assert panel.shutdown()
    finally:
        if panel.is_running:
            panel.stop()
            wait_until(lambda: not panel.is_running)
        panel.close()


@pytest.mark.skipif(not RL_PYTHON.is_file(), reason="optional standalone RL environment is not installed")
def test_close_requests_cooperative_training_stop(app, tmp_path):
    panel = TrainingPanel(tmp_path)
    panel.python_path.setText(str(RL_PYTHON))
    panel.steps.setValue(25600)
    assert panel.start_training()
    wait_until(lambda: panel.is_running)
    assert panel.shutdown() is False
    wait_until(lambda: not panel.is_running)
    artifact = Path(panel.model_path.text())
    metadata = json.loads((artifact / "metadata.json").read_text())
    assert metadata["status"] == "stopped"
    assert panel.shutdown() is True
    panel.close()
