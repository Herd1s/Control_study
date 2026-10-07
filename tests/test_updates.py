import hashlib
import io
import json
from pathlib import Path
import threading
from types import SimpleNamespace
from urllib.request import Request
import pytest

from control_lab.updates.releases import (
    RepositoryConfig, ReleaseInfo, ReleaseClient, UpdateCancelled, UpdateError,
    _SafeRedirect, checksum_from_sums, load_config, save_config, validate_https_url,
)
from control_lab.updates.download import download_release
from control_lab.updates.installer import confirm_installation, launch_installer, verify_cached_installer

PAYLOAD = b'MZ-control-lab-test-installer-not-executable'
HASH = hashlib.sha256(PAYLOAD).hexdigest()
REPO = RepositoryConfig('Teacher', 'ControlLab')
URL = 'https://github.com/Teacher/ControlLab/releases/download/v0.2.0/ControlLab-Setup-0.2.0.exe'


def release(**changes):
    values = dict(repository=REPO, version='0.2.0', tag='v0.2.0',
                  release_url='https://github.com/Teacher/ControlLab/releases/tag/v0.2.0',
                  notes='new lessons', filename='ControlLab-Setup-0.2.0.exe',
                  download_url=URL, size_bytes=len(PAYLOAD), sha256=HASH,
                  checksum_source='GitHub release asset digest')
    values.update(changes)
    return ReleaseInfo(**values)


