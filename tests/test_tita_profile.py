"""Optional robotics integration stays outside the basic Python process."""
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from control_lab.integrations.tita_profile import (
    TitaProfile, build_command, discover_profile, inspect_profile, load_profile,
    save_profile, write_run_record,
)


@pytest.fixture
def profile(tmp_path):
    ddt = tmp_path / "DDT's Lab"
    isaac = tmp_path / "Isaac Lab"
    isaac.mkdir()
    (ddt / "scripts/np3o").mkdir(parents=True)
    for relative in ("scripts/list_envs.py", "scripts/np3o/train.py", "scripts/np3o/play.py"):
        (ddt / relative).write_text("print('external test process completed')\n", encoding="utf-8")
    registry = ddt / "source/ddt_lab/ddt_lab/tasks/manager_based/locomotion/robots/tita/__init__.py"
    registry.parent.mkdir(parents=True)
    registry.write_text('gym.register(id="DDT-Velocity-Flat-Tita-v0")\n', encoding="utf-8")
    urdf = ddt / "ddt_ros2_control/urdfs/tita_description/urdf/robot.urdf"
    urdf.parent.mkdir(parents=True)
    urdf.write_text("<robot/>", encoding="utf-8")
    checkpoint = ddt / "own_model.pt"
    checkpoint.write_bytes(b"test-path-only")
    return TitaProfile(sys.executable, str(ddt), str(isaac), str(checkpoint), True, "test explicit acceptance")


def test_profile_roundtrip_and_probe_does_not_import_isaac(profile, tmp_path):
    save_profile(tmp_path, profile)
    assert load_profile(tmp_path) == profile
    before = set(sys.modules)
    report = inspect_profile(profile)
    assert report["executable"] == sys.executable
    assert report["task_registry"]["ids"] == ["DDT-Velocity-Flat-Tita-v0"]
    assert report["task_registry"]["method"] == "static_registration_declarations"
    assert not report["ready_for_smoke"]
    assert not any(name.startswith(("isaacsim", "isaaclab")) for name in set(sys.modules) - before)


def test_smoke_command_is_bounded_and_safely_quotes_paths(profile, tmp_path):
    command = build_command(profile, "smoke", tmp_path, run_tag="test_001")
    assert command.arguments[command.arguments.index("--num_envs") + 1] == "8"
    assert command.arguments[command.arguments.index("--max_iterations") + 1] == "2"
    assert "--headless" in command.arguments
    assert command.environment["OMNI_KIT_ACCEPT_EULA"] == "YES"
    assert "DDT''s Lab" in command.powershell()
    with pytest.raises(ValueError):
        build_command(profile, "train", tmp_path)
    with pytest.raises(ValueError):
        build_command(profile, "smoke", tmp_path, run_tag="../overwrite")
    with pytest.raises(ValueError, match="许可"):
        build_command(replace(profile, omniverse_eula_accepted=False), "smoke", tmp_path)
    build_command(replace(profile, omniverse_eula_accepted=False), "inspect", tmp_path)


def test_export_does_not_overwrite_old_models_and_play_uses_one_robot(profile, tmp_path):
    play = build_command(profile, "play", tmp_path, run_tag="play_one")
    assert play.arguments[play.arguments.index("--num_envs") + 1] == "1"
    assert "--headless" not in play.arguments
    export = build_command(profile, "export", tmp_path, run_tag="export_one")
    assert "--headless" in export.arguments and "--export_policy" in export.arguments
    export_path = Path(export.arguments[export.arguments.index("--export_dir") + 1])
    export_path.mkdir(parents=True)
    with pytest.raises(FileExistsError):
        build_command(profile, "export", tmp_path, run_tag="export_one")
    with pytest.raises(FileNotFoundError):
        build_command(replace(profile, checkpoint_path=""), "export", tmp_path)


def test_run_record_is_exclusive_and_records_simulation_only(profile, tmp_path):
    command = build_command(profile, "smoke", tmp_path, run_tag="one")
    record = write_run_record(tmp_path, command, exit_code=0, status="completed", log_path=tmp_path / "one.log")
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["hardware_control"] is False
    assert data["exit_code"] == 0
    with pytest.raises(FileExistsError):
        write_run_record(tmp_path, command, exit_code=0, status="completed", log_path="same.log")


def test_discovery_only_inherits_explicit_existing_eula(tmp_path):
    root = tmp_path / "workspace"
    learning = root / "tita_learning"
    learning.mkdir(parents=True)
    (learning / "local_config.json").write_text(json.dumps({"base_python": sys.executable,
                                                            "omniverse_eula_accepted": True}), encoding="utf-8")
    assert discover_profile(root).omniverse_eula_accepted is True
    assert discover_profile(tmp_path / "absent").omniverse_eula_accepted is False


def test_tita_panel_runs_external_process_asynchronously(profile, tmp_path):
    from control_lab.desktop.panels.tita import TitaPanel
    application = QApplication.instance() or QApplication([])
    save_profile(tmp_path, profile)
    panel = TitaPanel(tmp_path)
    completed = QSignalSpy(panel.runFinished)
    panel.start("smoke")
    deadline = time.monotonic() + 8
    while completed.count() == 0 and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    try:
        assert completed.count() == 1
        result = completed.at(0)[0]
        assert result["status"] == "completed"
        assert result["exit_code"] == 0
        assert "external test process completed" in panel.output.toPlainText()
        assert not panel.running
        assert Path(result["record_path"]).is_file()
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        application.processEvents()


def test_tita_panel_can_stop_its_own_external_process(profile, tmp_path):
    from control_lab.desktop.panels.tita import TitaPanel
    application = QApplication.instance() or QApplication([])
    script = Path(profile.ddt_root) / "scripts/np3o/train.py"
    script.write_text("import time\nprint('started', flush=True)\ntime.sleep(30)\n", encoding="utf-8")
    save_profile(tmp_path, profile)
    panel = TitaPanel(tmp_path)
    completed = QSignalSpy(panel.runFinished)
    panel.start("smoke")
    QTest.qWait(50)
    panel.stop()
    deadline = time.monotonic() + 6
    while completed.count() == 0 and time.monotonic() < deadline:
        application.processEvents()
        QTest.qWait(10)
    try:
        assert completed.count() == 1
        assert completed.at(0)[0]["status"] == "cancelled"
        assert not panel.running
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        application.processEvents()
