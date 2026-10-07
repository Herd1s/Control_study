"""A CPU Gym training task built on the same episode engine as classroom/evaluation."""
from copy import deepcopy
import gymnasium as gym
import numpy as np

from control_lab.core.scenario import ScenarioConfig
from control_lab.core.types import EpisodeSpec, State, integer
from control_lab.envs.wrappers import make_scenario_env
from .rewards import resolve_reward_config, components_for_config

ENVIRONMENT_CONTRACT = {
    "environment_id": "control-lab-continuous-balance-training-v1",
    "evaluation_protocol": "balance-v1",
    "physics": {"gravity_m_s2": 9.8, "cart_mass_kg": 1.0, "pole_mass_kg": 0.1,
                "pole_half_length_m": 0.5, "integrator": "euler", "dt_s": 0.02},
    "observation": {"fields": ["x", "v", "theta", "omega"],
                    "units": ["m", "m/s", "rad", "rad/s"], "dtype": "float32",
                    "normalization": "none", "noise": "none", "delay_steps": 0},
    "action": {"fields": ["normalized_force"], "low": -1.0, "high": 1.0,
               "mapping": "force_n=10*clip(action,-1,1)", "force_scale_n": 10.0},
    "initial_distribution": {"low": -0.05, "high": 0.05, "reject_abs_theta_below_rad": 0.01},
    "termination": {"theta_limit_rad": 0.20943951023931953, "x_limit_m": 2.4, "max_steps": 500},
}


def environment_contract(reward_id="survival-v1", reward_config=None):
    config = resolve_reward_config(reward_id, reward_config)
    return {**deepcopy(ENVIRONMENT_CONTRACT), "reward_id": reward_id,
            "reward_definition": {key: config[key] for key in ("version", "alive", "angle", "position", "effort")}}


class TrainingEnv(gym.Env):
    metadata = {"render_modes": [], "render_fps": 50}
    render_mode = None

    def __init__(self, seed=0, reward_id="survival-v1", reward_config=None):
        self.root_seed = integer(seed, "training seed")
        self.reward_config = resolve_reward_config(reward_id, reward_config)
        self.contract = environment_contract(reward_id, self.reward_config)
        self.reward_id = reward_id
        self.action_space = gym.spaces.Box(-1.0, 1.0, (1,), np.float32)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (4,), np.float32)
        self._base_env = None
        self._first_reset = True

    def reset(self, *, seed=None, options=None):
        if options:
            raise ValueError("Training reset does not accept arbitrary evaluation cases")
        if seed is not None:
            seed = integer(seed, "reset seed")
        elif self._first_reset:
            seed = self.root_seed
        super().reset(seed=seed)
        self._first_reset = False
        # Repeated reset without a seed advances this independent initial-state RNG.
        while True:
            values = self.np_random.uniform(-0.05, 0.05, 4)
            if abs(values[2]) >= 0.01:
                break
        scenario = ScenarioConfig("training-sampled-v1", State.from_sequence(values), initial_state_seed=seed)
        spec = EpisodeSpec("balance-training-v1", scenario, require_nonzero_initial=True,
                           theta_limit_rad=self.contract["termination"]["theta_limit_rad"])
        if self._base_env is None:
            self._base_env = make_scenario_env(spec, normalized_action=True)
        observation, info = self._base_env.reset(seed=seed, options={"spec": spec})
        info["reward_id"] = self.reward_id
        info["initial_state"] = [float(value) for value in values]
        return observation.astype(np.float32), info

    def step(self, action):
        if self._base_env is None:
            raise RuntimeError("Call reset() before step()")
        observation, _, terminated, truncated, info = self._base_env.step(action)
        parts = components_for_config(self.reward_config, info["true_state"], info["actuator_force_n"])
        info.update(reward_parts=parts, reward_id=self.reward_id)
        return observation.astype(np.float32), float(sum(parts.values())), terminated, truncated, info

    def close(self):
        if self._base_env is not None:
            self._base_env.close()
            self._base_env = None


def make_training_env(seed=0, reward_id="survival-v1", reward_config=None) -> TrainingEnv:
    return TrainingEnv(seed=seed, reward_id=reward_id, reward_config=reward_config)


def demonstrate_contract():
    """Actual fixed-seed examples for L25, without constructing or training PPO."""
    env = make_training_env(seed=42)
    try:
        initial, _ = env.reset(seed=42)
        mappings = []
        for value in (-1.0, 0.0, 1.0):
            env.reset(seed=42)
            observed, reward, terminated, truncated, info = env.step(np.array([value], dtype=np.float32))
            mappings.append({"normalized_action": value, "actuator_force_n": info["actuator_force_n"],
                             "observation": observed.tolist(), "reward": reward})
        examples = {}
        for name in ("zero_force", "reference_feedback"):
            observed, _ = env.reset(seed=42)
            for step in range(1, 501):
                x, v, theta, omega = observed
                force = 0.0 if name == "zero_force" else 60*theta+12*omega+2*x+3*v
                observed, reward, terminated, truncated, info = env.step(np.array([force/10], dtype=np.float32))
                if terminated or truncated:
                    break
            examples[name] = {"steps": step, "terminated": bool(terminated), "truncated": bool(truncated),
                              "end_reason": info.get("end_reason")}
        if not examples["zero_force"]["terminated"] or not examples["reference_feedback"]["truncated"]:
            raise RuntimeError("终止/时间上限演示与预期不符，请检查课程物理契约")
        return {"initial_observation": initial.tolist(), "observation_fields": ["x", "v", "theta", "omega"],
                "observation_units": ["m", "m/s", "rad", "rad/s"], "dt_s": .02,
                "mappings": mappings, "examples": examples, "policy_trained": False}
    finally:
        env.close()
