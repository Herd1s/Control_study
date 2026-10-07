"""L20 offline signal experiments; bounded data, no UI-thread computation."""
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QDoubleSpinBox, QFileDialog,
)


class _SignalWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, kind, output_dir, trajectory, dt_s, tau_s, parent=None):
        super().__init__(parent)
        self.kind, self.output_dir, self.trajectory = kind, output_dir, trajectory
        self.dt_s, self.tau_s = dt_s, tau_s

    def run(self):
        try:
            from control_lab.lessons.signal_experiments import analyze_trajectory, run_derivative_kick
            if self.kind == "noise":
                output = analyze_trajectory(self.trajectory, self.output_dir,
                                            dt_s=self.dt_s, tau_s=self.tau_s)
            else:
                output = run_derivative_kick(self.output_dir, dt_s=self.dt_s, tau_s=self.tau_s)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.succeeded.emit({"kind": self.kind, "output_dir": str(output),
                "report": str(output / "report.json"), "html": str(output / "report.html"),
                "metrics": report["metrics"], "dt_s": report["dt_s"], "tau_s": report["tau_s"],
                "samples": report["samples"], "source_sha256": report.get("source_sha256")})
        except Exception as exc:
            self.failed.emit(f"实验未完成：{exc}")


class SignalsPanel(QFrame):
    completed = Signal(dict)
    error = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.setObjectName("surface")
        self.data_dir = Path(data_dir).resolve()
        self._worker = None
        self._report_html = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)
        title = QLabel("同一份数据，换一种看法")
        title.setStyleSheet("font-size:20px; font-weight:600")
        title.setWordWrap(True)
        layout.addWidget(title)
        description = QLabel("先保存一轮带噪声实验，再比较同一条轨迹的直接角速度、角度差分与因果滤波。目标跳变是另一个独立信号实验。")
        description.setWordWrap(True)
        layout.addWidget(description)
        row = QHBoxLayout()
        self.trajectory_path = QLineEdit()
        self.trajectory_path.setPlaceholderText("选择保存实验文件夹中的 trajectory.csv")
        self.trajectory_path.setAccessibleName("待分析的轨迹 CSV")
        self.browse_button = QPushButton("选择轨迹")
        self.browse_button.clicked.connect(self._choose_trajectory)
        row.addWidget(self.trajectory_path, 1)
        row.addWidget(self.browse_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("采样周期 dt（s）"))
        self.dt = QDoubleSpinBox()
        self.dt.setDecimals(4)
        self.dt.setRange(.0001, .1)
        self.dt.setSingleStep(.01)
        self.dt.setValue(.02)
        row.addWidget(self.dt)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("滤波时间 tau（s）"))
        self.tau = QDoubleSpinBox()
        self.tau.setDecimals(3)
        self.tau.setRange(0, 1)
        self.tau.setSingleStep(.01)
        self.tau.setValue(.05)
        row.addWidget(self.tau)
        row.addStretch()
        layout.addLayout(row)
        self.analyze_button = QPushButton("分析同一条轨迹")
        self.analyze_button.setObjectName("primary")
        self.analyze_button.clicked.connect(self.analyze)
        self.kick_button = QPushButton("运行目标跳变实验")
        self.kick_button.clicked.connect(self.run_kick)
        layout.addWidget(self.analyze_button)
        layout.addWidget(self.kick_button)
        self.status = QLabel("tau=0 为不滤波。dt 必须与记录一致；分析不会重新运行小车，也不会改变成绩。")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.status)
        self.open_button = QPushButton("打开曲线报告")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_report)
        layout.addWidget(self.open_button, alignment=Qt.AlignmentFlag.AlignLeft)

    @property
    def is_running(self):
        return self._worker is not None and self._worker.isRunning()

    def _choose_trajectory(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择一轮实验的轨迹", str(self.data_dir), "轨迹 CSV (*.csv)")
        if filename:
            self.trajectory_path.setText(filename)

    def _set_busy(self, busy):
        for widget in (self.analyze_button, self.kick_button, self.browse_button,
                       self.trajectory_path, self.dt, self.tau):
            widget.setEnabled(not busy)

    def _start(self, kind):
        if self._worker is not None:
            return False
        trajectory = Path(self.trajectory_path.text().strip())
        if kind == "noise" and (not trajectory.is_file() or trajectory.suffix.lower() != ".csv"):
            self._failed("请先选择已保存的一轮实验轨迹 CSV。")
            return False
        output = self.data_dir / "signal_experiments" / (
            datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{kind}-{uuid4().hex[:8]}")
        worker = _SignalWorker(kind, output, trajectory, self.dt.value(), self.tau.value(), self)
        worker.succeeded.connect(self._succeeded)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        self._worker = worker
        self._set_busy(True)
        self.status.setText("正在计算并保存曲线报告…")
        worker.start()
        return True

    def analyze(self):
        return self._start("noise")

    def run_kick(self):
        return self._start("kick")

    def _succeeded(self, result):
        self._report_html = Path(result["html"])
        self.open_button.setEnabled(True)
        metrics = result["metrics"]
        if result["kind"] == "noise":
            noise = metrics["difference_noise_rms_rad_s"]
            filtered = metrics["filtered_difference_noise_rms_rad_s"]
            description = (f"同一份记录共 {result['samples']} 个样本。差分噪声 RMS：{noise:.4g} rad/s；"
                           f"因果滤波后：{filtered:.4g} rad/s。") if noise is not None and filtered is not None else (
                           "同一份记录已完成比较；可对齐的真实样本不足，部分误差指标不计算。")
            self.status.setText(description + "\n打开曲线查看平滑与滞后的取舍；噪声角度和角速度单位不同，不能直接相除当作增益。")
        else:
            self.status.setText(f"目标在 1 s 从 0 跳到 0.02 rad，测量保持 0。误差求导瞬间为 "
                f"{metrics['error_d_at_jump_n']:.4g} N；仅测量求导的最大绝对值为 "
                f"{metrics['measurement_d_peak_abs_n']:.4g} N。\n这是 D 项信号计算，未运行小车，也未套用执行器限幅。")
        self.completed.emit(result)

    def _failed(self, message):
        self.status.setText(message)
        self.error.emit(message)

    def _finished(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)

    def open_report(self):
        if self._report_html and self._report_html.is_file():
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_html)))
        return False

    def shutdown(self):
        # Input is limited to 20k rows/32 MB. Never destroy a running QThread.
        if self._worker is not None:
            self.status.setText("信号报告即将完成，请保存结束后再关闭。")
            return False
        return True
