import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from control_lab.desktop.panels import updates as panel_module
from control_lab.updates.download import download_release
from test_updates import release, Transport


def until(app, predicate, timeout=10):
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(5)
    raise AssertionError('Update worker did not finish')


def test_update_panel_requires_separate_check_download_and_install(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    calls = []
    class Client:
        def __init__(self, config):
            self.config = config
        def check(self, version, cancel):
            calls.append('check')
            return release()
    monkeypatch.setattr(panel_module, 'ReleaseClient', Client)
    monkeypatch.setattr(panel_module, 'download_release',
                        lambda info, cache, **kwargs: download_release(info, cache, transport=Transport(), **kwargs))
    panel = panel_module.UpdatesPanel(tmp_path)
    ready = []
    panel.readyToInstall.connect(ready.append)
    try:
        assert calls == [] and not panel.download_button.isEnabled()
        panel.owner_edit.setText('Teacher')
        panel.repo_edit.setText('ControlLab')
        panel.check_for_updates()
        until(app, lambda: not panel.running)
        app.processEvents()
        assert calls == ['check'] and panel._installer is None
        assert panel.download_button.isEnabled()
        panel.download_update()
        until(app, lambda: not panel.running)
        app.processEvents()
        assert panel._installer.is_file() and ready == []
        monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.No)
        panel.request_installation()
        assert ready == []
        monkeypatch.setattr(QMessageBox, 'question', lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
        panel.request_installation()
        assert ready == [panel._installer]
        assert not (panel._installer.parent / 'handoff.json').exists()  # Root coordinates launch.
    finally:
        panel.shutdown()
        until(app, lambda: not panel.running)
        panel.close()


def test_close_cancels_network_worker_without_destroying_it(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    class Client:
        def __init__(self, config):
            pass
        def check(self, version, cancel):
            cancel.wait(5)
            return None
    monkeypatch.setattr(panel_module, 'ReleaseClient', Client)
    panel = panel_module.UpdatesPanel(tmp_path)
    panel.owner_edit.setText('Teacher')
    panel.repo_edit.setText('ControlLab')
    panel.check_for_updates()
    assert panel.running
    panel.shutdown()
    until(app, lambda: not panel.running)
    assert panel.shutdown()
    panel.close()


def test_recovery_rechecks_cache_displays_log_and_requires_explicit_retry(monkeypatch,tmp_path):
    app=QApplication.instance() or QApplication([])
    path=download_release(release(),tmp_path/'updates/downloads',transport=Transport())
    (path.parent/'installer.log').write_text('previous installation cancelled',encoding='utf-8')
    panel=panel_module.UpdatesPanel(tmp_path)
    ready=[]
    panel.readyToInstall.connect(ready.append)
    try:
        assert panel.cache_combo.count()==0 and ready==[]
        panel.refresh_cache()
        until(app,lambda:not panel.running)
        app.processEvents()
        assert panel.cache_combo.count()==1 and panel.retry_install_button.isEnabled()
        assert panel.view_log_button.isEnabled()
        panel.view_installer_log()
        assert 'previous installation cancelled' in panel.release_notes.toPlainText()
        monkeypatch.setattr(QMessageBox,'question',lambda *args,**kwargs:QMessageBox.StandardButton.No)
        panel.retry_cached_installation()
        assert ready==[]
        monkeypatch.setattr(QMessageBox,'question',lambda *args,**kwargs:QMessageBox.StandardButton.Yes)
        panel.retry_cached_installation()
        assert ready==[path]
        path.write_bytes(b'tampered after recovery scan')
        panel.retry_cached_installation()
        assert ready==[path] and '校验失败' in panel.status_label.text()
        panel.refresh_cache()
        until(app,lambda:not panel.running)
        app.processEvents()
        assert not panel.retry_install_button.isEnabled() and panel.view_log_button.isEnabled()
    finally:
        panel.shutdown();until(app,lambda:not panel.running);panel.close()
