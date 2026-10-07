"""Local model/report index. Reads metadata and bytes, never deserializes a policy."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from control_lab.evaluation.protocol import canonical_hash
from .artifacts import atomic_json, validate_artifact


def _read_json(path, limit=10_000_000):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ValueError("Index input exceeds size limit")
    return json.loads(path.read_text(encoding="utf-8-sig"))


class ModelCatalog:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()
        self.path = self.data_dir/"training/catalog.json"

    def load(self):
        if not self.path.exists():
            return {"schema_version": 1, "model_roots": [], "report_roots": [], "entries": []}
        value = _read_json(self.path)
        if value.get("schema_version") != 1 or not all(isinstance(value.get(key), list) for key in ("model_roots", "report_roots", "entries")):
            raise ValueError("Unsupported model catalog")
        return value

    def _recoverable_load(self):
        try:
            return self.load()
        except (ValueError, OSError):
            if self.path.exists():
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
                shutil.copy2(self.path, self.path.with_name("catalog-corrupt-"+stamp+".json"))
            return {"schema_version": 1, "model_roots": [], "report_roots": [], "entries": [],
                    "notice": "原索引无法读取，已备份；模型和评价文件未更改，请重新导入外部目录。"}

    def add_model_root(self, path):
        return self._add_root(path, "model_roots")

    def add_report_root(self, path):
        return self._add_root(path, "report_roots")

    def _add_root(self, path, key):
        path = Path(path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(path)
        if key == "model_roots" and not path.is_dir():
            raise ValueError("Choose a model package or directory containing packages")
        value = self._recoverable_load()
        if str(path) not in value[key]:
            value[key].append(str(path))
        atomic_json(self.path, value)
        return path

    def refresh(self):
        value = self._recoverable_load()
        model_roots = [self.data_dir/"training/runs", *map(Path, value["model_roots"])]
        report_roots = [self.data_dir/"training/runs", *map(Path, value["report_roots"])]
        model_files, report_files = set(), set()
        warnings = []
        for roots, filename, target in ((model_roots, "metadata.json", model_files), (report_roots, "report.json", report_files)):
            for root in roots:
                if root.is_file():
                    target.add(root.resolve())
                elif root.is_dir():
                    for path in root.rglob(filename):
                        if path.is_file():
                            target.add(path.resolve())
                        if len(target) >= 5000:
                            warnings.append("索引达到5000文件上限，请导入更具体的目录。")
                            break
        reports = []
        for path in sorted(report_files):
            try:
                report = _read_json(path)
                snapshot_path = path.parent/"controller_snapshot.json"
                snapshot = _read_json(snapshot_path)
                identity = snapshot.get("configuration", {})
                if canonical_hash(snapshot) != report.get("controller_sha256"):
                    raise ValueError("Report controller fingerprint differs from its snapshot")
                if not identity.get("model_sha256") or not identity.get("metadata_sha256"):
                    continue  # Traditional controllers belong in the experiment library.
                status = report.get("status", "completed")
                complete = status == "completed" and report.get("is_complete", True)
                usable_validation = False
                if report.get("split") == "validation" and complete:
                    from .evaluate import validation_fingerprint
                    validation_fingerprint(path)
                    usable_validation = True
                reports.append({"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "model_sha256": identity["model_sha256"], "metadata_sha256": identity["metadata_sha256"],
                    "controller_sha256": report["controller_sha256"], "split": report.get("split"),
                    "protocol_id": report.get("protocol_id"), "protocol_hash": report.get("protocol_hash"),
                    "cases_hash": report.get("cases_hash"), "aggregate": report.get("aggregate"),
                    "status": status, "is_complete": complete, "usable_validation": usable_validation,
                    "source_snapshot": str(snapshot_path)})
            except (OSError, ValueError, KeyError, TypeError) as exc:
                warnings.append(f"评价未关联：{path}：{exc}")
        entries = []
        for path in sorted(model_files):
            entry = {"path": str(path.parent), "valid": False, "reports": []}
            try:
                metadata = validate_artifact(path.parent)
                training = metadata["training"]
                entry.update(valid=True, model_sha256=metadata["model_sha256"], metadata_sha256=metadata["metadata_sha256"],
                    seed=training["seed"], actual_steps=training["actual_timesteps"], requested_steps=training["requested_timesteps"],
                    reward_id=metadata["environment"]["reward_id"], reward_definition=metadata["environment"]["reward_definition"],
                    created_at=metadata["created_at"], status=metadata["status"], source=metadata.get("source"),
                    lineage=metadata.get("lineage"), hyperparameters=training.get("hyperparameters"),
                    reports=[report for report in reports if report["model_sha256"] == metadata["model_sha256"]
                             and report["metadata_sha256"] == metadata["metadata_sha256"]])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                entry["error"] = str(exc)
            entries.append(entry)
        value.update(entries=sorted(entries, key=lambda entry: entry.get("created_at", ""), reverse=True),
                     warnings=warnings, updated_at=datetime.now(timezone.utc).isoformat())
        # A completed background scan must not discard a directory imported while it ran.
        try:
            latest = self.load()
        except (ValueError, OSError):
            latest = value
        for key in ("model_roots", "report_roots"):
            value[key] = sorted(set(value[key]) | set(latest[key]))
        atomic_json(self.path, value)
        return value
