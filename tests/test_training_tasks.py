import json
import os
from pathlib import Path
import subprocess
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from control_lab.desktop.panels.training import TrainingPanel
from control_lab.rl.artifacts import atomic_json, validate_artifact
from control_lab.rl.tasks import TaskStore, process_identity

ROOT = Path(__file__).resolve().parents[1]
RL_PYTHON = ROOT/".venv-rl/Scripts/python.exe"


def test_recycled_pid_is_not_active_and_stop_never_targets_it(tmp_path):
    store = TaskStore(tmp_path)
    task_id = "a"*32
    folder = store.directory(task_id)
    folder.mkdir(parents=True)
    identity = process_identity(os.getpid())
    assert identity
    stale = {**identity, "created": str(identity["created"])+"old"}
    atomic_json(folder/"request.json", {"task_id":task_id,"created_at":"2026-10-08","config":{}})
    atomic_json(folder/"state.json", {"task_id":task_id,"status":"running","process":stale})
    state = store.read(task_id)
    assert state["status"] == "interrupted" and not state["alive"]
    assert not store.request_stop(task_id) and not (folder/"STOP").exists()
    with pytest.raises(ValueError):
        store.directory("../not-a-task")


@pytest.mark.skipif(not RL_PYTHON.is_file(), reason="independent RL runtime required")
def test_gui_parent_exits_keep_job_recovers_and_stops(tmp_path):
    # The launching interpreter really exits; this is stronger than hiding a widget.
    code = '''import json,sys
from PySide6.QtWidgets import QApplication
from control_lab.desktop.panels.training import TrainingPanel
app=QApplication([])
p=TrainingPanel(sys.argv[1])
p.python_path.setText(sys.argv[2]); p.steps.setValue(10240)
assert p.start_training()
assert p.prepare_close('cancel') is False and p.has_active_training()
assert p.prepare_close('keep') is True
print(json.dumps({'task_id':p._task_id,'parent_pid':__import__('os').getpid()}),flush=True)
p.close(); app.quit()
'''
    launched = subprocess.run([sys.executable,"-X","utf8","-c",code,str(tmp_path),str(RL_PYTHON)],
                              capture_output=True,text=True,timeout=20,check=True)
    launch = json.loads(launched.stdout.strip().splitlines()[-1])
    store = TaskStore(tmp_path)
    task_id = launch["task_id"]
    app = QApplication.instance() or QApplication([])
    panel = TrainingPanel(tmp_path)
    try:
        assert panel._task_id == task_id and panel.has_active_training()
        assert process_identity(launch["parent_pid"]) is None
        panel.abort_close()
        deadline = time.monotonic()+60
        while store.read(task_id).get("last_event",{}).get("step_count",0) < 256:
            assert time.monotonic() < deadline, store.read(task_id)
            QTest.qWait(20)
        state = store.read(task_id)
        assert state["alive"] and state["process"]["pid"] != launch["parent_pid"]
        assert panel.prepare_close("stop") is False
        while panel.is_running:
            assert time.monotonic() < deadline
            QTest.qWait(20)
        metadata = validate_artifact(panel.model_path.text())
        assert metadata["status"] == "stopped"
        assert 256 <= metadata["training"]["actual_timesteps"] < 10240
        assert panel.shutdown() and not panel.has_active_training()
        assert json.loads((store.directory(task_id)/"gui-choice.json").read_text())["choice"] == "stop"
    finally:
        store.request_stop(task_id)
        deadline = time.monotonic()+30
        while panel.is_running and time.monotonic() < deadline:
            QTest.qWait(20)
        panel.close()


def test_keep_does_not_suppress_nontraining_shutdown(tmp_path):
    app = QApplication.instance() or QApplication([])
    panel = TrainingPanel(tmp_path)
    panel.python_path.setText(sys.executable)
    assert panel._launch("doctor", [])
    assert panel.prepare_close("keep") is False
    panel.process.kill()  # Read-only probe using base Python; no model or training task.
    panel.process.waitForFinished(5000)
    panel.abort_close()
    assert not panel._leave_training and panel.shutdown()
    panel.close()
