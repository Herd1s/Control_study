"""L29 external inference-only batch, never importing torch into the desktop."""
import codecs
from datetime import datetime
import json
from pathlib import Path
import sys
from uuid import uuid4

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFileDialog, QProgressBar, QPlainTextEdit, QTableWidget, QTableWidgetItem, QDoubleSpinBox, QHeaderView)


class RobustnessPanel(QFrame):
    completed = Signal(dict)
    error = Signal(str)
    reviewed = Signal(dict)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.setObjectName("surface")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._result = None
        self._stop_file = None
        self._html = None
        self._had_error = False
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)
        title = QLabel("冻结策略，一次只改变一个因素")
        title.setWordWrap(True)
        title.setStyleSheet("font-size:20px;font-weight:600")
        layout.addWidget(title)
        note = QLabel("固定PD参数与PPO模型，用相同5个练习初态运行原始条件、20/40 ms观测延迟、角度噪声、杆质量±10%和外力脉冲。2种方法×7组×5回合，共70回合；不重新训练，不打开保留集。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.python_path = QLineEdit()
        self.model_path = QLineEdit()
        for field, caption, model in ((self.python_path, "独立RL Python", False), (self.model_path, "冻结模型包", True)):
            layout.addWidget(QLabel(caption))
            row = QHBoxLayout()
            row.addWidget(field, 1)
            button = QPushButton("选择")
            button.clicked.connect(lambda checked=False, model=model: self._browse(model))
            row.addWidget(button)
            layout.addLayout(row)
        layout.addWidget(QLabel("PD对照：F = aθ + bω + cx + dv（每次开始后参数冻结）"))
        gains = QHBoxLayout()
        self.pd_gains = []
        for name, value in zip(("a", "b", "c", "d"), (60., 12., 2., 3.)):
            gains.addWidget(QLabel(name))
            field = QDoubleSpinBox()
            field.setRange(-1000., 1000.)
            field.setDecimals(2)
            field.setValue(value)
            gains.addWidget(field, 1)
            self.pd_gains.append(field)
        layout.addLayout(gains)
        actions = QHBoxLayout()
        self.start_button = QPushButton("运行固定策略鲁棒性组")
        self.start_button.clicked.connect(self.start)
        self.stop_button = QPushButton("停止并保留记录")
        self.stop_button.clicked.connect(self.stop)
        self.stop_button.setEnabled(False)
        self.open_button = QPushButton("打开完整报告")
        self.open_button.clicked.connect(self.open_report)
        self.open_button.setEnabled(False)
        for button in (self.start_button, self.stop_button, self.open_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 70)
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["方法", "唯一变化", "完成回合", "平均步数", "最短步数"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellClicked.connect(self._review_group)
        layout.addWidget(self.table)
        self.status = QLabel("先记录预测，再比较结果。详细报告保留全部因素、明确初态、噪声seed、模型指纹与失败轨迹。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        self.log.setMaximumHeight(140)
        self.log.hide()
        layout.addWidget(self.log)
        logs = QPushButton("显示运行日志")
        logs.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        layout.addWidget(logs)
        settings = self.data_dir/"training/settings.json"
        try:
            config = json.loads(settings.read_text(encoding="utf-8"))
            self.python_path.setText(config.get("python", ""))
            self.model_path.setText(config.get("last_model", ""))
        except (OSError, ValueError):
            if not getattr(sys, "frozen", False):
                candidate = Path(__file__).resolve().parents[4]/".venv-rl/Scripts/python.exe"
                if candidate.is_file():
                    self.python_path.setText(str(candidate))

    @property
    def is_running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

    def set_model(self, model_dir, python_path=None):
        if not self.is_running:
            self.model_path.setText(str(model_dir))
            if python_path:
                self.python_path.setText(str(python_path))

    def _browse(self, model):
        if model:
            path = QFileDialog.getExistingDirectory(self, "选择完整PPO模型包", self.model_path.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, "选择独立RL Python", self.python_path.text(), "Python (python.exe python)")
        if path:
            (self.model_path if model else self.python_path).setText(path)

    def start(self):
        if self.is_running:
            return False
        python, model = Path(self.python_path.text().strip()), Path(self.model_path.text().strip())
        if not python.is_file() or not (model/"metadata.json").is_file() or not (model/"policy.zip").is_file():
            self._error("请选择独立RL解释器和包含metadata.json/policy.zip的完整模型包。")
            return False
        name = datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid4().hex[:8]
        output = self.data_dir/"robustness"/name
        requests = self.data_dir/"robustness/requests"
        requests.mkdir(parents=True, exist_ok=True)
        self._stop_file = requests/(name+".stop")
        self._result, self._had_error, self._buffer = None, False, ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.progress.setValue(0)
        self.log.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        for field in [self.python_path, self.model_path, *self.pd_gains]:
            field.setEnabled(False)
        self.status.setText("正在载入冻结模型并运行PD/PPO相同条件对照…")
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.start(str(python.resolve()), ["-m", "control_lab.rl.service", "robustness",
            "--model-dir", str(model.resolve()), "--output-dir", str(output.resolve()), "--stop-file", str(self._stop_file.resolve()),
            "--pd-gains", *[str(field.value()) for field in self.pd_gains]])
        return True

    def _read(self):
        self._buffer += self._decoder.decode(bytes(self.process.readAllStandardOutput()))
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.log.appendPlainText(line)
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "robustness_progress":
                self.progress.setRange(0, message["total"])
                self.progress.setValue(message["completed"])
                self.status.setText(f"已完成 {message['completed']} / {message['total']} 回合；{message.get('method', '').upper()} · {message.get('label', message['factor'])}")
            elif message.get("type") == "robustness":
                self._result = message
            elif message.get("type") == "error":
                self._error(message.get("message", "鲁棒性实验未完成"))

    def _finished(self, code, status):
        self._read()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for field in [self.python_path, self.model_path, *self.pd_gains]:
            field.setEnabled(True)
        if code == 0 and self._result:
            try:
                report = json.loads(Path(self._result["path"]).read_text(encoding="utf-8"))
                if not isinstance(report.get("groups"), list):
                    raise ValueError("报告缺少分组结果")
            except (OSError, ValueError, KeyError) as exc:
                self._error(f"无法载入鲁棒性报告：{exc}")
                return
            self.table.setRowCount(len(report["groups"]))
            for index, group in enumerate(report["groups"]):
                stats = group.get("aggregate", {})
                values = (group.get("method_label", "PPO"), group["label"], f"{stats.get('completed_episodes',0)} / {stats.get('episodes',0)}",
                          f"{stats.get('mean_steps',0):.1f}", str(stats.get("worst_steps", "—")))
                for column, value in enumerate(values):
                    self.table.setItem(index, column, QTableWidgetItem(value))
            self._html = Path(self._result["html"])
            self.open_button.setEnabled(True)
            self.status.setText("固定策略对照已完成，未重新训练；打开报告解释不同因素的影响。" if report["status"] == "completed"
                                else "已停止并保留部分记录；这不是完整的70回合结果。")
            self.completed.emit(self._result)
        elif not self._had_error:
            self._error("鲁棒性进程未返回完整结果，请查看日志。")

    def _error(self, message):
        self._had_error = True
        self.status.setText(message)
        self.log.show()
        self.error.emit(message)

    def _review_group(self, row, column):
        if not self._result or self._result.get("status") != "completed":
            return
        try:
            report = json.loads(Path(self._result["path"]).read_text(encoding="utf-8"))
            group = report["groups"][row]
            self.status.setText(f"正在查看：{group.get('method_label', 'PPO')} · {group['label']}。PD与PPO使用相同5个初态与场景；详细报告包含每个失败和轨迹。")
            self.reviewed.emit({"factor": group["factor"], "study_hash": report["study_hash"],
                                "method": group.get("method", "ppo"),
                                "review_key": group.get("method", "ppo")+":"+group["factor"],
                                "path": self._result["path"], "status": "completed"})
        except (OSError, ValueError, IndexError, KeyError) as exc:
            self._error(f"无法读取该组记录：{exc}")

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            for field in [self.python_path, self.model_path, *self.pd_gains]:
                field.setEnabled(True)
            self._error("独立RL解释器无法启动；其他课程仍可使用。")

    def stop(self):
        if self.is_running and self._stop_file:
            self._stop_file.write_text("stop", encoding="utf-8")
            self.status.setText("正在结束当前回合并保留记录…")
            self.stop_button.setEnabled(False)

    def open_report(self):
        if self._html:
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._html)))
        return False

    def shutdown(self):
        if self.is_running:
            self.stop()
            return False
        return True
