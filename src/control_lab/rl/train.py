"""Optional CPU PPO training; emits JSON progress and honors a stop-file request."""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Callable

from control_lab.core.types import integer, finite_number
from .artifacts import atomic_json, save_artifact, validate_artifact
from .env_factory import make_training_env
from .rewards import resolve_reward_config, reward_config_from_contract


@dataclass(frozen=True)
class TrainConfig:
    output_dir: Path
    total_timesteps: int = 25_600
    seed: int = 0
    reward_id: str = "survival-v1"
    stop_file: Path | None = None
    resume_from: Path | None = None
    checkpoint_interval: int = 10_240
    progress_interval: int = 256
    n_steps: int = 1024
    batch_size: int = 64
    learning_rate: float = 3e-4
    n_epochs: int = 10
    reward_config: dict | None = None

    def __post_init__(self):
        object.__setattr__(self, "output_dir", Path(self.output_dir).expanduser().resolve())
        for key, minimum in (("total_timesteps", 2), ("seed", 0), ("checkpoint_interval", 1),
                             ("progress_interval", 1), ("n_steps", 2), ("batch_size", 2), ("n_epochs", 1)):
            object.__setattr__(self, key, integer(getattr(self, key), key, minimum))
        rate = finite_number(self.learning_rate, "learning_rate")
        if rate <= 0:
            raise ValueError("Invalid learning rate or reward version")
        object.__setattr__(self, "reward_config", resolve_reward_config(self.reward_id, self.reward_config))
        object.__setattr__(self, "learning_rate", rate)
        for key in ("stop_file", "resume_from"):
            value = getattr(self, key)
            if value is not None:
                object.__setattr__(self, key, Path(value).expanduser().resolve())


def create_untrained_baseline(output_dir, *, seed=0, reward_id="survival-v1", reward_config=None, stop_file=None):
    """Save an initialized, never-updated PPO policy and its five practice rollouts."""
    from stable_baselines3 import PPO
    import torch
    from .evaluate import evaluate_model
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError("基线目录已存在，不覆盖原记录")
    config = TrainConfig(output, total_timesteps=256, seed=seed, reward_id=reward_id, reward_config=reward_config)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    env = make_training_env(seed, reward_id, config.reward_config)
    try:
        model = PPO("MlpPolicy", env, device="cpu", seed=seed, n_steps=1024, batch_size=64,
                    policy_kwargs={"net_arch": [64, 64]}, verbose=0)
        artifact = save_artifact(model, output/"artifact", reward_id=reward_id, reward_config=config.reward_config,
            status="checkpoint", training={"seed": seed, "requested_timesteps": 0, "actual_timesteps": 0,
                "hyperparameters": {"n_steps": 1024, "batch_size": 64, "net_arch": [64, 64]},
                "note": "Initialized policy baseline, model.learn was never called."})
    finally:
        env.close()
    report = evaluate_model(artifact, split="practice", output_dir=output/"evaluation", stop_file=stop_file)
    if not report.get("is_complete", True):
        from .evaluate import StopRequested
        raise StopRequested()
    return {"artifact": str(artifact), "report": str(output/"evaluation/report.json"),
            "aggregate": report["aggregate"], "training_steps": 0}


