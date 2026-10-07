"""Continuous-force CartPole, sharing Gymnasium's physics and rendering.

Actions are arrays of shape (1,) containing force in newtons. The inner
CartPole-v1 still uses its discrete action to choose direction; its force_mag
is set on every step. Its observations, reward and termination are unchanged.
Use make_env(), not gym.make(CONTINUOUS_ENV_ID); the name is a local identifier.
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np

from control_lab.core.types import finite_number

CONTINUOUS_ENV_ID = "CartPoleContinuousForce-v0"
MAX_FORCE_NEWTONS = 10.0


class ContinuousForceCartPole(gym.Wrapper):
    """Observation: [x (m), x_dot (m/s), theta (rad), theta_dot (rad/s)]."""

    def __init__(self, env: gym.Env) -> None:
        super().__init__(env)
        self.action_space = gym.spaces.Box(
            low=-MAX_FORCE_NEWTONS,
            high=MAX_FORCE_NEWTONS,
            shape=(1,),
            dtype=np.float32,
        )
        self.dt = float(self.env.unwrapped.tau)
        self.force_limit_n = MAX_FORCE_NEWTONS

    def step(self, action: Any):
        """Validate and clip requested force; log requested and actual values."""
        try:
            raw = np.asarray(action)
            if raw.dtype.kind not in "fiu":
                raise ValueError("action must contain real numbers, not booleans or strings")
            values = np.asarray(action, dtype=np.float64)
        except (TypeError, ValueError) as exc:
            raise ValueError("action must be a finite numeric array with shape (1,)") from exc
        if values.shape != (1,):
            raise ValueError(f"action must have shape (1,), received {values.shape}")
        if not np.isfinite(values).all():
            raise ValueError("action must contain a finite force in newtons")
        return self.step_force(float(values[0]))

    def step_force(self, force_n: float, disturbance_force_n: float = 0.0):
        """Clip the actuator request, then add the external force without clipping it."""
        requested = finite_number(force_n, "force")
        disturbance = finite_number(disturbance_force_n, "disturbance")
        limit = finite_number(self.force_limit_n, "force limit")
        if limit <= 0:
            raise ValueError("force limit must be positive")
        actuator = float(np.clip(requested, -limit, limit))
        return self.step_unbounded_force(actuator, disturbance, requested_force_n=requested)

    def step_unbounded_force(self, actuator_force_n: float, disturbance_force_n: float = 0.0,
                             *, requested_force_n: float | None = None):
        """Explicit auxiliary drive: unlike normal control, its actuator is not limited."""
        actuator = finite_number(actuator_force_n, "actuator force")
        disturbance = finite_number(disturbance_force_n, "disturbance")
        requested = actuator if requested_force_n is None else finite_number(requested_force_n, "request")
        net = finite_number(actuator + disturbance, "net force")
        self.env.unwrapped.force_mag = abs(net)
        observation, reward, terminated, truncated, info = self.env.step(
            1 if net >= 0.0 else 0
        )
        info = dict(info)
        info.update(commanded_force=requested, applied_force=actuator,
                    requested_force_n=requested, actuator_force_n=actuator,
                    disturbance_force_n=disturbance, net_force_n=net)
        return observation, reward, terminated, truncated, info


def make_env(
    render_mode: str | None = None,
    max_episode_steps: int = 500,
) -> ContinuousForceCartPole:
    """A default episode is 500 fixed 0.02 s simulation steps (10 s)."""
    if (
        isinstance(max_episode_steps, bool)
        or not isinstance(max_episode_steps, int)
        or max_episode_steps <= 0
    ):
        raise ValueError("max_episode_steps must be a positive integer")
    return ContinuousForceCartPole(
        gym.make(
            "CartPole-v1",
            render_mode=render_mode,
            max_episode_steps=max_episode_steps,
        )
    )
