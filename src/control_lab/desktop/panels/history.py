"""An experiment library and recorded-frame player; replay never runs a policy."""
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from control_lab.desktop.ui_widgets import SignalChart, SimulationCanvas
from control_lab.storage.replay import export_recording, load_recording


class HistoryDialog(QDialog):
    referenceRequested = Signal(object)
    restoreRequested = Signal(object)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.recording = None
        self.setWindowTitle("实验记录")
        self.resize(min(920, parent.width() - 40) if parent else 920,
                    min(680, parent.height() - 40) if parent else 680)
        layout = QVBoxLayout(self)
        self.records = QComboBox()
        self.records.setAccessibleName("选择保存的实验")
        layout.addWidget(self.records)
        self.notice = QLabel("回放使用保存的轨迹，不重新运行代码，也不产生新成绩。")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.tabs = QTabWidget()
        trajectory = QWidget()
        visual = QVBoxLayout(trajectory)
        self.canvas = SimulationCanvas()
        self.canvas.allow_drag = False
        self.canvas.setMinimumHeight(180)
        visual.addWidget(self.canvas, 1)
        self.chart = SignalChart()
        self.chart.setMinimumHeight(120)
        self.chart.available_channels = {"target_v", "requested_force", "true_theta"}
        self.channels = QComboBox()
        for title, channel in (("角度 · °", "theta"), ("位置 · m", "x"), ("速度 · m/s", "v"), ("推力 · N", "force"), ("积分", "integral")):
            self.channels.addItem(title, channel)
        self.channels.currentIndexChanged.connect(self._channel_changed)
        visual.addWidget(self.channels)
        visual.addWidget(self.chart)
        self.tabs.addTab(trajectory, "轨迹回放")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.tabs.addTab(self.details, "代码与条件")
        layout.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.play_pause)
        controls.addWidget(self.play_button)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self.show_frame)
        controls.addWidget(self.slider, 1)
        self.time_label = QLabel("0.00 s")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)
        actions = QHBoxLayout()
        self.reference_button = QPushButton("用作对照曲线")
        self.reference_button.clicked.connect(self.use_reference)
        actions.addWidget(self.reference_button)
        self.restore_button = QPushButton("恢复代码与条件")
        self.restore_button.clicked.connect(self.restore)
        actions.addWidget(self.restore_button)
        self.export_button = QPushButton("导出实验包")
        self.export_button.clicked.connect(self.export)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_frame)
        self.records.currentIndexChanged.connect(self._selected)
        self.refresh_records()

    def refresh_records(self):
        self.records.blockSignals(True)
        self.records.clear()
        for folder in sorted((self.data_dir / "runs").glob("*"), reverse=True):
            if (folder / "report.json").is_file() and (folder / "trajectory.csv").is_file():
                self.records.addItem(folder.name, str(folder))
        self.records.blockSignals(False)
        self._selected()

    def _selected(self, *_):
        self.timer.stop()
        self.play_button.setText("播放")
        self.recording = None
        self.chart.clear()
        for button in (self.play_button, self.reference_button, self.restore_button, self.export_button):
            button.setEnabled(False)
        folder = self.records.currentData()
        if not folder:
            self.notice.setText("还没有已保存的实验。先运行一次，再点击“保存实验”。")
            return
        try:
            self.recording = load_recording(folder)
            recording = self.recording
            self.canvas.show_pole = recording.spec.scenario.environment == "cartpole"
            for row in recording.rows:
                self.chart.append(list(row["observed_state"].values()), row["actuator_force_n"],
                    true_state=list(row["true_state"].values()), time_s=row["simulation_time_s"],
                    target_v=row["target_velocity_mps"], requested_force=row["requested_force_n"],
                    reward=row["reward"], diagnostics=row["diagnostics"])
            details = {"课号": recording.report["lesson_id"], "实验状态": recording.report["status"],
                       "原始条件": recording.report["spec"], "代码摘要": recording.report.get("controller_sha256")}
            self.details.setPlainText(json.dumps(details, ensure_ascii=False, indent=2) +
                                      "\n\n代码快照：\n" + (recording.code or "手动实验，没有控制代码。"))
            self.notice.setText("回放使用保存的轨迹，不重新运行代码，也不产生新成绩。移动曲线上的鼠标可查看同一时刻的读数。")
            self.timer.setInterval(max(1, round(recording.spec.dt_s * 1000)))
            self.slider.setRange(0, max(0, len(recording.rows) - 1))
            self.slider.setValue(0)
            self.show_frame(0)
            for button in (self.play_button, self.reference_button):
                button.setEnabled(bool(recording.rows))
            self.restore_button.setEnabled(recording.code is not None and len(recording.report["input_modes"]) == 1 and set(recording.report["input_modes"]).issubset({"force_n", "velocity_mps"}))
            self.export_button.setEnabled(True)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.notice.setText(f"这个实验暂时无法读取：{exc}")

    def _channel_changed(self, *_):
        self.chart.channel = self.channels.currentData()
        self.chart.update()

    def show_frame(self, index):
        if self.recording is None or not self.recording.rows:
            return
        row = self.recording.rows[index]
        self.canvas.set_state(list(row["true_state"].values()), row["actuator_force_n"], True, False)
        self.time_label.setText(f"{row['simulation_time_s']:.2f} s")
        self.chart.cursor_time = row["simulation_time_s"]
        self.chart.update()

    def play_pause(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        elif self.recording and self.recording.rows:
            if self.slider.value() == self.slider.maximum():
                self.slider.setValue(0)
            self.timer.start()
            self.play_button.setText("暂停")

    def next_frame(self):
        if self.slider.value() >= self.slider.maximum():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.slider.setValue(self.slider.value() + 1)

    def use_reference(self):
        if self.recording:
            self.referenceRequested.emit(self.recording)
            self.accept()

    def restore(self):
        if self.recording and self.recording.code is not None:
            self.restoreRequested.emit(self.recording)
            self.accept()

    def export(self):
        if self.recording is None:
            return
        folder = self.data_dir / "exports"
        folder.mkdir(parents=True, exist_ok=True)
        destination = folder / f"{self.recording.folder.name}.zip"
        try:
            export_recording(self.recording, destination)
            self.notice.setText(f"实验包已导出：{destination}")
        except (OSError, ValueError) as exc:
            self.notice.setText(f"实验包未导出：{exc}")

    def done(self, result):
        self.timer.stop()
        super().done(result)
