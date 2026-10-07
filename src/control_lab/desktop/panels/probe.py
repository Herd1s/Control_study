"""Single-call branch exercise in a disposable worker, separate from live physics."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPushButton, QVBoxLayout

from control_lab.desktop.engine import CodeController


class ProbePanel(QFrame):
    requested = Signal()
    completed = Signal(dict)
    failed = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.root = Path(data_dir)
        self.worker = CodeController()
        self.source = ""
        self._requested = False
        self._active = False
        self._checks = {}
        self._checked_hash = None
        self._lesson_id = "L07"
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        title = QLabel("用这个状态试算一次")
        layout.addWidget(title)
        self.case = QComboBox()
        self.case.setAccessibleName("试算的小车位置")
        layout.addWidget(self.case)
        self.run_button = QPushButton("试算并显示分支")
        self.run_button.clicked.connect(self.requested)
        layout.addWidget(self.run_button)
        self.result = QLabel("速度、角度、角速度均为零；当前实验保持原状。")
        self.result.setWordWrap(True)
        layout.addWidget(self.result)
        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self._poll)
        self.bind("L07")

    def bind(self, lesson_id):
        self.shutdown()
        self._lesson_id = lesson_id
        self._checked_hash = None
        self._checks = {}
        definitions = {
            "L07": [("左侧 · −0.3 m", [-.3,0.,0.,0.], 1.), ("中心 · 0 m", [0.,0.,0.,0.], 0.), ("右侧 · +0.3 m", [.3,0.,0.,0.], -1.)],
            "L08": [("向左运动 · −0.5 m/s", [0.,-.5,0.,0.], 1.), ("向右运动 · +0.5 m/s", [0.,.5,0.,0.], -1.)],
            "L10": [("右侧 · +0.3 m", [.3,0.,0.,0.], -1.), ("中心 · 0 m", [0.,0.,0.,0.], 0.)],
            "L12": [("向右倾 · +0.02 rad", [0.,0.,.02,0.], .2), ("向左倾 · −0.02 rad", [0.,0.,-.02,0.], -.2)],
        }
        self.case.clear()
        for title, state, expected in definitions[lesson_id]:
            self.case.addItem(title, {"state": state, "expected": expected})
        self.case.setAccessibleName("本课试算状态")
        self.result.setText("选择一个状态，计算一次推力。其他状态量为零；当前小车实验保持原状。")

    def run(self, source):
        self.shutdown()
        self.source = source
        self.observation = self.case.currentData()["state"]
        self.expected = self.case.currentData()["expected"]
        self.x = self.observation[0]
        self._requested = False
        self._active = True
        self.run_button.setEnabled(False)
        self.case.setEnabled(False)
        self.result.setText("正在计算这一次动作……")
        self.worker.start(source, trace_lines=True)
        self.timer.start()

    def _poll(self):
        value = self.worker.poll()
        if self.worker.error:
            error = self.worker.error
            self.shutdown()
            self.result.setText(error.splitlines()[-1])
            self.failed.emit(error)
            return
        if value is not None:
            expected = self.expected
            correct = abs(value - expected) < 1e-9
            result = {"x": self.x, "state": self.observation, "dt_s": .02, "force_n": value, "correct": correct,
                      "expected_n": expected, "lines": list(self.worker.last_lines),
                      "code_sha256": hashlib.sha256(self.source.encode("utf-8")).hexdigest()}
            if self._checked_hash != result["code_sha256"]:
                self._checked_hash = result["code_sha256"]
                self._checks = {}
            self._checks[json.dumps(self.observation)] = correct
            result["case_checks"] = dict(self._checks)
            result["all_cases_correct"] = len(self._checks) == self.case.count() and all(self._checks.values())
            direction = "→ 向右推" if value > 0 else "← 向左推" if value < 0 else "零推力"
            self.result.setText(f"{direction} · {value:g} N\n" +
                ("符合本课的分支任务。" if correct else f"本课这个位置的目标是 {expected:g} N；可以检查条件和返回值。"))
            try:
                folder = self.root / "exercises" / self._lesson_id / uuid4().hex
                folder.mkdir(parents=True)
                (folder / "controller.py").write_text(self.source, encoding="utf-8")
                (folder / "probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                result["path"] = str(folder)
            except OSError as exc:
                self.result.setText(self.result.text() + f"\n试算记录暂未保存：{exc}")
            self.shutdown()
            self.completed.emit(result)
            return
        if self.worker.ready and not self._requested:
            self.worker.request(self.observation, .02)
            self._requested = True

    def shutdown(self):
        self.timer.stop()
        self.worker.stop()
        self._active = False
        self.run_button.setEnabled(True)
        self.case.setEnabled(True)
        return True
