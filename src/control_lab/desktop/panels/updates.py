"""Explicit update checks/downloads in a cancellable background thread."""
from pathlib import Path
import threading

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWidget)

from control_lab import __version__
from control_lab.updates.download import download_release
from control_lab.updates.installer import (list_cached_installers, read_cached_installer_log,
                                          verify_cached_installer)
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
        recovery_note = QLabel("安装未完成时，可查看本机日志并重新校验已下载的安装包。只有缓存清单和文件 SHA256 一致的安装包才可重试；不会自动执行。")
        recovery_note.setWordWrap(True)
        layout.addWidget(recovery_note)
        self.cache_combo = QComboBox()
        self.cache_combo.setAccessibleName("本地安装包恢复列表")
        layout.addWidget(self.cache_combo)
        recovery_row = QHBoxLayout()
        self.refresh_cache_button = QPushButton("重新核对本地安装包")
        self.retry_install_button = QPushButton("重试所选安装包…")
        self.view_log_button = QPushButton("查看安装日志")
        for button in (self.refresh_cache_button, self.retry_install_button, self.view_log_button):
            recovery_row.addWidget(button)
        layout.addLayout(recovery_row)
        self.refresh_cache_button.clicked.connect(self.refresh_cache)
        self.retry_install_button.clicked.connect(self.retry_cached_installation)
        self.view_log_button.clicked.connect(self.view_installer_log)
        self.cache_combo.currentIndexChanged.connect(self._update_buttons)
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
        entry = self.cache_combo.currentData()
        self.cache_combo.setEnabled(not busy)
        self.refresh_cache_button.setEnabled(not busy and not self._closing)
        self.retry_install_button.setEnabled(not busy and not self._closing and bool(entry and entry["verified"]))
        self.view_log_button.setEnabled(not busy and bool(entry and entry["log_paths"]))

    def refresh_cache(self):
        if self.running:
            return
        self.status_label.setText("正在重新读取本地缓存并计算 SHA256；不会访问网络或执行安装包。")
        self.progress_bar.setRange(0, 0)
        self._start("recovery", lambda cancel, progress: list_cached_installers(self.cache_dir, cancel_event=cancel))

    def retry_cached_installation(self):
        entry = self.cache_combo.currentData()
        if self.running or not entry or not entry["verified"]:
            return
        self._installer = Path(entry["installer_path"])
        self.request_installation()

    def view_installer_log(self):
        entry = self.cache_combo.currentData()
        if not entry or not entry["log_paths"]:
            return
        try:
            path = entry["log_paths"][0]
            self.release_notes.setPlainText(f"最近一次安装日志：{path}\n（最多显示末尾 128 KiB；所有尝试日志保存在同一目录）\n\n" +
                                           read_cached_installer_log(path, self.cache_dir))
            self.status_label.setText("显示安装日志。安装器启动记录不代表安装成功；可结合日志决定是否重试。")
        except (OSError, ValueError, RuntimeError) as exc:
            self._failed(str(exc))

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
        if self._operation == "recovery":
            self.cache_combo.clear()
            labels = {"verified": "已校验，未启动", "unconfirmed": "安装结果尚未确认", "completed": "已确认完成", "invalid": "校验失败"}
            for entry in result:
                label = f"{entry['version']} · {entry['repository']} · {labels[entry['status']]}"
                self.cache_combo.addItem(label, entry)
            self.status_label.setText(f"找到 {len(result)} 份缓存记录，{sum(e['verified'] for e in result)} 份重新校验通过。选择记录后可查看日志或主动重试。")
            self.release_notes.setPlainText("\n".join(f"{e['folder']}\n{e['error'] or labels[e['status']]}" for e in result))
        elif self._operation == "check":
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
        answer = QMessageBox.question(self, "安装更新", f"准备安装 {release.version}，来源 {release.repository.full_name}（当前 {__version__}）。\n缓存包可能是较早版本，请确认选择。\n软件将先保存作业、停止实验并退出，然后打开安装向导。\n安装完成后，可在向导中选择打开软件。\n是否继续？",
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
