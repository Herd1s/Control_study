"""Exercise the shipped PowerShell selector without installing any dependencies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "setup-rl.ps1"
POWERSHELL = Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
pytestmark = pytest.mark.skipif(os.name != "nt" or not POWERSHELL.is_file(), reason="Windows deployment script")


def run(bundle):
    return subprocess.run([str(POWERSHELL), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(bundle / "setup-rl.ps1"), "-ValidateOnly"],
                          capture_output=True, text=True, timeout=20,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


@pytest.fixture
def bundle(tmp_path):
    shutil.copyfile(SCRIPT, tmp_path / "setup-rl.ps1")
    (tmp_path / "control_lab-0.2.0-py3-none-any.whl").write_bytes(b"old runtime lacks task_runner")
    content = b"new runtime includes tasks and catalog"
    (tmp_path / "control_lab-0.2.1-py3-none-any.whl").write_bytes(content)
    manifest = {"schema_version": 1, "app_version": "0.2.1",
                "wheel_filename": "control_lab-0.2.1-py3-none-any.whl",
                "wheel_sha256": hashlib.sha256(content).hexdigest()}
    (tmp_path / "runtime-manifest.json").write_text(json.dumps(manifest), encoding="utf-8-sig")
    return tmp_path


def test_manifest_selects_matching_wheel_when_old_wheel_remains(bundle):
    result = run(bundle)
    assert result.returncode == 0, result.stderr
    selected = json.loads(result.stdout)
    assert selected["app_version"] == "0.2.1"
    assert Path(selected["wheel"]).name == "control_lab-0.2.1-py3-none-any.whl"
    assert (bundle / "control_lab-0.2.0-py3-none-any.whl").read_bytes() == b"old runtime lacks task_runner"
    assert not (bundle / ".venv-rl").exists()


@pytest.mark.parametrize("failure, expected", [("missing_manifest", "missing"),
    ("invalid_json", "unreadable"), ("wrong_filename", "does not match"),
    ("missing_wheel", "is missing"), ("tampered_wheel", "SHA256 mismatch")])
def test_invalid_bundle_fails_before_installing_anything(bundle, failure, expected):
    manifest_path = bundle / "runtime-manifest.json"
    if failure == "missing_manifest":
        manifest_path.unlink()
    elif failure == "invalid_json":
        manifest_path.write_text("{broken")
    elif failure == "wrong_filename":
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        manifest["wheel_filename"] = "control_lab-0.2.0-py3-none-any.whl"
        manifest_path.write_text(json.dumps(manifest))
    elif failure == "missing_wheel":
        (bundle / "control_lab-0.2.1-py3-none-any.whl").unlink()
    else:
        (bundle / "control_lab-0.2.1-py3-none-any.whl").write_bytes(b"changed")
    result = run(bundle)
    assert result.returncode != 0 and expected in result.stderr, result.stdout + result.stderr
    assert not (bundle / ".venv-rl").exists()


def test_source_branch_does_not_require_distribution_manifest(bundle):
    (bundle / "pyproject.toml").write_text("[project]\nname='control-lab'\n")
    (bundle / "runtime-manifest.json").unlink()
    result = run(bundle)
    assert result.returncode == 0 and json.loads(result.stdout)["source_checkout"] is True