class Transport:
    def __init__(self, payload=PAYLOAD, metadata=None, sums=None):
        self.payload, self.metadata, self.sums = payload, metadata, sums
        self.calls = []

    def read_bytes(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return json.dumps(self.metadata).encode() if kwargs.get('api') else self.sums

    def open(self, url):
        self.calls.append(url)
        return io.BytesIO(self.payload)


def metadata(digest=True):
    asset = dict(name=release().filename, browser_download_url=URL, size=len(PAYLOAD))
    if digest:
        asset['digest'] = 'sha256:' + HASH
    return dict(tag_name='v0.2.0', draft=False, prerelease=False,
                html_url=release().release_url, body='release notes', assets=[asset])


def test_repository_setting_is_explicit_and_separate(tmp_path):
    assert load_config(tmp_path).full_name == 'Herd1s/Control_study'
    save_config(tmp_path, REPO)
    assert load_config(tmp_path) == REPO
    assert not list(tmp_path.glob('*.json'))
    for owner, repo in [('https://github.com', 'a'), ('ok', '../bad'), ('ok', '..'), ('', 'app')]:
        with pytest.raises(ValueError):
            RepositoryConfig(owner, repo)


def test_release_digest_or_same_release_sums_and_version_comparison():
    transport = Transport(metadata=metadata())
    client = ReleaseClient(REPO, transport)
    assert client.check('0.1.0').sha256 == HASH
    assert client.check('0.2.0') is None
    sums_metadata = metadata(False)
    sums_metadata['assets'].append(dict(name='SHA256SUMS', browser_download_url=URL.rsplit('/', 1)[0] + '/SHA256SUMS'))
    found = ReleaseClient(REPO, Transport(metadata=sums_metadata, sums=(HASH + '  ' + release().filename + '\n').encode())).check('0.1.0')
    assert found.sha256 == HASH and 'same release' in found.checksum_source
    with pytest.raises(UpdateError, match='校验信息'):
        ReleaseClient(REPO, Transport(metadata=metadata(False))).check('0.1.0')
    with pytest.raises(UpdateError):
        checksum_from_sums((HASH + '  ' + release().filename + '\n') * 2, release().filename)


def test_source_filename_and_redirect_restrictions():
    for url in ('http://github.com/a/b', 'https://github.com.evil.test/a',
                'https://127.0.0.1/app', 'https://user:pass@github.com/a', 'https://github.com:444/a'):
        with pytest.raises(UpdateError):
            validate_https_url(url)
    handler = _SafeRedirect()
    with pytest.raises(UpdateError):
        handler.redirect_request(Request(URL), None, 302, '', {}, 'http://github.com/unsafe')
    with pytest.raises(UpdateError):
        release(filename='../ControlLab.exe')
    with pytest.raises(UpdateError):
        release(download_url=URL.replace('/Teacher/', '/Other/'))
    assert release(download_url=URL.replace('/Teacher/', '/teacher/'))


def test_valid_download_and_handoff_revalidate_before_launch(tmp_path):
    path = download_release(release(), tmp_path / 'cache', transport=Transport())
    assert path.read_bytes() == PAYLOAD
    assert verify_cached_installer(path, tmp_path / 'cache').sha256 == HASH
    calls = []
    def launcher(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return SimpleNamespace(pid=12345)
    launch_installer(path, tmp_path / 'cache', popen=launcher)
    assert calls[0][0][0] == str(path)
    assert '/NORESTART' in calls[0][0]
    assert '/SILENT' not in calls[0][0]
    assert json.loads((path.parent / 'handoff.json').read_text())['completed'] is False
    path.write_bytes(b'tampered')
    with pytest.raises(UpdateError, match='校验失败'):
        launch_installer(path, tmp_path / 'cache', popen=launcher)
    assert len(calls) == 1


@pytest.mark.parametrize('bad', [b'X'*len(PAYLOAD), PAYLOAD[:-1], PAYLOAD+b'extra'])
def test_failed_download_removes_partial_but_preserves_old_files(tmp_path, bad):
    old = tmp_path / 'old-install.exe'
    old.write_bytes(b'old version')
    with pytest.raises(UpdateError):
        download_release(release(), tmp_path / 'cache', transport=Transport(payload=bad))
    assert old.read_bytes() == b'old version'
    assert not list((tmp_path / 'cache').rglob('*.part'))
    assert not list((tmp_path / 'cache').rglob('*.exe'))


def test_cancelled_and_network_failed_download_do_not_publish(tmp_path):
    cancel = threading.Event()
    def progress(done, total):
        cancel.set()
    with pytest.raises(UpdateCancelled):
        download_release(release(), tmp_path, transport=Transport(), cancel_event=cancel, progress=progress)
    assert not list(tmp_path.rglob('*.exe'))
    class Broken(Transport):
        def open(self, url):
            raise TimeoutError('network deadline')
    with pytest.raises(TimeoutError):
        download_release(release(), tmp_path, transport=Broken())
    assert not list(tmp_path.rglob('*.part'))


def test_completion_requires_success_marker_and_matching_version(tmp_path):
    path = download_release(release(), tmp_path / 'cache', transport=Transport())
    launch_installer(path, tmp_path / 'cache', popen=lambda *a, **k: SimpleNamespace(pid=1))
    app_dir = tmp_path / 'installed-app'
    app_dir.mkdir()
    assert confirm_installation(tmp_path / 'cache', app_dir, '0.2.0') == []
    (app_dir / 'installation.json').write_text(json.dumps(dict(
        schema_version=1, status='installed_successfully', version='0.2.0')))
    assert confirm_installation(tmp_path / 'cache', app_dir, '0.1.0') == []
    assert confirm_installation(tmp_path / 'cache', app_dir, '0.2.0') == [path.parent / 'handoff.json']
    assert json.loads((path.parent / 'handoff.json').read_text())['completed'] is True


def test_installer_launch_failure_has_no_completion_claim(tmp_path):
    path = download_release(release(), tmp_path / 'cache', transport=Transport())
    def unavailable(*args, **kwargs):
        raise OSError('could not start installer')
    with pytest.raises(UpdateError, match='未能启动'):
        launch_installer(path, tmp_path / 'cache', popen=unavailable)
    assert path.is_file()  # Verified file remains available for a deliberate retry.
    assert not (path.parent / 'handoff.json').exists()
