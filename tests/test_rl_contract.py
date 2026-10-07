import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from control_lab.core.scenario import ScenarioConfig
from control_lab.core.types import EpisodeSpec, State
from control_lab.envs.wrappers import make_scenario_env
from control_lab.evaluation.protocol import canonical_hash
from control_lab.rl.artifacts import save_artifact, validate_artifact
from control_lab.rl.env_factory import make_training_env, environment_contract
from control_lab.rl.evaluate import PPOPolicyAdapter
from control_lab.rl.rewards import reward_components
from control_lab.rl.train import TrainConfig


def test_importing_rl_modules_does_not_import_torch():
    code = "import sys; import control_lab.rl.train, control_lab.rl.evaluate; assert 'torch' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


def test_gym_checker_seed_distribution_and_action_mapping():
    env = make_training_env(seed=5)
    try:
        check_env(env, skip_render_check=True)
        first, info = env.reset(seed=42)
        same, _ = env.reset(seed=42)
        np.testing.assert_array_equal(first, same)
        assert first.dtype == np.float32 and abs(first[2]) >= .01
        following, _ = env.reset()
        assert not np.array_equal(first, following)
        for action in (-1.0, 0.0, 1.0, 10.0):
            env.reset(seed=42)
            observation, reward, terminated, truncated, info = env.step(np.array([action], np.float32))
            assert observation.dtype == np.float32
            assert info["actuator_force_n"] == np.clip(action, -1, 1)*10
            assert reward == 1.0
            assert type(terminated) is bool and type(truncated) is bool
        with pytest.raises(ValueError):
            env.step([float("nan")])
    finally:
        env.close()


def test_normalized_training_matches_explicit_newton_physics():
    env = make_training_env(seed=1)
    observation, _ = env.reset(seed=51)
    spec = EpisodeSpec("comparison", ScenarioConfig("same", State.from_sequence(observation)),
                       theta_limit_rad=environment_contract()["termination"]["theta_limit_rad"])
    # Start from the double-precision state actually provided by reset metadata.
    _, initial_info = env.reset(seed=51)
    spec = EpisodeSpec("comparison", ScenarioConfig("same", State(*initial_info["initial_state"])),
                       theta_limit_rad=environment_contract()["termination"]["theta_limit_rad"])
    reference = make_scenario_env(spec)
    try:
        reference.reset(seed=51)
        for normalized in (.1, -.2, .3, 0):
            a = env.step(np.array([normalized], np.float64))
            b = reference.step(np.array([normalized*10], np.float64))
            np.testing.assert_array_equal(a[0], b[0])
            assert a[2:4] == b[2:4]
    finally:
        env.close()
        reference.close()


def test_terminated_and_truncated_are_separate():
    env = make_training_env()
    try:
        env.reset(seed=42)
        for _ in range(500):
            _, _, terminated, truncated, _ = env.step([1.0])
            if terminated or truncated:
                break
        assert terminated and not truncated
        state, _ = env.reset(seed=42)
        for _ in range(500):
            x, v, theta, omega = state
            force = 60*theta + 12*omega + 2*x + 3*v
            state, _, terminated, truncated, _ = env.step([force/10])
            if terminated or truncated:
                break
        assert truncated and not terminated
    finally:
        env.close()


def test_reward_versions_use_actual_force_and_true_state():
    state = {"x": 1.2, "theta": np.deg2rad(6)}
    assert sum(reward_components("survival-v1", state, 5).values()) == 1.0
    assert sum(reward_components("balanced-v1", state, 5).values()) == pytest.approx(1-.15-.05-.005)
    with pytest.raises(ValueError):
        reward_components("guess", state, 0)


class FakeModel:
    def save(self, path):
        Path(path).write_bytes(b"trusted-test-model-content")

    def predict(self, observation, deterministic):
        assert deterministic and observation.shape == (4,)
        return np.array([.25], np.float32), None


def make_fake_artifact(path):
    return save_artifact(FakeModel(), path, training={"seed": 0, "requested_timesteps": 256,
                         "actual_timesteps": 256}, reward_id="survival-v1", status="completed")


def test_artifact_integrity_and_adapter_identity(tmp_path):
    artifact = make_fake_artifact(tmp_path / "model")
    metadata = validate_artifact(artifact)
    adapter = PPOPolicyAdapter(FakeModel(), metadata)
    assert adapter.act([0, 0, .01, 0], .02) == 2.5
    assert adapter.evaluation_identity()["model_sha256"] == metadata["model_sha256"]
    with pytest.raises(FileExistsError):
        make_fake_artifact(artifact)
    (artifact / "policy.zip").write_bytes(b"changed")
    with pytest.raises(ValueError, match="hash"):
        validate_artifact(artifact)


@pytest.mark.parametrize("field,value", [("observation_normalization", "VecNormalize"),
                                        ("model_file", "../policy.zip"), ("algorithm", "SAC")])
def test_rehashed_incompatible_metadata_still_rejected(tmp_path, field, value):
    artifact = make_fake_artifact(tmp_path / "model")
    path = artifact / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata[field] = value
    metadata.pop("metadata_sha256")
    metadata["metadata_sha256"] = canonical_hash(metadata)
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_artifact(artifact)


def test_model_contract_rejects_reordered_observation(tmp_path):
    artifact = make_fake_artifact(tmp_path / "model")
    path = artifact / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["environment"]["observation"]["fields"] = ["theta", "omega", "x", "v"]
    metadata["environment_hash"] = canonical_hash(metadata["environment"])
    metadata.pop("metadata_sha256")
    metadata["metadata_sha256"] = canonical_hash(metadata)
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ValueError, match="contract"):
        validate_artifact(artifact)


def test_training_config_validates_input_without_importing_torch(tmp_path):
    assert TrainConfig(tmp_path / "run").total_timesteps == 25600
    for args in ({"seed": True}, {"total_timesteps": 0}, {"learning_rate": float("nan")},
                 {"reward_id": "unknown"}):
        with pytest.raises((TypeError, ValueError)):
            TrainConfig(tmp_path / "run", **args)
