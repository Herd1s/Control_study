"""L24 editable reward declarations and same-record scoring, without learning."""
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QDoubleSpinBox, QSpinBox, QPushButton, QFileDialog, QFormLayout, QTableWidget,
    QTableWidgetItem, QHeaderView)

from control_lab.rl.artifacts import atomic_json
from control_lab.rl.rewards import normalize_reward_config, resolve_reward_config


class _RewardWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, paths, configs, destination, parent):
        super().__init__(parent)
        self.paths, self.configs, self.destination = paths, configs, destination

    def run(self):
        try:
            from control_lab.rl.reward_analysis import analyze_rewards
            self.succeeded.emit(analyze_rewards(self.paths, self.configs, self.destination))
        except Exception as exc:
            self.failed.emit(str(exc))


class RewardsPanel(QFrame):
    configurationSaved = Signal(str)
    completed = Signal(dict)
    error = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self._worker = None
        self._report_html = None
        self.setObjectName("surface")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)
        title = QLabel("把目标写成奖励")
        title.setStyleSheet("font-size:20px;font-weight:600")
        layout.addWidget(title)
        description = QLabel("选择1–2份已保存轨迹，比较存活奖励、基准奖励和你的新版本。这里只重新计分，不会训练策略；保存的新版本可在 L27 独立训练。")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.trajectory_paths = []
        for index in range(2):
            row = QHBoxLayout()
            field = QLineEdit()
            field.setPlaceholderText(f"轨迹{index+1}" + ("（可选，用于比较不同策略）" if index else " / trajectory.csv"))
            button = QPushButton("选择轨迹")
            button.clicked.connect(lambda checked=False, field=field: self._choose(field))
            row.addWidget(field, 1)
            row.addWidget(button)
            layout.addLayout(row)
            self.trajectory_paths.append(field)
        form = QFormLayout()
        self.reward_name = QLineEdit("balanced-effort-x10-v1")
        form.addRow("新奖励名称", self.reward_name)
        self.version = QSpinBox()
        self.version.setRange(1, 10000)
        form.addRow("版本号", self.version)
        self.weights = {}
        for key, caption, value in (("alive", "每步存活奖励", 1), ("angle", "角度惩罚权重", .6),
                                    ("position", "位置惩罚权重", .2), ("effort", "用力惩罚权重", .2)):
            widget = QDoubleSpinBox()
            widget.setDecimals(4)
            widget.setRange(0, 1000)
            widget.setSingleStep(.02)
            widget.setValue(value)
            self.weights[key] = widget
            form.addRow(caption, widget)
        layout.addLayout(form)
        formula = QLabel("r = 存活 − 角度权重×(θ/12°)² − 位置权重×(x/2.4m)² − 用力权重×(F/10N)²\n使用真实动作后状态和执行器实际推力；代码内部角度为 rad。基准用力权重为0.02。")
        formula.setWordWrap(True)
        layout.addWidget(formula)
        actions = QHBoxLayout()
        self.analyze_button = QPushButton("重新计分并比较")
        self.analyze_button.clicked.connect(self.analyze)
        self.save_button = QPushButton("保存版本供 L27 训练")
        self.save_button.clicked.connect(self.save_configuration)
        self.open_button = QPushButton("打开曲线报告")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_report)
        for button in (self.analyze_button, self.save_button, self.open_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["轨迹", "奖励版本", "存活", "角度", "位置", "用力", "总分"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.setMinimumHeight(185)
        layout.addWidget(self.table)
        self.status = QLabel("先预测：把用力惩罚增大10倍，哪条轨迹的总分变化更多？")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def _choose(self, field):
        path, _ = QFileDialog.getOpenFileName(self, "选择已保存轨迹", str(self.data_dir), "轨迹 (*.csv)")
        if path:
            field.setText(path)

    def configuration(self):
        return normalize_reward_config({"schema_version": 1, "reward_id": self.reward_name.text().strip(),
            "version": self.version.value(), **{key: widget.value() for key, widget in self.weights.items()}})

    def _destination(self, kind):
        return self.data_dir / "reward_experiments" / (datetime.now().strftime("%Y%m%d-%H%M%S")+f"-{kind}-{uuid4().hex[:8]}")

    def save_configuration(self):
        try:
            config = self.configuration()
            path = self._destination("configuration") / "reward.json"
            atomic_json(path, config)
            self.status.setText(f"奖励版本已保存：{path}\nL27训练页面可选择此声明；改变奖励需要独立新训。")
            self.configurationSaved.emit(str(path))
            return path
        except (ValueError, OSError) as exc:
            self._failed(str(exc))
            return None

    def analyze(self):
        if self._worker is not None:
            return False
        try:
            config = self.configuration()
            paths = [Path(field.text().strip()) for field in self.trajectory_paths if field.text().strip()]
            if not paths or any(not path.is_file() for path in paths):
                raise ValueError("请先选择至少一份已保存的轨迹CSV")
            configs = [resolve_reward_config("survival-v1"), resolve_reward_config("balanced-v1"), config]
            worker = _RewardWorker(paths, configs, self._destination("analysis"), self)
            worker.succeeded.connect(self._succeeded)
            worker.failed.connect(self._failed)
            worker.finished.connect(self._finished)
            self._worker = worker
            self.analyze_button.setEnabled(False)
            self.status.setText("正在按同一份实际记录重算奖励…")
            worker.start()
            return True
        except (ValueError, OSError) as exc:
            self._failed(str(exc))
            return False

    def _succeeded(self, result):
        self.table.setRowCount(len(result["report"]["results"]))
        for index, item in enumerate(result["report"]["results"]):
            cells = [item["trajectory_index"], item["reward_config"]["reward_id"],
                     *[f"{item['parts'][key]:.4g}" for key in ("survival", "angle", "position", "effort")],
                     f"{item['return']:.4g}"]
            for column, value in enumerate(cells):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self._report_html = Path(result["html"])
        self.open_button.setEnabled(True)
        self.status.setText("分量表与曲线已保存。轨迹和策略未改变；请解释分数变化，不把重新计分当作重新学习。")
        self.completed.emit(result)

    def _failed(self, message):
        self.status.setText(message)
        self.error.emit(message)

    def _finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        self.analyze_button.setEnabled(True)

    def open_report(self):
        if self._report_html:
            return QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_html)))
        return False

    def shutdown(self):
        return self._worker is None
