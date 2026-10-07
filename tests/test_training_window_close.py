"""Real main-window close choices with one short independent training job."""
import json
import os
from pathlib import Path
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
pytest.importorskip("PySide6")
from PySide6.QtCore import QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from control_lab.desktop.app import ControlLabWindow
from control_lab.rl.artifacts import atomic_json, validate_artifact

RL_PYTHON = Path(__file__).resolve().parents[1]/".venv-rl/Scripts/python.exe"
pytestmark = pytest.mark.skipif(not RL_PYTHON.is_file(), reason="optional independent RL interpreter is not installed")


def close_with_real_button(app, window, text):
    clicked = []
    timer = QTimer()
    timer.setInterval(10)
    def click():
        modal = app.activeModalWidget()
        if isinstance(modal, QMessageBox) and modal.windowTitle() == "训练还在运行":
            button = next(button for button in modal.buttons() if button.text() == text)
            clicked.append(text)
            button.click()
    timer.timeout.connect(click)
    timer.start()
    started = time.monotonic()
    try:
        window.close()
    finally:
        timer.stop()
    assert clicked == [text]
    return time.monotonic()-started


def test_main_window_cancel_keep_reconnect_and_stop(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = ControlLabWindow(lesson_id="L26", data_dir=tmp_path)
    second = None
    first.show()
    QTest.qWait(50)
    first.training_panel.python_path.setText(str(RL_PYTHON))
    first.training_panel.steps.setValue(10240)
    assert first.training_panel.start_training()
    store = first.training_panel.task_store
    task_id = first.training_panel._task_id
    stop_file = store.directory(task_id)/"STOP"
    try:
        cancel_s = close_with_real_button(app, first, "取消关闭")
        assert first.isVisible() and first.timer.isActive()
        assert first.training_panel.has_active_training() and not stop_file.exists()
        keep_s = close_with_real_button(app, first, "保留后台任务并退出")
        assert not first.isVisible() and first.training_panel.has_active_training()
        assert not stop_file.exists()
        assert json.loads((store.directory(task_id)/"gui-choice.json").read_text())["choice"] == "keep"
        first.deleteLater()
        QTest.qWait(25)
        second = ControlLabWindow(lesson_id="L26", data_dir=tmp_path)
        second.show()
        QTest.qWait(25)
        assert second.training_panel._task_id == task_id
        assert second.training_panel.has_active_training()
        stop_s = close_with_real_button(app, second, "停止并保存后退出")
        assert stop_file.is_file() and stop_s < 3.0
        deadline = time.monotonic()+60
        while second.isVisible() or second.training_panel.has_active_training():
            assert time.monotonic() < deadline, store.read(task_id)
            QTest.qWait(20)
            time.sleep(.001)
        state = store.read(task_id)
        assert state["status"] == "stopped"
        metadata = validate_artifact(state["result"]["path"])
        assert metadata["status"] == "stopped" and metadata["training"]["actual_timesteps"] < 10240
        atomic_json(tmp_path/"window-close-evidence.json", {"status":"passed", "task_id":task_id,
            "buttons":["取消关闭","保留后台任务并退出","停止并保存后退出"],
            "close_call_seconds":{"cancel":cancel_s,"keep":keep_s,"stop":stop_s},
            "same_task_reconnected":True,"metadata":metadata,"task":state})
    finally:
        store.request_stop(task_id)
        deadline = time.monotonic()+30
        while store.read(task_id)["status"] in {"starting","running","stopping"} and time.monotonic()<deadline:
            QTest.qWait(20)
        if second is not None:
            second.close()
