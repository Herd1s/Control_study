"""Deterministic policy inference, with exactly one action conversion to Newtons."""
from pathlib import Path
import hashlib
import json
import numpy as np

from control_lab.evaluation import evaluate, load_protocol
from .artifacts import validate_artifact


class StopRequested(BaseException):
    """Cooperative cancellation, deliberately not a controller failure."""


class PPOPolicyAdapter:
    def __init__(self, model, metadata: dict, stop_file=None):
        self._model = model
        self._metadata = metadata
        self.model_sha256 = metadata["model_sha256"]
        self.metadata_sha256 = metadata["metadata_sha256"]
        self._stop_file = Path(stop_file) if stop_file else None

    def reset(self):
        # MLP policy has no recurrent hidden state or running observation statistics.
        return None

    def act(self, observation, dt):
        if self._stop_file and self._stop_file.exists():
            raise StopRequested()
        values = observation.as_tuple() if hasattr(observation, "as_tuple") else observation
        values = np.asarray(values, dtype=np.float32)
        if values.shape != (4,) or not np.isfinite(values).all():
            raise ValueError("PPO needs four finite observations in x/v/theta/omega order")
        action, _ = self._model.predict(values, deterministic=True)
        action = np.asarray(action)
        if action.shape != (1,) or action.dtype.kind not in "fiu" or not np.isfinite(action).all():
            raise ValueError("PPO must produce one finite normalized action")
        return float(np.clip(action[0], -1.0, 1.0) * 10.0)

    def evaluation_identity(self):
        return {"algorithm": "PPO", "policy": "MlpPolicy", "model_sha256": self.model_sha256,
                "metadata_sha256": self.metadata_sha256,
                "training_environment_hash": self._metadata["environment_hash"],
                "observation_order": ["x", "v", "theta", "omega"],
                "observation_units": ["m", "m/s", "rad", "rad/s"],
                "observation_normalization": "none", "action_scale_n": 10.0,
                "predict_deterministic": True}


def load_policy_adapter(artifact_dir: Path, *, stop_file=None) -> PPOPolicyAdapter:
    artifact_dir = Path(artifact_dir).resolve()
    metadata = validate_artifact(artifact_dir, require_runtime=True)
    # Optional dependency is intentionally absent from module-level imports.
    try:
        from stable_baselines3 import PPO
    except ImportError as exc:
        raise RuntimeError("Use the separately configured RL Python environment to load PPO models") from exc
    model = PPO.load(str(artifact_dir / "policy.zip"), device="cpu")
    if model.observation_space.shape != (4,) or model.action_space.shape != (1,):
        raise ValueError("Loaded policy spaces do not match metadata")
    if not np.allclose(model.action_space.low, -1) or not np.allclose(model.action_space.high, 1):
        raise ValueError("Loaded policy does not use normalized force actions")
    return PPOPolicyAdapter(model, metadata, stop_file=stop_file)


def validation_fingerprint(report_path):
    """Freeze an actual complete validation report, never a selected best episode."""
    path = Path(report_path).resolve()
    if path.stat().st_size > 5_000_000:
        raise ValueError("验证报告过大")
    raw = path.read_bytes()
    report = json.loads(raw)
    protocol = load_protocol("balance-v1", split="validation")
    if report.get("status", "completed") != "completed" or not report.get("is_complete", True):
        raise ValueError("未完成或已取消的验证报告不能冻结")
    if (report.get("split") != "validation" or report.get("protocol_hash") != protocol.protocol_hash
            or report.get("cases_hash") != protocol.cases_hash or report.get("input_mode") != "force_n"):
        raise ValueError("保留测试需要当前balance-v1协议的完整验证报告")
    expected = [case.case_id for case in protocol.cases]
    if ([item.get("case_id") for item in report.get("episodes", [])] != expected
            or report.get("aggregate", {}).get("episodes") != len(expected)):
        raise ValueError("验证报告缺少用例，不能冻结")
    if [item.get("initial_state") for item in report["episodes"]] != [list(case.initial_state) for case in protocol.cases]:
        raise ValueError("验证报告初始状态与固定用例不符")
    fingerprint = report.get("controller_sha256")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("验证报告缺少控制器指纹")
    return fingerprint, {"validation_report": str(path), "validation_report_sha256": hashlib.sha256(raw).hexdigest(),
                         "frozen_controller_sha256": fingerprint}


def evaluate_model(artifact_dir: Path, split="validation", output_dir: Path | None = None,
                   *, frozen_controller_sha256: str | None = None, stop_file=None,
                   validation_report=None) -> dict:
    if split == "test":
        split = "held_out"
    evidence = None
    if validation_report is not None:
        declared, evidence = validation_fingerprint(validation_report)
        if frozen_controller_sha256 and frozen_controller_sha256 != declared:
            raise ValueError("填写的模型指纹与所选验证报告不一致")
        frozen_controller_sha256 = declared
    if split == "held_out" and not frozen_controller_sha256:
        raise ValueError("Held-out evaluation needs the frozen validation controller fingerprint")
    adapter = load_policy_adapter(artifact_dir, stop_file=stop_file)
    metadata = adapter._metadata
    report = evaluate(lambda: adapter, load_protocol("balance-v1", split=split),
                    output_dir=output_dir, controller_name=f"ppo_seed{metadata['training']['seed']}",
                    allow_held_out=(split == "held_out"), expected_controller_sha256=frozen_controller_sha256,
                    cancel_requested=(lambda: Path(stop_file).exists()) if stop_file else None)
    if evidence:
        report["freeze_evidence"] = evidence
        if output_dir is not None:
            from .artifacts import atomic_json
            atomic_json(Path(output_dir)/"report.json", report)
    return report
