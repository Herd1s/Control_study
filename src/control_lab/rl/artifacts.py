"""Versioned model packages. Hash checks validate integrity, not publisher identity."""
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import subprocess
from uuid import uuid4

from control_lab import __version__
from control_lab.evaluation.protocol import canonical_hash
from .env_factory import environment_contract

SCHEMA_VERSION = 1


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_versions() -> dict:
    packages = {"python": platform.python_version(), "control-lab": __version__}
    for package in ("stable-baselines3", "torch", "gymnasium", "numpy"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    return packages


def source_provenance() -> dict:
    package = Path(__file__).resolve().parents[1]
    hashes = {}
    for relative in ("core/session.py", "core/types.py", "envs/cartpole.py", "envs/wrappers.py",
                     "rl/env_factory.py", "rl/rewards.py", "rl/train.py"):
        source = package / relative
        if source.is_file():
            hashes[relative] = file_sha256(source)
    project = package.parent.parent
    revision, dirty = None, None
    if (project / ".git").exists():
        try:
            result = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, timeout=5, check=False)
            if result.returncode == 0:
                revision = result.stdout.strip()
                changes = subprocess.run(["git", "-C", str(project), "status", "--porcelain"],
                                         capture_output=True, text=True, timeout=5, check=False)
                dirty = bool(changes.stdout.strip()) if changes.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {"git_revision": revision, "working_tree_dirty": dirty, "implementation_files_sha256": hashes,
            "note": "A null revision means no accessible committed repository; file hashes preserve source provenance."}


def atomic_json(path: Path, value: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def save_artifact(model, destination, *, training: dict, reward_id: str, status: str,
                  lineage: dict | None = None) -> Path:
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(f"Model package already exists: {destination}")
    if status not in {"completed", "stopped", "checkpoint"}:
        raise ValueError("Unsupported artifact state")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name("." + destination.name + ".partial-" + uuid4().hex)
    staging.mkdir(exist_ok=False)
    policy = staging / "policy.zip"
    model.save(str(policy))
    if not policy.is_file():
        raise RuntimeError("Training library did not produce policy.zip")
    contract = environment_contract(reward_id)
    metadata = {"schema_version": SCHEMA_VERSION, "created_at": datetime.now(timezone.utc).isoformat(),
                "algorithm": "PPO", "policy": "MlpPolicy", "device": "cpu", "status": status,
                "model_file": "policy.zip", "model_sha256": file_sha256(policy),
                "environment": contract, "environment_hash": canonical_hash(contract),
                "observation_normalization": "none", "dependencies": runtime_versions(),
                "source": source_provenance(),
                "training": training, "lineage": lineage,
                "interpretation": "A saved model is not a claim of balance performance; evaluate independently."}
    metadata["metadata_sha256"] = canonical_hash(metadata)
    atomic_json(staging / "metadata.json", metadata)
    if destination.exists():
        raise FileExistsError(f"Model package was created concurrently: {destination}")
    os.rename(staging, destination)
    return destination


def validate_artifact(directory, *, require_runtime=False) -> dict:
    directory = Path(directory).resolve()
    metadata_path = directory / "metadata.json"
    if not metadata_path.resolve().is_relative_to(directory):
        raise ValueError("Metadata path escapes package")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported model metadata")
    expected_hash = metadata.get("metadata_sha256")
    unhashed = {key: value for key, value in metadata.items() if key != "metadata_sha256"}
    if expected_hash != canonical_hash(unhashed):
        raise ValueError("Model metadata hash mismatch")
    if (metadata.get("algorithm"), metadata.get("policy"), metadata.get("device")) != ("PPO", "MlpPolicy", "cpu"):
        raise ValueError("Unsupported model algorithm/policy/device")
    if metadata.get("observation_normalization") != "none":
        raise ValueError("This runtime requires explicit no-observation-normalization metadata")
    if metadata.get("status") not in {"completed", "stopped", "checkpoint"}:
        raise ValueError("Model package was not completed")
    contract = metadata.get("environment", {})
    expected_contract = environment_contract(contract.get("reward_id"))
    if contract != expected_contract or metadata.get("environment_hash") != canonical_hash(expected_contract):
        raise ValueError("Model observation/action/physics/reward contract is incompatible")
    model_file = metadata.get("model_file")
    if model_file != "policy.zip":
        raise ValueError("Unexpected model filename")
    policy = directory / model_file
    if not policy.resolve().is_relative_to(directory) or not policy.is_file():
        raise ValueError("Policy path escapes package or does not exist")
    if file_sha256(policy) != metadata.get("model_sha256"):
        raise ValueError("Policy file hash mismatch")
    training = metadata.get("training")
    if not isinstance(training, dict) or type(training.get("seed")) is not int or training["seed"] < 0:
        raise ValueError("Missing training seed provenance")
    for key in ("requested_timesteps", "actual_timesteps"):
        if type(training.get(key)) is not int or training[key] < 0:
            raise ValueError("Missing actual/requested training step count")
    if require_runtime:
        actual = runtime_versions()
        for key in ("stable-baselines3", "torch", "gymnasium", "numpy"):
            if not actual[key] or actual[key] != metadata["dependencies"].get(key):
                raise ValueError(f"Runtime version differs from the model package: {key}")
    return metadata
