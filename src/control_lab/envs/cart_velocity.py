"""Fixed-pole, single-cart velocity teaching plant for the PI lessons."""
from __future__ import annotations

import gymnasium as gym
import numpy as np

from control_lab.core.types import State, finite_number


class CartVelocityEnv(gym.Env):
    """m*dv/dt = actuator + external_force - drag*v; explicit Euler, SI units."""
    metadata = {"render_modes": []}

    def __init__(self, *, dt=0.02, mass_kg=1.0, drag_ns_m=0.5, force_limit_n=10.0):
        self.dt = finite_number(dt, "dt")
        self.mass_kg = finite_number(mass_kg, "mass")
        self.drag_ns_m = finite_number(drag_ns_m, "drag")
        self.force_limit_n = finite_number(force_limit_n, "force limit")
        if min(self.dt, self.mass_kg, self.force_limit_n) <= 0 or self.drag_ns_m < 0:
            raise ValueError("dt, mass and force limit must be positive; drag cannot be negative")
        self.action_space = gym.spaces.Box(-self.force_limit_n, self.force_limit_n, (1,), np.float32)
        self.observation_space = gym.spaces.Box(-np.inf, np.inf, (4,), np.float32)
        self.state = (0.0, 0.0, 0.0, 0.0)

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        state = State.from_sequence((options or {}).get("initial_state", (0., 0., 0., 0.)))
        if state.theta or state.omega:
            raise ValueError("the pole is fixed in the velocity teaching plant")
        self.state = state.as_tuple()
        return np.asarray(self.state, dtype=np.float32), {}

    def step(self, action):
        raw = np.asarray(action)
        if raw.shape != (1,) or raw.dtype.kind not in "fiu":
            raise ValueError("action must be one finite real force")
        return self.step_force(float(raw[0]))

    def step_force(self, force_n, disturbance_force_n=0.0):
        requested = finite_number(force_n, "force")
        actuator = min(self.force_limit_n, max(-self.force_limit_n, requested))
        return self.step_unbounded_force(actuator, disturbance_force_n, requested_force_n=requested)

    def step_unbounded_force(self, actuator_force_n, disturbance_force_n=0.0, *, requested_force_n=None):
        actuator = finite_number(actuator_force_n, "actuator force")
        disturbance = finite_number(disturbance_force_n, "disturbance")
        requested = actuator if requested_force_n is None else finite_number(requested_force_n, "request")
        net = finite_number(actuator + disturbance, "net force")
        x, v, _, _ = self.state
        acceleration = (net - self.drag_ns_m * v) / self.mass_kg
        state = State(x + self.dt * v, v + self.dt * acceleration, 0.0, 0.0)
        self.state = state.as_tuple()
        info = dict(commanded_force=requested, applied_force=actuator,
                    requested_force_n=requested, actuator_force_n=actuator,
                    disturbance_force_n=disturbance, net_force_n=net)
        return np.asarray(self.state, dtype=np.float32), 1.0, False, False, info
