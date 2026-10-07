"""One observation, one action, one fixed physics step for GUI, CLI and RL."""
from __future__ import annotations

from collections import deque
from dataclasses import replace
from enum import StrEnum
import uuid
import numpy as np

from .clock import SimulationClock
from .scenario import ForcePulse, configuration_hash
from .types import Action, ActionRequest, EpisodeSpec, State, StepResult, finite_number


class SessionStatus(StrEnum):
    READY = "READY"
    WAITING_ACTION = "WAITING_ACTION"
    PAUSED = "PAUSED"
    FINISHED = "FINISHED"
    ERROR = "ERROR"


class EpisodeSession:
    """Synchronous steps plus optional generation-safe asynchronous action requests.

    No wall-clock sleeps, Qt objects or controller code live in this class.
    ``step`` is for a caller that already owns action scheduling. Alternatively,
    use request_action/submit_action so stale/duplicate replies cannot step physics.
    """
    def __init__(self, spec: EpisodeSpec, *, render_mode=None):
        if not isinstance(spec, EpisodeSpec):
            raise TypeError("spec must be an EpisodeSpec")
        self.spec = spec
        self._base_spec = spec
        self.render_mode = render_mode
        self._env = None
        self._closed = False
        self._pending = None
        self._cached_action = None
        self.reset()

    @property
    def dt(self):
        return self.spec.dt_s

    @property
    def step_index(self):
        return self.clock.step_index

    @property
    def simulation_time_s(self):
        return self.clock.time_s

    @property
    def true_state(self):
        return self._true_state

    @property
    def observed_state(self):
        return self._observed_state

    @property
    def target_velocity_mps(self):
        return self.spec.scenario.target_at(self.step_index)

    @property
    def finished(self):
        return self.status in (SessionStatus.FINISHED, SessionStatus.ERROR)

    @property
    def config_hash(self):
        return configuration_hash(self.spec)

    def _observe(self):
        true = np.asarray(self._true_state.as_tuple(), dtype=np.float64)
        # Noise owns a separate RNG; reading the property does not draw new noise.
        noise = self._noise_rng.normal(0.0, self.spec.scenario.observation_noise_std, 4)
        return State.from_sequence((true + noise).astype(np.float32))

    def reset(self, *, spec: EpisodeSpec | None = None):
        if self._closed:
            raise RuntimeError("session is closed")
        if spec is not None:
            if not isinstance(spec, EpisodeSpec):
                raise TypeError("spec must be an EpisodeSpec")
            self.spec = spec
            self._base_spec = spec
        else:
            self.spec = self._base_spec
        if self._env is not None:
            self._env.close()
        scenario = self.spec.scenario
        if scenario.environment == "cart_velocity":
            from control_lab.envs.cart_velocity import CartVelocityEnv
            self._env = CartVelocityEnv(dt=self.dt, mass_kg=scenario.cart_mass_kg,
                                        drag_ns_m=scenario.velocity_drag_ns_m,
                                        force_limit_n=self.spec.force_limit_n)
            self._env.reset(seed=scenario.initial_state_seed,
                            options={"initial_state": scenario.initial_state.as_tuple()})
        else:
            from control_lab.envs.cartpole import make_env
            self._env = make_env(self.render_mode, self.spec.max_steps)
            physical = self._env.unwrapped
            physical.tau = self.dt
            self._env.dt = self.dt
            self._env.force_limit_n = self.spec.force_limit_n
            physical.theta_threshold_radians = self.spec.theta_limit_rad
            physical.x_threshold = self.spec.x_limit_m
            physical.masscart, physical.masspole = scenario.cart_mass_kg, scenario.pole_mass_kg
            physical.total_mass = physical.masscart + physical.masspole
            physical.length, physical.gravity = scenario.half_pole_length_m, scenario.gravity_m_s2
            physical.polemass_length = physical.masspole * physical.length
            self._env.reset(seed=scenario.initial_state_seed)
            physical.state = scenario.initial_state.as_tuple()
        self.clock = SimulationClock(self.dt)
        self.episode_id = uuid.uuid4().hex
        self._true_state = scenario.initial_state
        self._noise_rng = np.random.default_rng(scenario.observation_noise_seed)
        self._observed_state = self._observe()
        # Warm up with the initial measurement; no invented pre-episode motion.
        self._observation_delay = deque([self._observed_state] * scenario.observation_delay_steps)
        self._delay = deque([0.0] * scenario.action_delay_steps)
        self._pending = self._cached_action = None
        self.runtime_events = []
        self.last_result = None
        self.error = None
        self.status = SessionStatus.READY
        return self.observed_state

    def _require_ready(self):
        if self._closed:
            raise RuntimeError("session is closed")
        if self.status != SessionStatus.READY:
            raise RuntimeError(f"cannot step a session in state {self.status}")

    def _force_value(self, action):
        if isinstance(action, Action):
            if action.kind == "force_n":
                return action.value, "force_n"
            if action.kind == "velocity_mps":
                from control_lab.inputs.velocity import VelocityController
                force = VelocityController(force_limit_n=self.spec.force_limit_n).force(
                    action.value, self.observed_state)
                return finite_number(force, "velocity force"), "velocity_mps"
            raise ValueError("position actions use step_assisted(acceleration), not a force policy")
        return finite_number(action, "action"), "force_n"

    def _finish_step(self, raw, requested, mode, target):
        _, reward, terminated, truncated, info = raw
        step_id = self.step_index
        self.clock.advance()
        self._true_state = State.from_sequence(self._env.unwrapped.state)
        self._observation_delay.append(self._observe())
        self._observed_state = self._observation_delay.popleft()
        truncated = bool(truncated or self.step_index >= self.spec.max_steps)
        reason = None
        if terminated:
            reason = "position_limit" if abs(self.true_state.x) > self.spec.x_limit_m else "angle_limit"
        elif truncated:
            reason = "time_limit"
        result = StepResult(
            self.episode_id, step_id, self.simulation_time_s,
            self.true_state, self.observed_state, requested,
            float(info["actuator_force_n"]), float(info["disturbance_force_n"]),
            float(info["net_force_n"]), float(reward), bool(terminated), truncated, reason,
            mode, target)
        self.last_result = result
        self.status = SessionStatus.FINISHED if terminated or truncated else SessionStatus.READY
        return result

    def step(self, action):
        self._require_ready()
        requested, mode = self._force_value(action)
        target = action.value if isinstance(action, Action) and action.kind == "velocity_mps" else self.target_velocity_mps
        self._delay.append(requested)
        applied_request = self._delay.popleft()
        disturbance = self.spec.scenario.disturbance_at(self.step_index)
        raw = self._env.step_force(applied_request, disturbance)
        return self._finish_step(raw, requested, mode, target)

    def step_assisted(self, acceleration_mps2):
        self._require_ready()
        acceleration = finite_number(acceleration_mps2, "acceleration")
        # Never replay pre-drag policy commands when a user releases the cart.
        self._delay = deque([0.0] * self.spec.scenario.action_delay_steps)
        disturbance = self.spec.scenario.disturbance_at(self.step_index)
        if self.spec.scenario.environment == "cartpole":
            from control_lab.envs.driven_cartpole import step_driven
            raw = step_driven(self._env, acceleration, disturbance)
        else:
            required_net = (self.spec.scenario.cart_mass_kg * acceleration
                            + self.spec.scenario.velocity_drag_ns_m * self.true_state.v)
            raw = self._env.step_unbounded_force(required_net - disturbance, disturbance)
        return self._finish_step(raw, float(raw[-1]["requested_force_n"]),
                                 "manual_position_assist", self.target_velocity_mps)

    def add_disturbance(self, force_n=1.0, duration_steps=5):
        if self._closed or self.finished:
            raise RuntimeError("cannot disturb a finished or closed session")
        if not self.spec.allow_runtime_disturbances:
            raise ValueError("this fixed protocol does not allow interactive disturbances")
        pulse = ForcePulse(self.step_index, duration_steps, force_n)
        self.spec = replace(self.spec, scenario=replace(
            self.spec.scenario, disturbances=self.spec.scenario.disturbances + (pulse,)))
        self.runtime_events.append(dict(event="disturbance_added", step_id=self.step_index,
                                        force_n=pulse.force_n, duration_steps=pulse.duration_steps))
        return pulse

    def request_action(self):
        self._require_ready()
        request = ActionRequest(self.episode_id, self.step_index, self.observed_state, self.dt)
        self._pending = request
        self.status = SessionStatus.WAITING_ACTION
        return request

    def submit_action(self, request: ActionRequest, action):
        if self._closed or request != self._pending:
            return None
        # Validate now, including when paused; bad output cannot be hidden in a cache.
        self._force_value(action)
        if self._cached_action is not None:
            return None
        if self.status == SessionStatus.PAUSED:
            self._cached_action = action
            return None
        if self.status != SessionStatus.WAITING_ACTION:
            return None
        self._pending = None
        self.status = SessionStatus.READY
        return self.step(action)

    def pause(self):
        if not self.finished and not self._closed:
            self.status = SessionStatus.PAUSED

    def resume(self):
        if self.status != SessionStatus.PAUSED or self._closed:
            return None
        if self._cached_action is not None:
            action = self._cached_action
            self._cached_action = self._pending = None
            self.status = SessionStatus.READY
            return self.step(action)
        self.status = SessionStatus.WAITING_ACTION if self._pending is not None else SessionStatus.READY
        return None

    def fail(self, message):
        self.error = str(message)
        self.status = SessionStatus.ERROR
        self._pending = self._cached_action = None

    def close(self):
        if self._env is not None:
            self._env.close()
        self._closed = True
        self._pending = self._cached_action = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
