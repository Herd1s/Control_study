"""Explicit update checks/downloads in a cancellable background thread."""
from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from control_lab import __version__
from control_lab.updates.download import download_release
from control_lab.updates.installer import verify_cached_installer
from control_lab.updates.releases import (RepositoryConfig, ReleaseClient, UpdateCancelled,
                                         load_config, save_config)


class _UpdateWorker(QThread):
    result = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    progress = Signal(object, object)  # Byte counts may exceed signed Qt int32.

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.cancel_event = threading.Event()
        self.operation = operation

    def run(self):
        try:
            result = self.operation(self.cancel_event, self.progress.emit)
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.result.emit(result)
        except UpdateCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def cancel(self):
        self.cancel_event.set()


class UpdatesPanel(QWidget):
    readyToInstall = Signal(object)
    error = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        self.cache_dir = self.data_dir / "updates" / "downloads"
        self._worker = None
        self._release = None
        self._installer = None
        self._operation = None
        self._closing = False
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"软件更新 · 当前版本 {__version__}"))
        description = QLabel("从你指定的公开 GitHub 仓库检查正式版本。检查、下载和安装分别由你操作；离线时已有课程仍可使用。")
        description.setWordWrap(True)
        layout.addWidget(description)
        form = QFormLayout()
        self.owner_edit = QLineEdit()
        self.owner_edit.setPlaceholderText("发布者或组织，例如你的 GitHub 用户名")
        self.repo_edit = QLineEdit()
        self.repo_edit.setPlaceholderText("仓库名，例如 ControlLab；不要粘贴网址")
        form.addRow("发布者 owner", self.owner_edit)
        form.addRow("仓库 repo", self.repo_edit)
        layout.addLayout(form)
        self.check_button = QPushButton("保存设置并检查")
        self.download_button = QPushButton("下载此版本")
        self.install_button = QPushButton("安装更新…")
        self.cancel_button = QPushButton("取消当前操作")
        row = QHBoxLayout()
        for button in (self.check_button, self.download_button, self.install_button, self.cancel_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.check_button.clicked.connect(self.check_for_updates)
        self.download_button.clicked.connect(self.download_update)
        self.install_button.clicked.connect(self.request_installation)
        self.cancel_button.clicked.connect(self.cancel)
        self.status_label = QLabel("尚未配置发布仓库。填写发布者和仓库名后，再主动检查。")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)
        self.release_notes = QPlainTextEdit()
        self.release_notes.setReadOnly(True)
        self.release_notes.setPlaceholderText("版本说明会显示在这里；内容来自所配置的仓库。")
        layout.addWidget(self.release_notes, 1)
        integrity = QLabel("下载使用 HTTPS，并核对版本发布的 SHA256。该校验验证文件一致性，不等于发布者数字签名；请填写你认可的发布仓库。")
        integrity.setWordWrap(True)
        layout.addWidget(integrity)
        try:
            config = load_config(self.data_dir)
            if config is not None:
                self.owner_edit.setText(config.owner)
                self.repo_edit.setText(config.repo)
                self.status_label.setText(f"已配置 {config.full_name}；点击检查后才会访问网络。")
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            self.status_label.setText(f"原更新设置已保留，请检查后重新保存：{exc}")
        self.owner_edit.textEdited.connect(self._source_changed)
        self.repo_edit.textEdited.connect(self._source_changed)
        self._update_buttons()

    @property
    def running(self):
        return self._worker is not None and self._worker.isRunning()

    def _update_buttons(self):
        busy = self.running
        self.check_button.setEnabled(not busy and not self._closing)
        self.download_button.setEnabled(not busy and self._release is not None and not self._closing)
        self.install_button.setEnabled(not busy and self._installer is not None and not self._closing)
        self.cancel_button.setEnabled(busy)
        self.owner_edit.setEnabled(not busy)
        self.repo_edit.setEnabled(not busy)

    def _source_changed(self):
        self._release = None
        self._installer = None
        self.release_notes.clear()
        self.status_label.setText("发布仓库设置已修改，请重新保存并检查。")
        self._update_buttons()

    def _start(self, operation, function):
        if self.running:
            return
        self._operation = operation
        worker = _UpdateWorker(function, self)
        self._worker = worker
        worker.result.connect(self._result)
        worker.failed.connect(self._failed)
        worker.cancelled.connect(self._cancelled)
        worker.progress.connect(self._progress)
        worker.finished.connect(self._worker_finished)
        worker.start()
        self._update_buttons()

    def check_for_updates(self):
        if self.running:
            return
        try:
            config = RepositoryConfig(self.owner_edit.text().strip(), self.repo_edit.text().strip())
            save_config(self.data_dir, config)
        except (OSError, ValueError) as exc:
            self._failed(str(exc))
            return
        self._release = None
        self._installer = None
        self.progress_bar.setRange(0, 0)
        self.release_notes.clear()
        self.status_label.setText(f"正在检查 {config.full_name} 的正式版本…")
        self._start("check", lambda cancel, progress: ReleaseClient(config).check(__version__, cancel))

    def download_update(self):
        if self.running or self._release is None:
            return
        release = self._release
        self._installer = None
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"正在下载 {release.filename}，尚未执行安装。")
        self._start("download", lambda cancel, progress: download_release(
            release, self.cache_dir, cancel_event=cancel, progress=progress))

    def _result(self, result):
        self.progress_bar.setRange(0, 100)
        if self._operation == "check":
            self._release = result
            if result is None:
                self.status_label.setText("该仓库暂无比当前版本更新的正式版本。")
            else:
                self.status_label.setText(f"发现 {result.version} · {result.repository.full_name} · {result.size_bytes / 1024**2:.1f} MiB。可阅读说明后下载。")
                self.release_notes.setPlainText(result.notes + "\n\n版本来源：" + result.release_url)
        else:
            self._installer = Path(result)
            self.progress_bar.setValue(100)
            self.status_label.setText("下载完整且 SHA256 一致。点击安装后，软件将先保存作业并停止实验，再交给安装向导；完成后可在向导中选择打开软件。")

    def _failed(self, message):
        self.progress_bar.setRange(0, 100)
        self.status_label.setText(f"操作未完成：{message}。当前版本和学习文件保持可用。")
        self.error.emit(message)

    def _cancelled(self):
        self.progress_bar.setRange(0, 100)
        self.status_label.setText("已取消。当前软件和作业没有被替换。")

    def _progress(self, downloaded, total):
        self.progress_bar.setValue(round(100 * downloaded / total) if total else 0)

    def _worker_finished(self):
        worker, self._worker = self._worker, None
        if worker is not None:
            worker.deleteLater()
        self._update_buttons()

    def cancel(self):
        if self._worker is not None:
            self.status_label.setText("正在取消；网络阻塞最多等待本次连接超时。")
            self._worker.cancel()

    def request_installation(self):
        if self.running or self._installer is None:
            return
        try:
            release = verify_cached_installer(self._installer, self.cache_dir)
        except Exception as exc:
            self._failed(str(exc))
            return
        answer = QMessageBox.question(self, "安装更新", f"准备安装 {release.version}。\n软件将先保存作业、停止实验并退出，然后打开安装向导。\n安装完成后，可在向导中选择打开软件。\n是否继续？",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.readyToInstall.emit(self._installer)

    def shutdown(self):
        """Return False while a bounded network request is still unwinding.

        The containing window should defer its close and retry when False, rather
        than destroy a running QThread. No GUI-thread wait() is performed.
        """
        self._closing = True
        self.cancel()
        self._update_buttons()
        return not self.running

    def closeEvent(self, event):
        if self.shutdown():
            event.accept()
        else:
            event.ignore()
