"""Qt orchestration only: all policy imports and work live in an external Python."""
from datetime import datetime
import codecs
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QComboBox, QPlainTextEdit, QFileDialog, QProgressBar,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView,
)


class TrainingPanel(QFrame):
    operationStarted = Signal(str)
    completed = Signal(dict)
    error = Signal(str)
    replayState = Signal(list, float)

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
        self._build_ui()
        self._load_settings()
        self.set_lesson(self._lesson_id)

    @property
    def is_running(self):
        return self.process.state() != QProcess.ProcessState.NotRunning

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
        self.comparison_table = QTableWidget(0, 4)
        self.comparison_table.setHorizontalHeaderLabels(["方法", "完成回合", "平均步数", "最短步数"])
        self.comparison_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.comparison_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
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

    def _load_settings(self):
        if self.settings_path.is_file():
            try:
                settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
                self.python_path.setText(settings.get("python", ""))
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
            temporary.write_text(json.dumps({"python": self.python_path.text().strip()}, ensure_ascii=False), encoding="utf-8")
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
            try:
                metadata = json.loads((Path(path) / "metadata.json").read_text(encoding="utf-8"))
                index = self.reward.findData(metadata.get("environment", {}).get("reward_id"))
                if index >= 0:
                    self.reward.setCurrentIndex(index)
            except (OSError, ValueError):
                self._show_error("该目录没有可读取的模型元数据，请选择完整模型包。")

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
        return self._launch("train", arguments)

    def evaluate_model(self):
        if self.is_running:
            return False
        model = self._model()
        if model is None:
            return False
        self._prepare_stop()
        self._run_dir = self._new_run("validation")
        return self._launch("evaluate", ["--model-dir", model, "--output-dir", self._run_dir,
                                        "--split", "validation", "--stop-file", self._stop_file])

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
        elif kind in ("completed", "stopped", "evaluation", "replay_completed", "doctor"):
            self._last_result = dict(message, operation=self._operation)
            if kind in ("completed", "stopped") and self._operation == "train" and message.get("path"):
                self.model_path.setText(message["path"])
            if kind == "evaluation":
                aggregate = message.get("aggregate", {})
                self.status.setText(f"验证完成：{aggregate.get('completed_episodes', 0)} / {aggregate.get('episodes', 0)} 回合达到时长上限。")
            elif kind == "doctor":
                self.status.setText("独立训练环境检查通过，可以开始实验。")
            elif kind == "stopped":
                self.status.setText("已停止；已写入的数据和模型保留。")
            elif kind == "completed":
                self.progress.setValue(100)
                self.status.setText("模型已保存。请独立验证，再判断是否学会平衡。")
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
        self.model_group.setVisible(lesson in ("L27", "L28"))
        self.actions_group.setVisible(lesson != "L25" or self.is_running)
        self.resume_button.setVisible(lesson == "L27")
        self.evaluate_button.setVisible(lesson in ("L26", "L27", "L28"))
        self.replay_button.setVisible(lesson in ("L27", "L28"))
        self.replay_case.setVisible(lesson in ("L27", "L28"))
        self.compare_button.setVisible(lesson == "L28")
        self.stop_button.setVisible(self.is_running or lesson != "L25")
        self.comparison_table.setVisible(lesson == "L28" and self.comparison_table.rowCount() > 0)

    def choose_comparison_reports(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择至少两份同协议评价report.json", str(self.data_dir),
                                              "评价报告 (*.json)")
        if paths:
            return self.compare_report_files(paths)
        return None

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
                cells = (method["controller"], f"{stats['completed_episodes']} / {stats['episodes']}",
                         f"{stats['mean_steps']:.2f}", str(stats["worst_steps"]))
                for column, value in enumerate(cells):
                    self.comparison_table.setItem(index, column, QTableWidgetItem(str(value)))
            self.comparison_table.show()
            split = comparison["comparison_contract"]["split"]
            self.status.setText(f"同协议对照已保存（{split}）。先比较完成与失败，再解释误差；结果不代表任意条件下的优劣。")
            result = {"type": "comparison", "operation": "compare", "status": "completed",
                      "path": str(destination), "methods": len(comparison["methods"])}
            self.completed.emit(result)
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._show_error(f"无法比较这些报告：{exc}")
            return None

    def shutdown(self) -> bool:
        if not self.is_running:
            return True
        self.stop()
        return False
