"""Background classroom scans, an explicit table and shared-axis true curves."""
from datetime import datetime
import json
import math
from pathlib import Path
import sys

from PySide6.QtCore import QProcess, QProcessEnvironment, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from control_lab.storage.replay import load_recording


class ComparisonChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.candidates, self.channel, self.spec = [], "theta", None
        self.setMinimumHeight(225)

    def set_results(self, candidates, spec):
        self.candidates, self.spec = candidates, spec
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#f5faf7"))
        if not self.candidates:
            painter.setPen(QColor("#59746b"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "完成扫描后，在同一坐标轴查看所有方案")
            return
        unit = {"theta": "角度 / °", "v": "速度 / m/s", "force": "实际推力 / N", "integral": "积分 / m"}[self.channel]
        def value(row):
            if self.channel == "force":
                return row["actuator_force_n"]
            if self.channel == "integral":
                return row["diagnostics"].get("integral", 0.)
            return row["true_state"][self.channel] * (180/math.pi if self.channel == "theta" else 1.)
        all_rows = [row for _, recording in self.candidates for row in recording.rows]
        if not all_rows:
            return
        values = [value(row) for row in all_rows]
        if self.channel == "v":
            values += [row["target_velocity_mps"] for row in all_rows]
        low, high = min(values+[0.]), max(values+[0.])
        margin = max(.01, (high-low)*.12)
        low, high = low-margin, high+margin
        maximum_time = max(row["simulation_time_s"] for row in all_rows)
        metrics = painter.fontMetrics()
        row_height = metrics.height()+5
        legend_rows = math.ceil(len(self.candidates)/3)
        area = QRectF(max(54, metrics.horizontalAdvance(f"{low:.2f}")+12), row_height*(legend_rows+2),
                      self.width()-max(68, metrics.horizontalAdvance(f"{low:.2f}")+26), self.height()-row_height*(legend_rows+4))
        if area.height() < 20:
            return
        x = lambda t: area.left()+t/maximum_time*area.width()
        y = lambda v: area.bottom()-(v-low)/(high-low)*area.height()
        painter.setPen(QColor("#c9d8d0"))
        painter.drawRect(area)
        painter.drawLine(int(area.left()), int(y(0)), int(area.right()), int(y(0)))
        painter.setPen(QColor("#36594b"))
        painter.drawText(5, row_height, unit)
        painter.drawText(2, int(area.top()+metrics.ascent()), f"{high:.2f}")
        painter.drawText(2, int(area.bottom()), f"{low:.2f}")
        painter.drawText(int(area.left()), int(area.bottom()+row_height), "0 s")
        painter.drawText(int(area.right()-65), int(area.bottom()+row_height), f"{maximum_time:.2f} s")
        for index, (name, recording) in enumerate(self.candidates):
            color = QColor.fromHsv((155+index*67)%360, 170, 160)
            painter.setPen(QPen(color, 1.8))
            legend_x = 8+(index%3)*(self.width()/3)
            legend_y = row_height*(2+index//3)
            painter.drawText(int(legend_x), legend_y, name)
            path = QPainterPath()
            for number, row in enumerate(recording.rows):
                point = (x(row["simulation_time_s"]), y(value(row)))
                path.moveTo(*point) if number == 0 else path.lineTo(*point)
            painter.drawPath(path)
        if self.channel == "v":
            painter.setPen(QPen(QColor("#8c7660"), 1.4, Qt.PenStyle.DashLine))
            path = QPainterPath()
            for index, row in enumerate(self.candidates[0][1].rows):
                point = (x(row["simulation_time_s"]), y(row["target_velocity_mps"]))
                path.moveTo(*point) if index == 0 else path.lineTo(*point)
            painter.drawPath(path)
            painter.drawText(int(area.left()+8), int(area.top()+row_height), "虚线：目标速度")


class SweepPanel(QWidget):
    completed = Signal(dict)
    error = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.output_dir = None
        self.last_report = None
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(lambda *_: self._fail(self.process.errorString()))
        self.process.readyReadStandardOutput.connect(lambda: self.process.readAllStandardOutput())
        layout = QVBoxLayout(self)
        self.kind = QComboBox()
        self.kind.addItem("L14 · P 参数扫描", "p")
        self.kind.addItem("L18 · 三种积分保护", "pi")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        layout.addWidget(self.kind)
        form = QFormLayout()
        self.gains = QLineEdit("0, 20, 40, 60, 100")
        form.addRow("Kp 候选", self.gains)
        self.condition = QComboBox()
        self.condition.addItem("θ=+0.05 rad，其他状态为 0", "primary")
        self.condition.addItem("θ=−0.03 rad，ω=+0.05 rad/s", "check")
        form.addRow("同一初态", self.condition)
        layout.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.note)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("用这些参数重复实验")
        self.stop_button = QPushButton("停止扫描")
        self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["方案", "步数", "原因", "角 RMS/rad", "最大|x|/m", "饱和比例", "恢复/s"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setMaximumHeight(190)
        layout.addWidget(self.table)
        self.channels = QComboBox()
        for text, value in (("真实角度", "theta"), ("速度与目标", "v"), ("实际推力", "force"), ("积分累积", "integral")):
            self.channels.addItem(text, value)
        self.channels.currentIndexChanged.connect(self._channel_changed)
        layout.addWidget(self.channels)
        self.chart = ComparisonChart()
        layout.addWidget(self.chart, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status)
        self._kind_changed()

    def set_kind(self, kind):
        self.kind.setCurrentIndex(self.kind.findData(kind))

    def _kind_changed(self, *_):
        velocity = self.kind.currentData() == "pi"
        self.gains.setEnabled(not velocity)
        self.condition.setEnabled(not velocity)
        self.note.setText("单车速度：Kp=2、Ki=1、外载−0.5 N、限力±1 N；4 s 时目标从4切到0.3 m/s。恢复定义：误差≤0.03 m/s连续1 s；未达到则留空。三方案的配置与目标完全相同。" if velocity else
                          "同一非零初态、±10 N、0.02 s、12°、2.4 m、500步；这是单场景课堂扫描，不是正式 balance-v1 成绩。")
        self.channels.blockSignals(True)
        self.channels.clear()
        choices = (("速度与目标", "v"), ("实际推力", "force"), ("积分累积", "integral")) if velocity else (
            ("真实角度", "theta"), ("速度", "v"), ("实际推力", "force"))
        for text, value in choices:
            self.channels.addItem(text, value)
        self.channels.blockSignals(False)
        self._channel_changed()

    def _channel_changed(self, *_):
        self.chart.channel = self.channels.currentData()
        self.chart.update()

    def _fail(self, message):
        self.status.setText(message)
        self.error.emit(message)

    def start(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            return
        try:
            values = [float(value.strip()) for value in self.gains.text().replace("，", ",").split(",")]
            if not 2 <= len(values) <= 12 or any(not math.isfinite(value) or abs(value)>300 for value in values) or len(set(values)) != len(values):
                raise ValueError("填写2–12个不同的有限 Kp，范围−300至300。")
        except ValueError as exc:
            self._fail(str(exc))
            return
        self.output_dir = self.data_dir / "scans" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.output_dir.parent.mkdir(parents=True, exist_ok=True)
        if getattr(sys, "frozen", False):
            program, args = str(Path(sys.executable).with_name("ControlLabCLI.exe")), ["sweep"]
        else:
            interpreter = Path(sys.executable)
            program = str(interpreter.with_name("python.exe") if interpreter.name.lower() == "pythonw.exe" else interpreter)
            args = ["-m", "control_lab", "sweep"]
        args += ["--kind", self.kind.currentData(), "--condition", "primary" if self.kind.currentData()=="pi" else self.condition.currentData(),
                 "--gains", ",".join(map(str, values)), "--output-dir", str(self.output_dir)]
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        self.process.setProcessEnvironment(environment)
        self.process.start(program, args)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status.setText("后台逐个运行相同配置；失败轨迹同样保留。")

    def stop(self):
        if self.output_dir and self.process.state() != QProcess.ProcessState.NotRunning:
            if self.output_dir.is_dir():
                (self.output_dir / "STOP").touch()
            else:
                self.process.kill()

    def _finished(self, code, status):
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        try:
            if self.output_dir is None:
                raise ValueError("扫描尚未开始")
            report = json.loads((self.output_dir / "scan.json").read_text(encoding="utf-8"))
            self.last_report = report
            self.table.setRowCount(len(report["candidates"]))
            curves = []
            for index, candidate in enumerate(report["candidates"]):
                metrics = candidate["metrics"]
                recovery = metrics.get("velocity_recovery_s")
                values = [candidate["name"], str(metrics["episode_steps"]), metrics["end_reason"],
                          f"{metrics['rms_theta_rad']:.4f}", f"{metrics['max_abs_x_m']:.3f}",
                          f"{metrics['saturation_fraction']:.1%}" if metrics['saturation_fraction'] is not None else "—",
                          f"{recovery:.2f}" if recovery is not None else "未达到" if report["scan_kind"]=="pi" else "—"]
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(json.dumps({"饱和区间/s": candidate["saturation_intervals_s"],
                                               "冻结区间/s": candidate["integral_frozen_intervals_s"]}, ensure_ascii=False))
                    self.table.setItem(index, column, item)
                curves.append((candidate["name"], load_recording(self.output_dir / candidate["recording"])))
            self.table.resizeColumnsToContents()
            self.chart.set_results(curves, report["spec"])
            self.status.setText(f"{'扫描完成' if report['status']=='completed' else '已取消，保留现有结果'}：{self.output_dir}\n表格 scan.csv；各方案可在实验记录器中读取；将鼠标停在表格可看饱和/冻结区间。")
            if report["status"] == "completed" and code == 0:
                self.completed.emit({"path": str(self.output_dir / "scan.json"), "candidate_count": len(curves),
                                     "kind": report["scan_kind"], "condition": report["condition"],
                                     "configuration_hash": report["configuration_hash"]})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail(f"扫描未完成：{exc}")

    def shutdown(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
