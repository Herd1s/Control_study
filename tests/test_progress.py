import json
from pathlib import Path

import pytest

from control_lab.storage.progress import ProgressStore


def test_progress_roundtrip_and_unique_homework(tmp_path):
    store = ProgressStore(tmp_path)
    store.save_lesson("L05", {"completed_step_ids": ["step_01"], "content_version": 1})
    assert ProgressStore(tmp_path).get_lesson("L05")["completed_step_ids"] == ["step_01"]
    first = store.save_workspace("L05", "original")
    second = store.save_workspace("L05", "my edits")
    assert first != second and first.read_text() == "original" and second.read_text() == "my edits"
    with pytest.raises(ValueError):
        store.save_workspace("L05", "oops", "../outside.py")
    assert not list(store.path.parent.glob("*.tmp"))


def test_corrupt_progress_recovers_last_successful_backup(tmp_path):
    store = ProgressStore(tmp_path)
    store.save_lesson("L01", {"step_index": 1})
    store.save_lesson("L01", {"step_index": 2})
    store.path.write_text("{broken", encoding="utf-8")
    assert store.load()["lessons"]["L01"]["step_index"] == 1
    assert "恢复" in store.last_notice
    damaged = list((tmp_path / "backups").glob("*damaged*"))
    assert damaged and damaged[0].read_text() == "{broken"
    assert json.loads(store.path.read_text())["lessons"]["L01"]["step_index"] == 1


def test_v0_migration_keeps_backup_and_unknown_future_version(tmp_path):
    store = ProgressStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    old = {"lesson_id": "L03", "completed_step_ids": ["step_01"]}
    store.path.write_text(json.dumps(old), encoding="utf-8")
    migrated = store.load()
    assert migrated["schema_version"] == 1
    assert migrated["lessons"]["L03"]["completed_step_ids"] == ["step_01"]
    backup = list((tmp_path / "backups").glob("*migration-v0*"))
    assert len(backup) == 1 and json.loads(backup[0].read_text()) == old
    store.path.write_text('{"schema_version":999,"lessons":{}}', encoding="utf-8")
    before = store.path.read_bytes()
    with pytest.raises(ValueError):
        store.save_lesson("L01", {})
    assert store.path.read_bytes() == before


def test_failed_atomic_replace_preserves_previous_profile(tmp_path, monkeypatch):
    store = ProgressStore(tmp_path)
    store.save_lesson("L01", {"step_index": 1})
    before = store.path.read_bytes()
    import control_lab.storage.progress as progress
    real_replace = progress.os.replace
    def fail_profile(source, destination):
        if Path(destination) == store.path:
            raise OSError("simulated full disk")
        return real_replace(source, destination)
    monkeypatch.setattr(progress.os, "replace", fail_profile)
    with pytest.raises(OSError):
        store.save_lesson("L01", {"step_index": 2})
    assert store.path.read_bytes() == before
    assert not list(store.path.parent.glob("*.tmp"))
