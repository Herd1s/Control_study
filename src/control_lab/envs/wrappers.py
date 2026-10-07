"""Gym adapter around the exact same fixed-step session used by lessons/evaluation."""
from dataclasses import asdict, replace
import gymnasium as gym
import numpy as np

from control_lab.core.scenario import configuration_hash
from control_lab.core.session import EpisodeSession


class ScenarioEnv(gym.Env):
    """An explicit frozen case. reset(seed) seeds Gym, not the case's initial state.

    To change initial conditions construct another EpisodeSpec or pass spec in
    reset(options={"spec": ...}). This avoids silently altering evaluation cases.
    """
    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 50}

    def __init__(self, spec, render_mode=None):
        self.render_mode = render_mode
        self.session = EpisodeSession(spec, render_mode=render_mode)
        self.action_space = gym.spaces.Box(-spec.force_limit_n, spec.force_limit_n, (1,), np.float32)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (4,), np.float32)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        observation = self.session.reset(spec=(options or {}).get("spec"))
        spec = self.session.spec
        self.action_space = gym.spaces.Box(-spec.force_limit_n, spec.force_limit_n, (1,), np.float32)
        info = dict(true_state=self.session.true_state.as_tuple(),
                    config_hash=configuration_hash(spec), scenario_id=spec.scenario.scenario_id,
                    target_velocity_mps=self.session.target_velocity_mps)
        return np.asarray(observation.as_tuple(), np.float32), info

    def step(self, action):
        values = np.asarray(action)
        if values.shape != (1,) or values.dtype.kind not in "fiu":
            raise ValueError("action must have shape (1,) with a real force")
        result = self.session.step(float(values[0]))
        info = asdict(result)
        # A random run ID is not part of deterministic physics or Gym equality.
        info.pop("episode_id")
        info.update(commanded_force=result.requested_force_n, applied_force=result.actuator_force_n)
        return (np.asarray(result.observed_state.as_tuple(), np.float32), result.reward,
                result.terminated, result.truncated, info)

    def render(self):
        return self.session._env.render()

    def close(self):
        self.session.close()


class NormalizedForceAction(gym.ActionWrapper):
    """Map RL action [-1,1] to the declared Newton limit, without changing physics."""
    def __init__(self, env):
        super().__init__(env)
        self.force_limit_n = float(env.action_space.high[0])
        self.action_space = gym.spaces.Box(-1.0, 1.0, (1,), np.float32)

    def action(self, action):
        values = np.asarray(action)
        if values.shape != (1,) or values.dtype.kind not in "fiu" or not np.isfinite(values).all():
            raise ValueError("normalized action must be one finite real value")
        self.force_limit_n = float(self.env.action_space.high[0])
        return np.clip(values.astype(np.float64), -1.0, 1.0) * self.force_limit_n


def make_scenario_env(spec, render_mode=None, *, normalized_action=False):
    env = ScenarioEnv(spec, render_mode=render_mode)
    return NormalizedForceAction(env) if normalized_action else env
