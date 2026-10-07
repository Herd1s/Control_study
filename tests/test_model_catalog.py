import json
from pathlib import Path

from control_lab.evaluation import evaluate, load_protocol
from control_lab.rl.artifacts import save_artifact, validate_artifact
from control_lab.rl.catalog import ModelCatalog
from control_lab.rl.evaluate import PPOPolicyAdapter
import numpy as np


class Model:
    def save(self, path):
        Path(path).write_bytes(b"fixture-model-bytes")
    def predict(self, observation, deterministic=True):
        return np.zeros(1), None


def model_package(folder):
    return save_artifact(Model(), folder, training={"seed":2,"requested_timesteps":256,"actual_timesteps":256},
                         reward_id="balanced-v1", status="completed")


def test_catalog_hashes_metadata_and_binds_actual_report_snapshot(tmp_path):
    artifact = model_package(tmp_path/"external/model")
    adapter = PPOPolicyAdapter(Model(), validate_artifact(artifact))
    report_folder = tmp_path/"external/validation"
    evaluate(lambda:adapter, load_protocol(split="validation"), output_dir=report_folder)
    catalog = ModelCatalog(tmp_path/"userdata")
    catalog.add_model_root(artifact.parent)
    catalog.add_report_root(report_folder/"report.json")
    result = catalog.refresh()
    entry = result["entries"][0]
    assert entry["valid"] and entry["seed"] == 2
    assert entry["actual_steps"] == entry["requested_steps"] == 256
    assert entry["reports"][0]["usable_validation"]
    assert entry["reports"][0]["source_snapshot"].endswith("controller_snapshot.json")
    # A report cannot be attached by merely claiming a model path/name.
    path = report_folder/"controller_snapshot.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["configuration"]["model_sha256"] = "0"*64
    path.write_text(json.dumps(snapshot),encoding="utf-8")
    result = catalog.refresh()
    assert not result["entries"][0]["reports"] and result["warnings"]
    (artifact/"policy.zip").write_bytes(b"tampered")
    entry = catalog.refresh()["entries"][0]
    assert not entry["valid"] and "hash" in entry["error"]


def test_broken_index_backed_up_and_model_files_unchanged(tmp_path):
    artifact = model_package(tmp_path/"training/runs/first/artifact")
    before = {path.name:path.read_bytes() for path in artifact.iterdir()}
    catalog = ModelCatalog(tmp_path)
    catalog.path.parent.mkdir(parents=True,exist_ok=True)
    catalog.path.write_text("broken-index",encoding="utf-8")
    result = catalog.refresh()
    assert result["entries"][0]["valid"] and result["notice"]
    assert len(list(catalog.path.parent.glob("catalog-corrupt-*.json"))) == 1
    assert before == {path.name:path.read_bytes() for path in artifact.iterdir()}


def test_catalog_dialog_selects_verified_model_and_validation_origin(tmp_path):
    import os
    import time
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from control_lab.desktop.panels.training import ModelCatalogDialog
    app = QApplication.instance() or QApplication([])
    artifact = model_package(tmp_path/"training/runs/example/artifact")
    adapter = PPOPolicyAdapter(Model(), validate_artifact(artifact))
    report_dir = tmp_path/"training/runs/validation"
    evaluate(lambda:adapter, load_protocol(split="validation"), output_dir=report_dir)
    dialog = ModelCatalogDialog(ModelCatalog(tmp_path))
    selected = []
    dialog.selected.connect(lambda model, report:selected.append((model,report)))
    deadline = time.monotonic()+30
    while dialog._worker:
        assert time.monotonic() < deadline
        QTest.qWait(20)
        time.sleep(.001)  # Let the Python scanner run while the test pumps Qt without app.exec().
    assert dialog.table.rowCount() == 1
    assert dialog.reports.currentData()["usable_validation"]
    assert dialog.use_selection()
    assert selected == [(str(artifact.resolve()),str((report_dir/"report.json").resolve()))]
    dialog.close()
