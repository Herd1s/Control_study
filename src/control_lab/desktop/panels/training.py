"""Qt orchestration only: all policy imports and work live in an external Python."""
from datetime import datetime
import codecs
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QComboBox, QPlainTextEdit, QFileDialog, QProgressBar, QCheckBox,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QDialog,
)


class _CatalogWorker(QThread):
    ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog = catalog

    def run(self):
        try:
            self.ready.emit(self.catalog.refresh())
        except Exception as exc:
            self.failed.emit(str(exc))


class ModelCatalogDialog(QDialog):
    selected = Signal(str, str)
    reportRequested = Signal(str)

    def __init__(self, catalog, parent=None):
        super().__init__(parent)
        self.catalog, self._worker, self.entries = catalog, None, []
        self.setWindowTitle("本地模型目录")
        self.resize(1080, 730)
        layout = QVBoxLayout(self)
        intro = QLabel("显示真实模型与评价来源；读取时核验模型/元数据hash，不载入神经网络。副本保留各自路径，失败或损坏的包不隐藏。")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        actions = QHBoxLayout()
        self.refresh_button = QPushButton("刷新并核验")
        self.refresh_button.clicked.connect(self.refresh)
        self.import_model_button = QPushButton("导入模型目录")
        self.import_model_button.clicked.connect(self.import_models)
        self.import_report_button = QPushButton("关联评价report.json")
        self.import_report_button.clicked.connect(self.import_report)
        for button in (self.refresh_button, self.import_model_button, self.import_report_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["状态", "模型hash", "seed", "实际/请求步数", "奖励版本", "来源", "已关联评价", "路径"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(150)
        layout.addWidget(self.details)
        self.reports = QComboBox()
        layout.addWidget(self.reports)
        self.status = QLabel("正在读取本地模型索引…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.use_button = QPushButton("选择模型与验证出处")
        self.use_button.clicked.connect(self.use_selection)
        self.open_report_button = QPushButton("打开所选评价轨迹")
        self.open_report_button.clicked.connect(self.open_report)
        row.addWidget(self.use_button)
        row.addWidget(self.open_report_button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        if self._worker:
            return False
        self.status.setText("正在核验本地模型字节与评价来源…")
        for button in (self.refresh_button, self.import_model_button, self.import_report_button, self.use_button, self.open_report_button):
            button.setEnabled(False)
        self._worker = _CatalogWorker(self.catalog, self)
        self._worker.ready.connect(self._loaded)
        self._worker.failed.connect(self.status.setText)
        self._worker.finished.connect(self._scan_finished)
        self._worker.start()
        return True

    def _loaded(self, index):
        self.entries = index["entries"]
        self.table.setRowCount(len(self.entries))
        for row, item in enumerate(self.entries):
            values = (item.get("status", "损坏/缺失") if item["valid"] else "校验失败", item.get("model_sha256", "")[:12],
                item.get("seed", "—"), f"{item.get('actual_steps','—')} / {item.get('requested_steps','—')}",
                item.get("reward_id", "—"), "继续训练" if item.get("lineage") else "新训练/导入",
                len(item["reports"]), item["path"])
            for col, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setToolTip(item.get("model_sha256", "") if col == 1 else str(value))
                self.table.setItem(row, col, cell)
        warnings = index.get("warnings", [])
        self.status.setText(f"已索引{len(self.entries)}个模型包。"+(f" {len(warnings)}份评价无法关联，已记录在catalog.json。" if warnings else "")+index.get("notice", ""))
        if self.entries:
            self.table.selectRow(0)

    def _scan_finished(self):
        worker, self._worker = self._worker, None
        worker.deleteLater()
        for button in (self.refresh_button, self.import_model_button, self.import_report_button):
            button.setEnabled(True)
        self._selection_changed()

    def _selection_changed(self):
        row = self.table.currentRow()
        self.reports.clear()
        item = self.entries[row] if 0 <= row < len(self.entries) else None
        self.use_button.setEnabled(bool(item and item["valid"] and not self._worker))
        self.open_report_button.setEnabled(bool(item and item["reports"] and not self._worker))
        if not item:
            return
        self.details.setPlainText(json.dumps(item, ensure_ascii=False, indent=2))
        self.reports.addItem("仅选择模型（暂不指定冻结验证报告）", None)
        for report in item["reports"]:
            aggregate = report.get("aggregate") or {}
            self.reports.addItem(f"{report['split']} · {report['status']} · {aggregate.get('completed_episodes',0)}/{aggregate.get('episodes',0)} · {report['path']}", report)
        preferred = next((index+1 for index, report in enumerate(item["reports"]) if report["usable_validation"]), 0)
        self.reports.setCurrentIndex(preferred)

    def import_models(self):
        path = QFileDialog.getExistingDirectory(self, "选择模型包或包含多个模型包的目录", str(self.catalog.data_dir))
        if path:
            self.catalog.add_model_root(path)
            self.refresh()

    def import_report(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择实际评价report.json", str(self.catalog.data_dir), "评价报告 (*.json)")
        if path:
            self.catalog.add_report_root(path)
            self.refresh()

    def use_selection(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.entries) or not self.entries[row]["valid"] or self._worker:
            return False
        report = self.reports.currentData()
        self.selected.emit(self.entries[row]["path"], report["path"] if report and report["usable_validation"] else "")
        self.accept()
        return True

    def open_report(self):
        report = self.reports.currentData()
        if report:
            self.reportRequested.emit(report["path"])

    def reject(self):
        if not self._worker:
            super().reject()

    def closeEvent(self, event):
        event.ignore() if self._worker else event.accept()


class TrainingPanel(QFrame):
    operationStarted = Signal(str)
    completed = Signal(dict)
    error = Signal(str)
    replayState = Signal(list, float)
    reportRequested = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.setObjectName("surface")
        self.data_dir = Path(data_dir).resolve()
        self.settings_path = self.data_dir / "training" / "settings.json"
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self.process.started.connect(lambda: self.operationStarted.emit(self._operation or ""))
        self._doctor_watchdog = QTimer(self)
        self._doctor_watchdog.setSingleShot(True)
        self._doctor_watchdog.setInterval(30000)
        self._doctor_watchdog.timeout.connect(self._doctor_timeout)
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._operation = None
        self._stop_file = None
        self._last_result = None
        self._reported_error = False
        self._lesson_id = "L26"
        self._reward_configs = {}
        from control_lab.rl.tasks import TaskStore
        from control_lab.rl.catalog import ModelCatalog
        self.task_store = TaskStore(self.data_dir)
        self.catalog = ModelCatalog(self.data_dir)
        self._catalog_dialog = None
        self._task_id = None
        self._task_running = False
        self._task_offset = 0
        self._task_started_emitted = False
        self._leave_training = False
        self._task_ticks = 0
        self._build_ui()
        self._load_settings()
        self.set_lesson(self._lesson_id)
        self._task_timer = QTimer(self)
        self._task_timer.setInterval(200)
        self._task_timer.timeout.connect(self._poll_task)
        self._task_timer.start()
        self.refresh_tasks(recover=True)

    @property
    def is_running(self):
        return self._task_running or self.process.state() != QProcess.ProcessState.NotRunning

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(12)
        self.title = QLabel("强化学习实验")
        self.title.setStyleSheet("font-size:20px; font-weight:600")
        layout.addWidget(self.title)
        description = QLabel("先检查独立训练环境，再训练、评价和回放。训练进程不会阻塞课堂界面。")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.environment_group = QWidget()
        row = QHBoxLayout(self.environment_group)
        row.setContentsMargins(0, 0, 0, 0)
        self.python_path = QLineEdit()
        self.python_path.setPlaceholderText("选择已配置的独立 Python 解释器")
        self.python_path.setAccessibleName("独立强化学习Python解释器")
        self.browse_python = QPushButton("选择解释器")
        self.browse_python.clicked.connect(self._choose_python)
        self.doctor_button = QPushButton("检查环境")
        self.doctor_button.clicked.connect(self.check_environment)
        row.addWidget(self.python_path, 1)
        row.addWidget(self.browse_python)
        row.addWidget(self.doctor_button)
        layout.addWidget(self.environment_group)
        self.contract_summary = QLabel("")
        self.contract_summary.setWordWrap(True)
        self.contract_summary.hide()
        layout.addWidget(self.contract_summary)
        self.smoke_button = QPushButton("运行 256 步通路检查")
        self.smoke_button.clicked.connect(self.start_smoke)
        layout.addWidget(self.smoke_button)
        self.baseline_button = QPushButton("保存未训练策略 · 5 回合起点")
        self.baseline_button.clicked.connect(self.create_baseline)
        layout.addWidget(self.baseline_button)
        self.training_group = QWidget()
        row = QHBoxLayout(self.training_group)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("训练步数"))
        self.steps = QSpinBox()
        self.steps.setRange(256, 10_240_000)
        self.steps.setSingleStep(256)
        self.steps.setValue(25600)
        row.addWidget(self.steps)
        row.addWidget(QLabel("独立训练种子"))
        self.seed = QSpinBox()
        self.seed.setRange(0, 1_000_000)
        row.addWidget(self.seed)
        self.reward = QComboBox()
        self.reward.addItem("存活奖励", "survival-v1")
        self.reward.addItem("角度 / 位置 / 用力", "balanced-v1")
        row.addWidget(self.reward)
        self.train_button = QPushButton("开始训练")
        self.train_button.setObjectName("primary")
        self.train_button.clicked.connect(self.start_training)
        row.addWidget(self.train_button)
        layout.addWidget(self.training_group)
        self.reward_config_group = QWidget()
        reward_row = QHBoxLayout(self.reward_config_group)
        reward_row.setContentsMargins(0, 0, 0, 0)
        self.load_reward_button = QPushButton("载入 L24 奖励版本")
        self.load_reward_button.clicked.connect(self._choose_reward)
        reward_row.addWidget(self.load_reward_button)
        self.reward_description = QLabel("内置版本；改变奖励需独立新训，不能接着旧奖励训练。")
        self.reward_description.setWordWrap(True)
        reward_row.addWidget(self.reward_description, 1)
        self.reward.currentIndexChanged.connect(self._reward_changed)
        layout.addWidget(self.reward_config_group)
        self.model_group = QWidget()
        row = QHBoxLayout(self.model_group)
        row.setContentsMargins(0, 0, 0, 0)
        self.model_path = QLineEdit()
        self.model_path.setPlaceholderText("训练完成后自动填入模型包目录，也可选择已有模型")
        self.model_path.setAccessibleName("强化学习模型包目录")
        self.browse_model = QPushButton("选择模型包")
        self.browse_model.clicked.connect(self._choose_model)
        row.addWidget(self.model_path, 1)
        row.addWidget(self.browse_model)
        layout.addWidget(self.model_group)
        self.catalog_button = QPushButton("本地模型目录 · 比较来源与选择验证报告")
        self.catalog_button.clicked.connect(self.open_catalog)
        layout.addWidget(self.catalog_button)
        self.model_summary = QLabel("选择模型包后显示训练seed、预算、奖励与模型指纹。")
        self.model_summary.setWordWrap(True)
        layout.addWidget(self.model_summary)
        self.evaluation_group = QWidget()
        evaluation_layout = QVBoxLayout(self.evaluation_group)
        evaluation_layout.setContentsMargins(0, 0, 0, 0)
        self.held_out = QCheckBox("冻结后的保留测试（需要完整验证报告）")
        self.held_out.toggled.connect(self._held_out_changed)
        evaluation_layout.addWidget(self.held_out)
        frozen_row = QHBoxLayout()
        self.validation_report_path = QLineEdit()
        self.validation_report_path.setPlaceholderText("选择此模型的20回合验证 report.json")
        self.browse_validation = QPushButton("选择验证报告")
        self.browse_validation.clicked.connect(self._choose_validation)
        frozen_row.addWidget(self.validation_report_path, 1)
        frozen_row.addWidget(self.browse_validation)
        evaluation_layout.addLayout(frozen_row)
        self.validation_report_path.hide()
        self.browse_validation.hide()
        layout.addWidget(self.evaluation_group)
        self.actions_group = QWidget()
        row = QHBoxLayout(self.actions_group)
        row.setContentsMargins(0, 0, 0, 0)
        self.resume_button = QPushButton("继续训练")
        self.resume_button.clicked.connect(lambda: self.start_training(resume=True))
        self.evaluate_button = QPushButton("独立验证 · 20 回合")
        self.evaluate_button.clicked.connect(self.evaluate_model)
        self.replay_button = QPushButton("回放验证用例")
        self.replay_button.clicked.connect(self.replay_model)
        self.replay_case = QSpinBox()
        self.replay_case.setRange(1, 20)
        self.replay_case.setToolTip("选择验证用例1–20；不会读取保留测试集")
        self.stop_button = QPushButton("停止并保存")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        self.compare_button = QPushButton("比较评价报告")
        self.compare_button.clicked.connect(self.choose_comparison_reports)
        for widget in (self.resume_button, self.evaluate_button, self.replay_button, self.replay_case, self.stop_button):
            row.addWidget(widget)
        row.addWidget(self.compare_button)
        layout.addWidget(self.actions_group)
        self.report_button = QPushButton("打开评价轨迹 / 添加同条件对照")
        self.report_button.clicked.connect(self.choose_report_replay)
        layout.addWidget(self.report_button)
        self.comparison_table = QTableWidget(0, 8)
        self.comparison_table.setHorizontalHeaderLabels(["方法 / 指纹", "完成回合", "平均步数", "最短步数", "角度RMS rad", "最大位移 m", "力RMS N", "饱和比例"])
        self.comparison_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comparison_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.comparison_table.setMinimumHeight(130)
        self.comparison_table.hide()
        layout.addWidget(self.comparison_table)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.status = QLabel("训练可完成、可保存与策略已经稳定平衡是两项不同的验证。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.log.setMinimumHeight(150)
        layout.addWidget(self.log, 1)
        self.log.hide()
        self.log_toggle = QPushButton("查看实验日志")
        self.log_toggle.clicked.connect(lambda: self.log.setVisible(not self.log.isVisible()))
        layout.addWidget(self.log_toggle)
        self.tasks_group = QWidget()
        tasks_layout = QVBoxLayout(self.tasks_group)
        tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.task_selector = QComboBox()
        self.task_selector.setToolTip("持久化登记的训练任务；关闭窗口保留后可在这里恢复监控。")
        tasks_layout.addWidget(self.task_selector)
        task_actions = QHBoxLayout()
        self.monitor_button = QPushButton("查看 / 恢复监控")
        self.monitor_button.clicked.connect(self.monitor_selected_task)
        self.stop_task_button = QPushButton("停止所选任务并保存")
        self.stop_task_button.clicked.connect(self.stop_selected_task)
        task_actions.addWidget(self.monitor_button)
        task_actions.addWidget(self.stop_task_button)
        tasks_layout.addLayout(task_actions)
        self.task_summary = QLabel("")
        self.task_summary.setWordWrap(True)
        tasks_layout.addWidget(self.task_summary)
        layout.addWidget(self.tasks_group)

    def _load_settings(self):
        if self.settings_path.is_file():
            try:
                settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
                self.python_path.setText(settings.get("python", ""))
                self.model_path.setText(settings.get("last_model", ""))
                for path in settings.get("reward_configs", []):
                    self.set_reward_config(path, persist=False)
                if self.model_path.text():
                    self._display_model()
                return
            except (ValueError, OSError):
                self.log.appendPlainText("解释器设置无法读取，请重新选择；课程和作业仍可使用。")
        if not getattr(sys, "frozen", False):
            project = Path(__file__).resolve().parents[4]
            candidate = project / ".venv-rl" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
            if candidate.is_file():
                self.python_path.setText(str(candidate))

    def _save_settings(self):
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.settings_path.with_name("settings-" + uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps({"python": self.python_path.text().strip(),
                "last_model": self.model_path.text().strip(),
                "reward_configs": list(self._reward_configs.values())}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.settings_path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _choose_python(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择独立训练环境的 Python", self.python_path.text(), "Python (python.exe python);;所有文件 (*)")
        if path:
            self.python_path.setText(path)
            self._save_settings()

    def _choose_model(self):
        path = QFileDialog.getExistingDirectory(self, "选择包含 metadata.json 和 policy.zip 的模型包", self.model_path.text())
        if path:
            self.model_path.setText(path)
            self._display_model()
            self._save_settings()

    def _display_model(self):
        path = self.model_path.text().strip()
        if path:
            try:
                from control_lab.rl.artifacts import validate_artifact
                metadata = validate_artifact(path)
                self.catalog.add_model_root(path)
                from control_lab.rl.rewards import reward_config_from_contract
                config = reward_config_from_contract(metadata["environment"])
                if config["reward_id"] not in ("survival-v1", "balanced-v1"):
                    from control_lab.rl.artifacts import atomic_json
                    config_path = self.data_dir / "training/model_reward_configs" / (metadata["metadata_sha256"]+".json")
                    if not config_path.exists():
                        atomic_json(config_path, config)
                    self.set_reward_config(config_path, persist=False)
                index = self.reward.findData(metadata.get("environment", {}).get("reward_id"))
                if index >= 0:
                    self.reward.setCurrentIndex(index)
                training = metadata["training"]
                self.model_summary.setText(f"seed {training['seed']} · 已训练 {training['actual_timesteps']:,} 步 · "
                    f"奖励 {config['reward_id']} · {metadata['status']}\n模型 {metadata['model_sha256'][:16]}…；观察归一化：{metadata['observation_normalization']}")
            except (OSError, ValueError, KeyError) as exc:
                self._show_error(f"模型元数据或hash校验失败：{exc}")

    def _choose_reward(self):
        path, _ = QFileDialog.getOpenFileName(self, "载入L24保存的奖励版本", str(self.data_dir), "奖励声明 (*.json)")
        if path:
            self.set_reward_config(path)

    def set_reward_config(self, path, *, persist=True):
        try:
            from control_lab.rl.rewards import load_reward_config
            config = load_reward_config(path)
            name = config["reward_id"]
            if name in self._reward_configs and load_reward_config(self._reward_configs[name]) != config:
                raise ValueError("同名奖励已经保存了不同权重，请在L24改用新的版本名")
            self._reward_configs[name] = str(Path(path).resolve())
            index = self.reward.findData(name)
            if index < 0:
                self.reward.addItem(name, name)
                index = self.reward.count()-1
            self.reward.setCurrentIndex(index)
            self._reward_changed()
            if persist:
                self._save_settings()
            return True
        except (ValueError, OSError) as exc:
            self._show_error(f"奖励版本未载入：{exc}")
            return False

    def _reward_changed(self):
        name = self.reward.currentData()
        self.reward_description.setText(f"当前训练奖励：{name}。修改奖励请独立新训；继续训练须与模型声明完全一致。")

    def _held_out_changed(self, enabled):
        self.validation_report_path.setVisible(enabled)
        self.browse_validation.setVisible(enabled)
        self.evaluate_button.setText("冻结保留测试 · 20 回合" if enabled else "独立验证 · 20 回合")

    def _choose_validation(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择完整验证report.json", str(self.data_dir), "评价报告 (*.json)")
        if path:
            self.validation_report_path.setText(path)
            self.catalog.add_report_root(path)

    def _model(self):
        path = Path(self.model_path.text().strip()).expanduser()
        if not (path / "metadata.json").is_file() or not (path / "policy.zip").is_file():
            self._show_error("请选择包含 metadata.json 和 policy.zip 的完整模型包。")
            return None
        return path.resolve()

    def _new_run(self, kind):
        name = f"{datetime.now():%Y%m%d_%H%M%S}_{kind}_seed{self.seed.value()}_{uuid4().hex[:8]}"
        return self.data_dir / "training" / "runs" / name

    def _launch(self, operation, arguments):
        if self.is_running:
            self._show_error("已有训练或评价正在运行，请先正常停止。")
            return False
        interpreter = Path(self.python_path.text().strip()).expanduser()
        if not interpreter.is_file():
            self._show_error("尚未配置独立训练环境。请选择安装了 ControlLab、CPU PyTorch 和 Stable-Baselines3 的 Python；其他课程仍可使用。")
            return False
        self._save_settings()
        self._operation = operation
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._last_result = None
        self._reported_error = False
        self.log.clear()
        self.progress.setValue(0)
        self.status.setText("正在启动独立进程……")
        self._set_running(True)
        if operation == "train":
            return self._launch_training_task(interpreter, arguments)
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        self.process.setProcessEnvironment(environment)
        self.process.setProgram(str(interpreter.resolve()))
        self.process.setArguments(["-m", "control_lab.rl.service", operation, *map(str, arguments)])
        self.process.start()
        if operation == "doctor":
            self._doctor_watchdog.start()
        return True

    def _prepare_stop(self):
        directory = self.data_dir / "training" / "requests"
        directory.mkdir(parents=True, exist_ok=True)
        self._stop_file = directory / f"stop-{uuid4().hex}.txt"

    def check_environment(self):
        if self.is_running:
            return False
        self._stop_file = None
        return self._launch("doctor", [])

    def start_training(self, checked=False, *, resume=False):
        if self.is_running:
            return False
        model = self._model() if resume else None
        if resume and model is None:
            return False
        self._prepare_stop()
        self._run_dir = self._new_run("resume" if resume else "train")
        arguments = ["--output-dir", self._run_dir, "--steps", self.steps.value(),
                     "--seed", self.seed.value(), "--reward", self.reward.currentData(),
                     "--stop-file", self._stop_file]
        if model:
            arguments += ["--resume-from", model]
        if self.reward.currentData() in self._reward_configs:
            arguments += ["--reward-config", self._reward_configs[self.reward.currentData()]]
            # The explicit file carries custom version names, while --reward retains builtin CLI choices.
            arguments[arguments.index("--reward")+1] = "survival-v1"
        return self._launch("train", arguments)

    def start_smoke(self):
        if self.is_running:
            return False
        self._prepare_stop()
        self._run_dir = self._new_run("smoke256")
        return self._launch("train", ["--output-dir", self._run_dir, "--steps", 256, "--seed", 0,
            "--reward", "survival-v1", "--stop-file", self._stop_file])

    def create_baseline(self):
        if self.is_running:
            return False
        self._prepare_stop()
        self._run_dir = self._new_run("untrained")
        return self._launch("baseline", ["--output-dir", self._run_dir, "--seed", self.seed.value(),
                                         "--stop-file", self._stop_file])

    def evaluate_model(self):
        if self.is_running:
            return False
        model = self._model()
        if model is None:
            return False
        self._prepare_stop()
        split = "held_out" if self.held_out.isChecked() else "validation"
        arguments = ["--model-dir", model, "--split", split, "--stop-file", self._stop_file]
        if split == "held_out":
            path = Path(self.validation_report_path.text().strip())
            if not path.is_file():
                self._show_error("请先选择此模型完整的验证report.json，再运行保留测试。")
                return False
            arguments += ["--validation-report", path]
        self._run_dir = self._new_run(split)
        arguments += ["--output-dir", self._run_dir]
        return self._launch("evaluate", arguments)

    def replay_model(self):
        if self.is_running:
            return False
        model = self._model()
        if model is None:
            return False
        self._prepare_stop()
        return self._launch("replay", ["--model-dir", model, "--case-index", self.replay_case.value()-1,
                                      "--stop-file", self._stop_file])

    def stop(self):
        if not self.is_running:
            return
        if self._task_running and self._task_id:
            self.task_store.request_stop(self._task_id)
            self.status.setText("已请求独立训练任务停止，正在保存模型…")
            self.stop_button.setEnabled(False)
            return
        if self._stop_file is not None:
            self._stop_file.write_text("stop requested", encoding="utf-8")
            self.status.setText("已请求停止，正在完成当前步骤并保存……")
            self.stop_button.setEnabled(False)
        else:
            self.status.setText("环境检查即将结束，请稍候……")

    def _set_running(self, running):
        for widget in (self.train_button, self.resume_button, self.evaluate_button, self.replay_button,
                       self.doctor_button, self.browse_python, self.python_path, self.browse_model,
                       self.model_path, self.steps, self.seed, self.reward, self.replay_case, self.compare_button):
            widget.setEnabled(not running)
        for widget in (self.smoke_button, self.load_reward_button, self.held_out,
                       self.validation_report_path, self.browse_validation, self.baseline_button, self.catalog_button):
            widget.setEnabled(not running)
        self.stop_button.setEnabled(running and self._operation != "doctor")
        self._apply_lesson_visibility()

    def _read_output(self):
        self._buffer += self._decoder.decode(bytes(self.process.readAllStandardOutput()))
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._consume_line(line.strip())

    def _consume_line(self, line):
        if not line:
            return
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("not an event")
        except ValueError:
            self.log.appendPlainText(line)
            return
        kind = message.get("type")
        if kind == "replay_state":
            state = message.get("state")
            force = message.get("force", 0)
            if (isinstance(state, list) and len(state) == 4 and
                all(type(value) in (int, float) and math.isfinite(value) for value in [*state, force])):
                self.replayState.emit(state, float(force))
            else:
                self._show_error("回放进程返回了无效状态，未更新画面。")
                return
            self.status.setText(f"验证用例 {message.get('scenario', '')} · 第 {message.get('step_count', 0)} 步")
            return
        self.log.appendPlainText(json.dumps(message, ensure_ascii=False))
        if kind == "progress":
            count = int(message.get("additional_steps", message.get("step_count", 0)))
            budget = int(message.get("requested_steps", self.steps.value()))
            self.progress.setValue(min(100, int(100*count/max(1,budget))))
            self.status.setText(f"正在尝试：{count:,} / {budget:,} 步")
        elif kind == "checkpoint":
            self.status.setText(f"已保存第 {message.get('step_count', 0):,} 步检查点")
        elif kind in ("completed", "stopped", "evaluation", "replay_completed", "doctor", "baseline"):
            self._last_result = dict(message, operation=self._operation)
            if kind in ("completed", "stopped") and self._operation == "train" and message.get("path"):
                self.model_path.setText(message["path"])
                self._display_model()
                self._save_settings()
            if kind == "evaluation":
                try:
                    self.catalog.add_report_root(Path(message["path"])/"report.json")
                except (OSError, ValueError):
                    pass
                aggregate = message.get("aggregate", {})
                self.status.setText(f"验证完成：{aggregate.get('completed_episodes', 0)} / {aggregate.get('episodes', 0)} 回合达到时长上限。")
            elif kind == "doctor":
                self.status.setText("独立训练环境检查通过，可以开始实验。")
                contract = message.get("contract_examples", {})
                if contract:
                    examples = contract["examples"]
                    zero, reference = examples["zero_force"], examples["reference_feedback"]
                    self.contract_summary.setText("4维观测 x/v/θ/ω，单位 m、m/s、rad、rad/s，dt=0.02s。\n"
                        "动作 −1 / 0 / 1 实际映射 −10 / 0 / 10 N，仅一次缩放。\n"
                        f"零推力：{zero['steps']}步，terminated={zero['terminated']}，truncated={zero['truncated']}。\n"
                        f"参考控制：{reference['steps']}步，terminated={reference['terminated']}，truncated={reference['truncated']}。\n"
                        "这两个例子没有训练PPO；接下来可运行256步通路检查，并试正常停止。")
                    self.contract_summary.show()
            elif kind == "stopped":
                self.status.setText("已停止；已写入的数据和模型保留。")
            elif kind == "completed":
                self.progress.setValue(100)
                self.status.setText("模型已保存。请独立验证，再判断是否学会平衡。")
            elif kind == "baseline":
                self.model_path.setText(message["path"])
                self._display_model()
                self._save_settings()
                self.status.setText("未训练策略和5回合起点已保存；训练步数为0。请保留这份记录再开始训练。")
            else:
                self.status.setText("回放结束；这是指定验证用例的真实策略轨迹。")
        elif kind == "error":
            self._reported_error = True
            self._show_error(message.get("message", "外部进程发生错误"))

    def _finished(self, exit_code, exit_status):
        self._doctor_watchdog.stop()
        self._read_output()
        self._buffer += self._decoder.decode(b"", final=True)
        if self._buffer.strip():
            self._consume_line(self._buffer.strip())
            self._buffer = ""
        self._set_running(False)
        if exit_code != 0 and not self._reported_error:
            self._show_error("独立进程退出失败。请查看下方日志，核对解释器和训练依赖；其他课程仍可使用。")
        elif self._last_result is not None:
            self.completed.emit(self._last_result)
        elif not self._reported_error:
            self._show_error("外部进程结束但没有返回结果，请查看日志。")

    def _process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._reported_error = True
            self._set_running(False)
            self._show_error("无法启动所选 Python 解释器，请检查路径和权限。")

    def _doctor_timeout(self):
        if self.is_running and self._operation == "doctor":
            self._reported_error = True
            self.process.kill()  # Only the read-only environment probe; training uses cooperative stop.
            self._show_error("训练环境检查超过30秒，已结束检查。请查看日志并核对解释器；其他课程仍可使用。")

    def _show_error(self, message):
        self.status.setText(message)
        self.log.show()
        self.error.emit(message)

    def set_lesson(self, lesson_id):
        self._lesson_id = lesson_id
        titles = {"L25":"检查强化学习环境", "L26":"训练第一个策略", "L27":"保存、继续训练与回放",
                  "L28":"用统一协议比较方法"}
        self.title.setText(titles.get(lesson_id, "强化学习实验"))
        self._apply_lesson_visibility()

    def _apply_lesson_visibility(self):
        lesson = self._lesson_id
        self.training_group.setVisible(lesson in ("L26", "L27"))
        self.reward_config_group.setVisible(lesson == "L27")
        self.smoke_button.setVisible(lesson == "L25")
        self.baseline_button.setVisible(lesson == "L26")
        self.model_summary.setVisible(lesson in ("L26", "L27", "L28"))
        self.evaluation_group.setVisible(lesson == "L28")
        if lesson != "L28" and self.held_out.isChecked():
            self.held_out.setChecked(False)
        self.model_group.setVisible(lesson in ("L27", "L28"))
        self.catalog_button.setVisible(lesson in ("L26", "L27", "L28"))
        self.actions_group.setVisible(lesson != "L25" or self.is_running)
        self.resume_button.setVisible(lesson == "L27")
        self.evaluate_button.setVisible(lesson in ("L26", "L27", "L28"))
        self.replay_button.setVisible(lesson in ("L27", "L28"))
        self.replay_case.setVisible(lesson in ("L27", "L28"))
        self.compare_button.setVisible(lesson == "L28")
        self.report_button.setVisible(lesson in ("L27", "L28"))
        self.stop_button.setVisible(self.is_running or lesson != "L25")
        self.comparison_table.setVisible(lesson == "L28" and self.comparison_table.rowCount() > 0)

    def choose_comparison_reports(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择至少两份同协议评价report.json", str(self.data_dir),
                                              "评价报告 (*.json)")
        if paths:
            return self.compare_report_files(paths)
        return None

    def choose_report_replay(self):
        path, _ = QFileDialog.getOpenFileName(self, "打开验证或保留集report.json的只读轨迹", str(self.data_dir), "评价报告 (*.json)")
        if path:
            self.reportRequested.emit(path)
        return path

    def compare_report_files(self, paths):
        if self.is_running:
            return None
        try:
            from control_lab.evaluation import compare_reports
            reports = [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]
            comparison = compare_reports(reports)
            folder = self.data_dir / "training" / "comparisons" / f"{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"
            folder.mkdir(parents=True, exist_ok=False)
            destination = folder / "comparison.json"
            with destination.open("x", encoding="utf-8") as handle:
                json.dump(comparison, handle, ensure_ascii=False, indent=2, allow_nan=False)
            self.comparison_table.setRowCount(len(comparison["methods"]))
            for index, method in enumerate(comparison["methods"]):
                stats = method["aggregate"]
                episodes = method["episodes"]
                mean = lambda key: sum(float(e[key] or 0) for e in episodes)/len(episodes)
                cells = (method["controller"]+" / "+str(method.get("controller_sha256", ""))[:10],
                         f"{stats['completed_episodes']} / {stats['episodes']}",
                         f"{stats['mean_steps']:.2f}", str(stats["worst_steps"]),
                         f"{mean('rms_theta_rad'):.4g}", f"{max(e['max_abs_x_m'] for e in episodes):.4g}",
                         f"{mean('rms_actuator_force_n'):.4g}", f"{mean('saturation_fraction'):.1%}")
                for column, value in enumerate(cells):
                    self.comparison_table.setItem(index, column, QTableWidgetItem(str(value)))
            self.comparison_table.show()
            split = comparison["comparison_contract"]["split"]
            self.status.setText(f"同协议对照已保存（{split}）。先比较完成与失败，再解释误差；结果不代表任意条件下的优劣。")
            result = {"type": "comparison", "operation": "compare", "status": "completed",
                      "path": str(destination), "methods": len(comparison["methods"]), "split": split}
            self.completed.emit(result)
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._show_error(f"无法比较这些报告：{exc}")
            return None

    def open_catalog(self):
        if self.is_running:
            return None
        if self._catalog_dialog is not None and self._catalog_dialog._worker:
            self._catalog_dialog.show()
            return self._catalog_dialog
        dialog = ModelCatalogDialog(self.catalog, self)
        dialog.selected.connect(self._catalog_selected)
        dialog.reportRequested.connect(self.reportRequested)
        self._catalog_dialog = dialog
        dialog.show()
        return dialog

    def _catalog_selected(self, model_path, validation_report):
        if self.is_running:
            return
        self.model_path.setText(model_path)
        self.validation_report_path.setText(validation_report)
        self._display_model()
        self._save_settings()

    def _launch_training_task(self, interpreter, arguments):
        import argparse
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--steps", type=int, required=True)
        parser.add_argument("--seed", type=int, required=True)
        parser.add_argument("--reward", default="survival-v1")
        parser.add_argument("--reward-config", type=Path)
        parser.add_argument("--resume-from", type=Path)
        parser.add_argument("--stop-file", type=Path)
        try:
            args = parser.parse_args(list(map(str, arguments)))
            from control_lab.rl.rewards import load_reward_config
            reward = load_reward_config(args.reward_config) if args.reward_config else None
            config = {"output_dir": args.output_dir, "total_timesteps": args.steps, "seed": args.seed,
                      "reward_id": reward["reward_id"] if reward else args.reward,
                      "reward_config": reward, "resume_from": args.resume_from}
            task_id = self.task_store.launch(interpreter, config)
            self._leave_training = False
            self._attach_task(task_id)
            self.refresh_tasks()
            return True
        except (OSError, ValueError) as exc:
            self._set_running(False)
            self._show_error(f"独立训练任务未启动：{exc}")
            return False

    def _attach_task(self, task_id):
        from control_lab.rl.tasks import ACTIVE
        state = self.task_store.read(task_id)
        self._task_id = task_id
        self._task_running = state["status"] in ACTIVE
        self._task_emit_completion = self._task_running
        self._operation = "train"
        self._task_offset = 0
        self._task_started_emitted = False
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._last_result = None
        self._reported_error = False
        self._stop_file = self.task_store.directory(task_id)/"STOP"
        self.log.clear()
        self._set_running(self._task_running)
        self._poll_task(refresh=False)

    def refresh_tasks(self, *, recover=False):
        from control_lab.rl.tasks import ACTIVE
        tasks = self.task_store.list()
        selected = self.task_selector.currentData()
        self.task_selector.blockSignals(True)
        self.task_selector.clear()
        names = {"starting":"启动中", "running":"训练中", "stopping":"正在停止保存", "completed":"已完成",
                 "stopped":"已停止保存", "interrupted":"意外中断", "failed":"失败", "invalid":"记录损坏"}
        for task in tasks:
            config = task.get("request", {}).get("config", {})
            self.task_selector.addItem(f"{task['task_id'][:8]} · {names.get(task['status'],task['status'])} · seed{config.get('seed','?')} · {config.get('total_timesteps','?')}步", task["task_id"])
        target = self._task_id or selected
        index = self.task_selector.findData(target)
        if index >= 0:
            self.task_selector.setCurrentIndex(index)
        self.task_selector.blockSignals(False)
        active = [task for task in tasks if task["status"] in ACTIVE]
        self.tasks_group.setVisible(bool(tasks))
        self.task_summary.setText(f"登记{len(tasks)}个任务，{len(active)}个待完成。任务保留在本地，重新打开软件仍可查看日志、选模型或请求停止。")
        if recover and active and not self.is_running:
            self._attach_task(active[0]["task_id"])
        return tasks

    def _poll_task(self, *, refresh=True):
        self._task_ticks += 1
        if refresh and self._task_ticks % 10 == 0:
            self.refresh_tasks()
        if not self._task_id:
            return
        try:
            state = self.task_store.read(self._task_id)
            events_path = self.task_store.directory(self._task_id)/"events.jsonl"
            if events_path.is_file():
                with events_path.open("rb") as stream:
                    stream.seek(self._task_offset)
                    data = stream.read(512_000)
                    self._task_offset = stream.tell()
                self._buffer += self._decoder.decode(data)
                while "\n" in self._buffer:
                    line, self._buffer = self._buffer.split("\n", 1)
                    if not self._task_started_emitted:
                        try:
                            if json.loads(line).get("type") == "started" and self._task_emit_completion:
                                self.operationStarted.emit("train")
                                self._task_started_emitted = True
                        except ValueError:
                            pass
                    self._consume_line(line.strip())
            from control_lab.rl.tasks import ACTIVE
            if state["status"] not in ACTIVE and self._task_running:
                self._task_running = False
                self._set_running(False)
                if state["status"] in {"completed", "stopped"}:
                    result = state.get("result") or self._last_result
                    if result:
                        self._consume_line(json.dumps(result))
                        if self._task_emit_completion:
                            self.completed.emit(dict(result, operation="train"))
                else:
                    raw = self.task_store.directory(self._task_id)/"runner.log"
                    if raw.is_file():
                        self.log.appendPlainText(raw.read_text(encoding="utf-8", errors="replace")[-16000:])
                    self._show_error(state.get("error", "训练任务中断，记录已保留。"))
                self._task_emit_completion = False
                self.refresh_tasks()
        except (OSError, ValueError, KeyError) as exc:
            self._show_error(f"训练任务记录暂时无法读取：{exc}")

    def monitor_selected_task(self):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self._show_error("先结束当前评价或回放，再切换训练任务。")
            return False
        task_id = self.task_selector.currentData()
        if task_id:
            self._attach_task(task_id)
            self.log.show()
            return True
        return False

    def stop_selected_task(self):
        task_id = self.task_selector.currentData()
        if task_id:
            result = self.task_store.request_stop(task_id)
            self.refresh_tasks()
            return result
        return False

    def has_active_training(self):
        from control_lab.rl.tasks import ACTIVE
        return any(task["status"] in ACTIVE for task in self.task_store.list())

    def prepare_close(self, choice):
        from control_lab.rl.tasks import ACTIVE
        if choice == "cancel":
            self.abort_close()
            return False
        if choice not in {"stop", "keep"}:
            raise ValueError("Choose stop, keep, or cancel")
        self._leave_training = choice == "keep"
        for task in self.task_store.list():
            if task["status"] in ACTIVE:
                self.task_store.record_close_choice(task["task_id"], choice)
                if choice == "stop":
                    self.task_store.request_stop(task["task_id"])
        return self.shutdown()

    def abort_close(self):
        self._leave_training = False
        self._task_timer.start()
        self.refresh_tasks(recover=True)

    resume_monitoring = abort_close

    def shutdown(self) -> bool:
        if self._catalog_dialog is not None and self._catalog_dialog._worker:
            return False
        if self.process.state() != QProcess.ProcessState.NotRunning:
            if self._stop_file:
                self._stop_file.write_text("stop requested", encoding="utf-8")
            return False
        if self._leave_training:
            return True
        if self.has_active_training():
            from control_lab.rl.tasks import ACTIVE
            for task in self.task_store.list():
                if task["status"] in ACTIVE:
                    self.task_store.request_stop(task["task_id"])
            return False
        return True
