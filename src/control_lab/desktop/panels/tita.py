"""Optional TITA environment panel; all robotics execution stays in QProcess."""
from __future__ import annotations

import codecs
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout,
)

from control_lab.integrations.tita_profile import (
    TitaProfile, build_command, load_profile, parse_inspection_output,
    save_profile, write_run_record,
)


class TitaPanel(QFrame):
    statusChanged = Signal(str)
    inspectionFinished = Signal(dict)
    runFinished = Signal(dict)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.setObjectName("guide")
        self.data_dir = Path(data_dir)
        self._process = None
        self._command = None
        self._stream = None
        self._output = ""
        self._cancelled = False
        self._did_time_out = False
        self._inspection = None
        try:
            self.profile = load_profile(self.data_dir)
        except (OSError, ValueError, TypeError):
            self.profile = TitaProfile("", "", "")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)
        title = QLabel("连接外部 TITA 仿真环境")
        title.setObjectName("guideTitle")
        layout.addWidget(title)
        note = QLabel("先检查环境，再运行 8 个机器人、2 轮的无界面检查。此入口只用于仿真；短训模型不能说明机器人已经学会行走。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.path_fields = {}
        for key, caption, kind in (("python_executable", "TITA Python", "python"),
                                   ("ddt_root", "DDT_Lab 目录", "directory"),
                                   ("isaaclab_root", "IsaacLab 目录", "directory"),
                                   ("checkpoint_path", "自己的仿真模型 .pt", "checkpoint")):
            label = QLabel(caption)
            layout.addWidget(label)
            row = QHBoxLayout()
            field = QLineEdit(getattr(self.profile, key))
            field.setAccessibleName(caption)
            field.setToolTip(field.text())
            field.textChanged.connect(field.setToolTip)
            browse = QPushButton("选择")
            browse.setMaximumWidth(60)
            browse.clicked.connect(lambda _checked=False, name=key, selection=kind: self._browse(name, selection))
            row.addWidget(field, 1)
            row.addWidget(browse)
            layout.addLayout(row)
            self.path_fields[key] = field
        self.buttons = {}
        for modes in (("inspect", "registry"), ("smoke", "stop"), ("play", "export")):
            row = QHBoxLayout()
            labels = {"inspect": "检查环境", "registry": "核对运行时任务", "smoke": "低资源仿真检查",
                      "stop": "停止外部进程", "play": "1 个机器人回放", "export": "导出模型"}
            for mode in modes:
                button = QPushButton(labels[mode])
                button.clicked.connect(self.stop if mode == "stop" else lambda _checked=False, task=mode: self.start(task))
                self.buttons[mode] = button
                row.addWidget(button)
            layout.addLayout(row)
        self.buttons["stop"].setEnabled(False)
        self.copy_button = QPushButton("复制固定的无界面检查命令")
        self.copy_button.clicked.connect(self.copy_smoke_command)
        layout.addWidget(self.copy_button)
        self.status = QLabel("检查只读取版本、提交号和任务声明；仿真由独立 Python 运行。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(1200)
        self.output.setMinimumHeight(120)
        self.output.setMaximumHeight(220)
        self.output.setPlaceholderText("外部环境检查与运行日志")
        layout.addWidget(self.output)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.timeout.connect(self._timed_out)

    @property
    def running(self):
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def _set_status(self, message):
        self.status.setText(message)
        self.statusChanged.emit(message)

    def _browse(self, key, kind):
        current = self.path_fields[key].text()
        if kind == "directory":
            selected = QFileDialog.getExistingDirectory(self, "选择目录", current)
        else:
            extension = "Python (python.exe)" if kind == "python" else "TITA 仿真模型 (*.pt)"
            selected, _ = QFileDialog.getOpenFileName(self, "选择文件", current, extension)
        if selected:
            self.path_fields[key].setText(selected)

    def save_profile(self):
        self.profile = replace(self.profile, **{name: field.text().strip() for name, field in self.path_fields.items()})
        save_profile(self.data_dir, self.profile)
        return self.profile

    def copy_smoke_command(self):
        try:
            command = build_command(self.save_profile(), "smoke", self.data_dir)
            QApplication.clipboard().setText(command.powershell())
            self._set_status("已复制 8 环境、2 轮、headless 命令，可在 PowerShell 中查看并运行。")
        except (OSError, ValueError, TypeError) as exc:
            self._set_status(str(exc))

    def inspect(self):
        self.start("inspect")

    def start(self, mode="inspect"):
        if self.running:
            self._set_status("先停止当前外部进程，再开始下一项。")
            return
        try:
            command = build_command(self.save_profile(), mode, self.data_dir)
            folder = self.data_dir / "tita" / "runs"
            folder.mkdir(parents=True, exist_ok=True)
            self._log_path = folder / f"{command.run_tag}_{mode}.log"
            self._stream = self._log_path.open("x", encoding="utf-8")
        except (OSError, ValueError, TypeError) as exc:
            self._set_status(str(exc))
            return
        self._command = command
        self._output = ""
        self._cancelled = False
        self._did_time_out = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.output.clear()
        process = QProcess(self)
        self._process = process
        environment = QProcessEnvironment.systemEnvironment()
        for name, value in command.environment.items():
            environment.insert(name, value)
        process.setProcessEnvironment(environment)
        process.setWorkingDirectory(command.working_directory)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_output)
        process.finished.connect(self._finished)
        process.errorOccurred.connect(self._process_error)
        for button in self.buttons.values():
            button.setEnabled(False)
        self.buttons["stop"].setEnabled(True)
        for field in self.path_fields.values():
            field.setEnabled(False)
        self.copy_button.setEnabled(False)
        self._set_status("正在检查外部 Python…" if mode == "inspect" else "外部仿真启动中，首次加载可能需要等待。可随时停止。")
        # Playback is explicitly interactive; other checks receive bounded time.
        if mode != "play":
            self._timeout.start(45_000 if mode == "inspect" else 300_000)
        process.start(command.program, list(command.arguments))

    def _read_output(self):
        if self._process is None:
            return
        chunk = self._decoder.decode(bytes(self._process.readAllStandardOutput()))
        if not chunk:
            return
        if self._stream is not None:
            self._stream.write(chunk)
            self._stream.flush()
        self._output = (self._output + chunk)[-2_000_000:]
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(chunk)
        self.output.setTextCursor(cursor)

    def _process_error(self, error):
        if self._process is not None and error == QProcess.ProcessError.FailedToStart:
            self._set_status("外部 Python 无法启动，请检查所选路径。")
            self._finished(-1, QProcess.ExitStatus.CrashExit)

    def _finished(self, exit_code, exit_status):
        if self._process is None:
            return
        self._timeout.stop()
        self._read_output()
        command = self._command
        status = ("timeout" if self._did_time_out else "cancelled" if self._cancelled
                  else "completed" if exit_code == 0 and exit_status == QProcess.ExitStatus.NormalExit
                  else "error")
        report = None
        if command.mode == "inspect" and exit_code == 0:
            try:
                report = parse_inspection_output(self._output)
                self._inspection = report
                self.inspectionFinished.emit(report)
            except ValueError as exc:
                status = "error"
                self._set_status(str(exc))
        if self._stream is not None:
            tail = self._decoder.decode(b"", final=True)
            if tail:
                self._stream.write(tail)
            self._stream.close()
            self._stream = None
        try:
            record = write_run_record(self.data_dir, command, exit_code=exit_code, status=status,
                                      log_path=self._log_path, inspection=report or self._inspection)
            payload = dict(mode=command.mode, status=status, exit_code=exit_code, record_path=str(record))
            self.runFinished.emit(payload)
        except (OSError, ValueError) as exc:
            self._set_status(f"运行结束，但结果记录未保存：{exc}")
        else:
            if report is not None:
                ready = "路径与包已就绪；仍需运行仿真检查。" if report["ready_for_smoke"] else "部分外部依赖或路径尚未就绪。"
                self._set_status(f"外部 Python {report['python']}，找到 {len(report['task_registry']['ids'])} 个 TITA 任务声明。{ready}")
            elif status == "completed":
                self._set_status("外部任务已完成。日志与版本记录已保存在学习目录。")
            elif status == "cancelled":
                self._set_status("已停止外部进程，本次记录标为取消。")
            elif status == "timeout":
                self._set_status("外部检查已超时停止；日志保留，未记为通过。")
            else:
                self._set_status(f"外部任务退出码 {exit_code}，请查看日志。")
        self._process.deleteLater()
        self._process = None
        for name, button in self.buttons.items():
            button.setEnabled(name != "stop")
        for field in self.path_fields.values():
            field.setEnabled(True)
        self.copy_button.setEnabled(True)

    def stop(self, checked=False):
        if self._process is None:
            return
        self._cancelled = True
        process = self._process
        process.terminate()
        QTimer.singleShot(1500, lambda: self._kill_if_current(process))

    def _kill_if_current(self, process):
        if self._process is process and process.state() != QProcess.ProcessState.NotRunning:
            process.kill()

    def _timed_out(self):
        self._did_time_out = True
        self._set_status("外部检查超过时间上限，正在停止；日志会保留。")
        self.stop()

    def shutdown(self):
        if self._process is not None:
            self._cancelled = True
            self._process.kill()
            self._process.waitForFinished(2000)

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)
