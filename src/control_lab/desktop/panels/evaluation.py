"""Background protocol evaluation; no simulation loop runs in the Qt thread."""
from __future__ import annotations

import codecs
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import uuid

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)


class EvaluationPanel(QWidget):
    completed = Signal(dict)
    error = Signal(str)
    caseViewed = Signal(dict)
    comparisonCompleted = Signal(dict)
    sweepCompleted = Signal(dict)
    projectExported = Signal(dict)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self._output_dir = None
        self._cancelled = False
        self._generation = 0
        self._current_report_path = None
        self._dialogs = []
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._read_output)
        self._process.finished.connect(self._finished)
        self._process.errorOccurred.connect(self._process_error)

        layout = QVBoxLayout(self)
        title = QLabel("用同一把尺，比较控制器")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        note = QLabel("固定非零初态、±10 N、0.02 s、最多 500 步。先看是否通过，再看摆角和用力；全部回合都会保留。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.controller_box = QComboBox()
        for label, name in (("参考：PD + 回中（Ki=0）", "reference"),
                            ("角度 PD", "reference-angle"), ("零输入基线", "zero"),
                            ("我的控制器文件", "student")):
            self.controller_box.addItem(label, name)
        form.addRow("控制方案", self.controller_box)
        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self.controller_file = QLineEdit()
        self.controller_file.setPlaceholderText("选择 control(state, dt) 或 Controller 类的 Python 文件")
        self.browse_button = QPushButton("选择文件")
        self.browse_button.clicked.connect(self._browse)
        file_layout.addWidget(self.controller_file, 1)
        file_layout.addWidget(self.browse_button)
        form.addRow("学生代码", file_row)
        self.split_box = QComboBox()
        self.split_box.addItem("练习：5 个回合（42–46）", "practice")
        self.split_box.addItem("开发验证：20 个回合（100–119）", "validation")
        self.split_box.setCurrentIndex(1)
        form.addRow("用例组", self.split_box)
        self.advanced_box = QCheckBox("高级：冻结配置后的保留测试")
        self.advanced_box.toggled.connect(self._toggle_advanced)
        form.addRow(self.advanced_box)
        self.frozen_hash = QLineEdit()
        self.frozen_hash.setPlaceholderText("粘贴验证报告中的 controller_sha256（64 位）")
        self.hash_label = QLabel("冻结指纹")
        form.addRow(self.hash_label, self.frozen_hash)
        self.hash_label.hide()
        self.frozen_hash.hide()
        layout.addLayout(form)
        buttons = QHBoxLayout()
        self.start_button = QPushButton("开始评价")
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(self.start_evaluation)
        self.stop_button.clicked.connect(self.stop_evaluation)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        tools = QGridLayout()
        for index, (text, slot) in enumerate((("打开评价报告", lambda: self.open_report()),
                                               ("回放选中回合", self.replay_selected_case),
                                               ("比较多个报告", self.choose_comparison),
                                               ("P / PI 参数实验", lambda: self.open_sweep()),
                                               ("导出课程项目", self.open_project))):
            button = QPushButton(text)
            button.clicked.connect(slot)
            tools.addWidget(button, index//3, index%3)
        layout.addLayout(tools)
        self.status_label = QLabel("选择同一组用例，逐项对照；保留测试不用于调参。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.results_table = QTableWidget(0, 10)
        self.results_table.setHorizontalHeaderLabels(["用例", "步数", "通过", "角度 RMS / rad", "结束原因", "错误",
                                                     "最大 |x| / m", "平均 |力| / N", "饱和比例", "力变化 / N"])
        self.results_table.cellDoubleClicked.connect(lambda *_: self.replay_selected_case())
        self.results_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.results_table.setMinimumHeight(180)
        layout.addWidget(self.results_table, 1)
        self.output_log = QPlainTextEdit()
        self.output_log.setReadOnly(True)
        self.output_log.setMaximumBlockCount(1500)
        self.output_log.setMaximumHeight(130)
        self.output_log.setPlaceholderText("后台进度将在这里显示；评价期间界面仍可操作。")
        layout.addWidget(self.output_log)
        self.controller_box.currentIndexChanged.connect(self._update_controls)
        self._update_controls()

    @property
    def running(self):
        return self._process.state() != QProcess.ProcessState.NotRunning

    def set_controller_file(self, path):
        self.controller_file.setText(str(Path(path).expanduser().resolve()))
        self.controller_box.setCurrentIndex(self.controller_box.findData("student"))

    def _browse(self):
        filename, _ = QFileDialog.getOpenFileName(self, "选择控制器", str(self.data_dir), "Python (*.py)")
        if filename:
            self.set_controller_file(filename)

    def _toggle_advanced(self, checked):
        index = self.split_box.findData("held_out")
        if checked and index < 0:
            self.split_box.addItem("保留测试：20 回合（仅用于冻结后验收）", "held_out")
        elif not checked and index >= 0:
            self.split_box.removeItem(index)
        self.hash_label.setVisible(checked)
        self.frozen_hash.setVisible(checked)

    def _update_controls(self):
        running = self.running
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        for widget in (self.controller_box, self.split_box, self.advanced_box, self.frozen_hash):
            widget.setEnabled(not running)
        editable = not running and self.controller_box.currentData() == "student"
        self.controller_file.setEnabled(editable)
        self.browse_button.setEnabled(editable)

    def _fail(self, message):
        self.status_label.setText(message)
        self.error.emit(message)

    def start_evaluation(self):
        if self.running:
            return
        controller, split = self.controller_box.currentData(), self.split_box.currentData()
        file_path = Path(self.controller_file.text()).expanduser()
        if controller == "student" and not file_path.is_file():
            self._fail("请选择已保存的学生 Python 文件，再开始评价。")
            return
        fingerprint = self.frozen_hash.text().strip()
        if split == "held_out" and not re.fullmatch(r"[0-9a-fA-F]{64}", fingerprint):
            self._fail("保留测试需要先冻结控制器，并填写开发验证报告中的 64 位 controller_sha256。")
            return
        if getattr(sys, "frozen", False):
            program = str(Path(sys.executable).with_name("ControlLabCLI.exe"))
            arguments = ["evaluate"]
            if not Path(program).is_file():
                self._fail("缺少 ControlLabCLI.exe，请使用完整的软件文件夹。")
                return
        else:
            interpreter = Path(sys.executable)
            if interpreter.name.lower() == "pythonw.exe":
                interpreter = interpreter.with_name("python.exe")
            program = str(interpreter)
            arguments = ["-m", "control_lab", "evaluate"]
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
        self._output_dir = self.data_dir / "evaluations" / run_name
        try:
            self._output_dir.mkdir(parents=True, exist_ok=False)
        except OSError as exc:
            self._fail(f"无法创建评价目录：{exc}")
            return
        arguments += ["--controller", controller, "--split", split, "--output-dir", str(self._output_dir)]
        if controller == "student":
            arguments += ["--controller-file", str(file_path.resolve())]
        if split == "held_out":
            arguments += ["--frozen-controller-sha256", fingerprint.lower()]
        environment = QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONUTF8", "1")
        environment.insert("PYTHONUNBUFFERED", "1")
        self._process.setProcessEnvironment(environment)
        self._cancelled = False
        self._generation += 1
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.results_table.setRowCount(0)
        self.output_log.clear()
        self.status_label.setText(f"正在后台评价；结果将保存在 {self._output_dir}")
        self._process.start(program, arguments)
        self._update_controls()

    def _read_output(self):
        data = bytes(self._process.readAllStandardOutput())
        text = self._decoder.decode(data)
        if text:
            cursor = self.output_log.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertText(text)
            self.output_log.setTextCursor(cursor)

    def stop_evaluation(self):
        if not self.running:
            return
        self._cancelled = True
        generation = self._generation
        self.status_label.setText("正在取消；已生成的记录保留，本次不会标记为完成成绩。")
        try:
            (self._output_dir / "STOP").touch()
        except (OSError, TypeError):
            self._process.terminate()
        QTimer.singleShot(1500, lambda: self._kill_if_running(generation))

    def _kill_if_running(self, generation):
        if generation == self._generation and self.running and self._cancelled:
            self._process.kill()

    def _process_error(self, process_error):
        if self._cancelled:
            return
        self._fail(f"评价进程错误：{self._process.errorString()}")
        if process_error == QProcess.ProcessError.FailedToStart:
            self._update_controls()

    def _finished(self, exit_code, exit_status):
        self._read_output()
        self._update_controls()
        if self._cancelled:
            self.status_label.setText(f"已取消。本次不是完整成绩；现有记录保留在 {self._output_dir}")
            if self._output_dir is not None:
                try:
                    if (self._output_dir / "report.json").is_file():
                        partial = json.loads((self._output_dir / "report.json").read_text(encoding="utf-8"))
                        self._fill_rows(partial)
                        self._current_report_path = self._output_dir / "report.json"
                    (self._output_dir / "cancelled.json").write_text(
                        json.dumps({"status": "cancelled", "result_is_complete": False}, indent=2), encoding="utf-8")
                except OSError:
                    pass
            return
        # The CLI returns 1 when all cases were recorded but student code failed.
        # Those errors still belong in the full results table, not an empty view.
        report_path = self._output_dir / "report.json"
        if exit_status == QProcess.ExitStatus.CrashExit or (exit_code != 0 and not report_path.is_file()):
            self._fail(f"评价未完成（退出码 {exit_code}），请查看后台输出；已有记录保留。")
            return
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            episodes, summary = report["episodes"], report["aggregate"]
            expected = 5 if self.split_box.currentData() == "practice" else 20
            if report.get("is_complete") is False or len(episodes) != expected or summary["episodes"] != expected:
                raise ValueError("评价回合不完整，不能当作完成成绩")
            self._fill_rows(report)
            self._current_report_path = report_path
            self.status_label.setText(
                f"通过 {summary['completed_episodes']}/{summary['episodes']}（{summary['completed_fraction']:.0%}） · "
                f"平均 {summary['mean_steps']:.1f} 步 · 最差 {summary['worst_steps']} 步 · "
                f"代码错误 {summary['controller_errors']} 次\n全部记录：{self._output_dir}")
            self.completed.emit(report)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail(f"无法确认完整评价结果：{exc}")

    def shutdown(self):
        """Called by the containing window before it closes; never block Qt."""
        self.stop_evaluation()
        if self.running:
            self._process.kill()  # The event loop may stop before the grace timer.
        for dialog in self._dialogs:
            dialog.close()

    def _fill_rows(self, report):
        self.results_table.setRowCount(len(report["episodes"]))
        number = lambda value: f"{value:.5f}" if value is not None else "—"
        for row_index, episode in enumerate(report["episodes"]):
            err = episode.get("controller_error")
            values = [episode["case_id"], str(episode["episode_steps"]), "是" if episode["completed"] else "否",
                      number(episode["rms_theta_rad"]), episode["end_reason"],
                      err.get("message", str(err)) if isinstance(err, dict) else str(err or ""),
                      number(episode["max_abs_x_m"]), number(episode["mean_abs_actuator_force_n"]),
                      number(episode["saturation_fraction"]), number(episode["mean_abs_force_change_n"])]
            for column, value in enumerate(values):
                self.results_table.setItem(row_index, column, QTableWidgetItem(value))
        self.results_table.resizeColumnsToContents()

    def open_report(self, path=None, *, case_id=None):
        from .evaluation_history import EvaluationReportDialog
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "打开正式评价报告", str(self.data_dir / "evaluations"), "评价报告 (report.json)")
        if not path:
            return None
        try:
            dialog = EvaluationReportDialog(path, self)
            dialog.caseViewed.connect(self.caseViewed.emit)
            if case_id is not None:
                dialog.case_box.setCurrentIndex(dialog.case_box.findData(case_id))
            self._current_report_path = Path(path) / "report.json" if Path(path).is_dir() else Path(path)
            self._fill_rows(dialog.record.report)
            self._dialogs.append(dialog)
            dialog.show()
            return dialog
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail(f"无法打开评价报告：{exc}")
            return None

    def replay_selected_case(self):
        if self._current_report_path is None:
            self._fail("先运行一次评价，或打开已有的正式评价报告。")
            return None
        row = max(0, self.results_table.currentRow())
        item = self.results_table.item(row, 0)
        return self.open_report(self._current_report_path, case_id=item.text() if item else None)

    def choose_comparison(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择至少两个同协议报告", str(self.data_dir / "evaluations"), "评价报告 (report.json)")
        if paths:
            self.compare_paths(paths)

    def compare_paths(self, paths):
        from control_lab.evaluation.report_io import load_evaluation
        from control_lab.evaluation.compare import compare_reports
        try:
            records = [load_evaluation(path, require_complete=True) for path in paths]
            if len({record.report["controller_sha256"] for record in records}) != len(records):
                raise ValueError("请选择不同控制器配置，重复方法不能增加方法数量")
            comparison = compare_reports(record.report for record in records)
            dialog = QDialog(self)
            dialog.setWindowTitle("同一协议的控制方法对照")
            from ._dialogs import scrolling_body
            layout = scrolling_body(dialog, self, (900, 600))
            notice = QLabel("先看失败与完成率，再看角度、位置和用力；不把提前失败造成的短轨迹当作低误差优势。")
            notice.setWordWrap(True)
            layout.addWidget(notice)
            table = QTableWidget(len(records), 8)
            table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            table.setHorizontalHeaderLabels(["方法", "通过", "平均步数", "最差步数", "角 RMS/rad", "最大|x|/m", "平均|力|/N", "饱和比例"])
            def mean(report, key):
                values = [entry[key] for entry in report["episodes"] if entry[key] is not None]
                return f"{sum(values)/len(values):.5f}" if values else "—"
            for row, record in enumerate(records):
                report, summary = record.report, record.report["aggregate"]
                values = [report["controller"], f"{summary['completed_episodes']}/{summary['episodes']}",
                          f"{summary['mean_steps']:.2f}", str(summary["worst_steps"]),
                          f"{summary['mean_episode_rms_theta_rad']:.5f}",
                          f"{max(case['max_abs_x_m'] for case in report['episodes']):.5f}",
                          mean(report, "mean_abs_actuator_force_n"), mean(report, "saturation_fraction")]
                for column, value in enumerate(values):
                    table.setItem(row, column, QTableWidgetItem(value))
            table.resizeColumnsToContents()
            layout.addWidget(table)
            details = QPlainTextEdit()
            details.setReadOnly(True)
            details.setPlainText(json.dumps(comparison, ensure_ascii=False, indent=2))
            layout.addWidget(details, 1)
            folder = self.data_dir / "comparisons"
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / (datetime.now().strftime("%Y%m%d_%H%M%S_%f")+".json")
            destination.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
            self._dialogs.append(dialog)
            dialog.show()
            self.comparisonCompleted.emit({"path": str(destination), "method_count": len(records),
                                           "reports": [str(record.folder / "report.json") for record in records]})
            return dialog
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self._fail(f"这些报告不能直接比较：{exc}")
            return None

    def open_sweep(self, kind="p"):
        from .sweep import SweepPanel
        dialog = QDialog(self)
        dialog.setWindowTitle("固定条件的参数实验")
        from ._dialogs import scrolling_body
        layout = scrolling_body(dialog, self, (850, 700))
        panel = SweepPanel(self.data_dir, dialog)
        panel.set_kind(kind)
        panel.completed.connect(self.sweepCompleted.emit)
        panel.error.connect(self.error.emit)
        layout.addWidget(panel)
        dialog.finished.connect(lambda *_: panel.shutdown())
        self._dialogs.append(dialog)
        dialog.show()
        return panel

    def open_project(self):
        from .project import ProjectPanel
        dialog = QDialog(self)
        dialog.setWindowTitle("导出我的控制项目")
        from ._dialogs import scrolling_body
        layout = scrolling_body(dialog, self, (750, 620))
        panel = ProjectPanel(self.data_dir, dialog)
        panel.exported.connect(self.projectExported.emit)
        panel.error.connect(self.error.emit)
        layout.addWidget(panel)
        self._dialogs.append(dialog)
        dialog.show()
        return panel

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