def train(config: TrainConfig, *, progress_callback: Callable[[dict], None] | None = None) -> Path:
    try:
        import torch
        from stable_baselines3 import PPO
        from stable_baselines3.common.callbacks import BaseCallback
        from stable_baselines3.common.monitor import Monitor
    except ImportError as exc:
        raise RuntimeError("Training requires the independent RL environment with Stable-Baselines3 and CPU PyTorch") from exc
    if config.output_dir.exists():
        raise FileExistsError(f"Training will not overwrite an existing directory: {config.output_dir}")
    parent_metadata = validate_artifact(config.resume_from, require_runtime=True) if config.resume_from else None
    if parent_metadata and reward_config_from_contract(parent_metadata["environment"]) != config.reward_config:
        raise ValueError("Resuming with a different reward requires a separately declared experiment")
    config.output_dir.mkdir(parents=True, exist_ok=False)
    stop_file = config.stop_file or config.output_dir / "STOP"
    started = time.monotonic()
    run_id = config.output_dir.name
    progress_path = config.output_dir / "progress.jsonl"
    def emit(kind: str, **details):
        message = {"type": kind, "run_id": run_id, "wall_time_s": time.monotonic()-started, **details}
        line = json.dumps(message, ensure_ascii=False, allow_nan=False)
        with progress_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)
        if progress_callback:
            progress_callback(dict(message))
    effective_steps = min(config.n_steps, config.total_timesteps)
    effective_batch = min(config.batch_size, effective_steps)
    hyperparameters = {"n_steps": effective_steps, "batch_size": effective_batch,
                       "learning_rate": config.learning_rate, "n_epochs": config.n_epochs,
                       "net_arch": [64, 64], "device": "cpu", "n_envs": 1,
                       "observation_normalization": "none"}
    request = {"seed": config.seed, "reward_id": config.reward_id, "reward_config": config.reward_config,
               "requested_timesteps": config.total_timesteps, "hyperparameters": hyperparameters,
               "stop_file": str(stop_file), "resume_from": str(config.resume_from) if config.resume_from else None}
    atomic_json(config.output_dir / "request.json", request)
    torch.set_num_threads(1)
    env = Monitor(make_training_env(config.seed, config.reward_id, config.reward_config))
    model = None
    status = "completed"
    initial_timesteps = 0
    lineage = None if parent_metadata is None else {
        "parent_model_sha256": parent_metadata["model_sha256"],
        "parent_metadata_sha256": parent_metadata["metadata_sha256"]}
    def training_metadata():
        return {"seed": config.seed, "requested_timesteps": config.total_timesteps,
                "actual_timesteps": int(model.num_timesteps),
                "initial_timesteps": initial_timesteps,
                "additional_timesteps": int(model.num_timesteps) - initial_timesteps,
                "hyperparameters": hyperparameters,
                "note": "PPO completes rollouts; actual steps may exceed the requested lower bound."}
    class CourseCallback(BaseCallback):
        def _on_step(self):
            nonlocal status
            additional = self.num_timesteps - initial_timesteps
            if additional % config.progress_interval == 0:
                emit("progress", step_count=int(self.num_timesteps), additional_steps=additional,
                     requested_steps=config.total_timesteps)
            if additional > 0 and additional % config.checkpoint_interval == 0:
                target = save_artifact(self.model, config.output_dir / "checkpoints" / f"step-{self.num_timesteps:09d}",
                                       training=training_metadata(), reward_id=config.reward_id,
                                       status="checkpoint", lineage=lineage, reward_config=config.reward_config)
                emit("checkpoint", step_count=int(self.num_timesteps), path=str(target))
            if stop_file.exists():
                status = "stopped"
                return False
            return True
    try:
        if config.resume_from:
            model = PPO.load(str(config.resume_from / "policy.zip"), env=env, device="cpu")
            model.set_random_seed(config.seed)
            initial_timesteps = int(model.num_timesteps)
            # A continuation preserves the saved optimizer/model settings, not new defaults.
            hyperparameters.update(n_steps=int(model.n_steps), batch_size=int(model.batch_size),
                                   learning_rate=float(model.lr_schedule(1.0)), n_epochs=int(model.n_epochs))
        else:
            model = PPO("MlpPolicy", env, device="cpu", seed=config.seed, verbose=0,
                        n_steps=effective_steps, batch_size=effective_batch,
                        learning_rate=config.learning_rate, n_epochs=config.n_epochs,
                        policy_kwargs={"net_arch": [64, 64]})
        hyperparameters.update(gamma=float(model.gamma), gae_lambda=float(model.gae_lambda),
                               clip_range=float(model.clip_range(1.0)), ent_coef=float(model.ent_coef),
                               vf_coef=float(model.vf_coef), max_grad_norm=float(model.max_grad_norm),
                               normalize_advantage=bool(model.normalize_advantage))
        atomic_json(config.output_dir / "request.json", request)
        emit("started", step_count=initial_timesteps, requested_steps=config.total_timesteps, stop_file=str(stop_file))
        if stop_file.exists():
            status = "stopped"
        else:
            try:
                model.learn(total_timesteps=config.total_timesteps, callback=CourseCallback(),
                            reset_num_timesteps=not bool(config.resume_from), progress_bar=False)
            except KeyboardInterrupt:
                status = "stopped"
        target = save_artifact(model, config.output_dir / "artifact", training=training_metadata(),
                               reward_id=config.reward_id, status=status, lineage=lineage,
                               reward_config=config.reward_config)
        emit(status, status=status, step_count=int(model.num_timesteps), path=str(target),
             additional_steps=int(model.num_timesteps)-initial_timesteps, requested_steps=config.total_timesteps,
             seed=config.seed, reward_id=config.reward_id,
             reward_custom=config.reward_id not in ("survival-v1", "balanced-v1"), resumed=bool(config.resume_from))
        atomic_json(config.output_dir / "result.json", {"status": status, "artifact": str(target),
                    "step_count": int(model.num_timesteps), "finished_at": datetime.now(timezone.utc).isoformat()})
        return target
    except Exception as exc:
        emit("error", error_type=type(exc).__name__, message=str(exc))
        atomic_json(config.output_dir / "result.json", {"status": "error", "error": str(exc)})
        raise
    finally:
        env.close()
