"""Validated explicit initial conditions, independent measurement noise and loads."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
import numpy as np

from .types import EpisodeSpec, State, finite_number, integer


@dataclass(frozen=True)
class ForcePulse:
    start_step: int
    duration_steps: int
    force_n: float

    def __post_init__(self):
        object.__setattr__(self, "start_step", integer(self.start_step, "start_step"))
        object.__setattr__(self, "duration_steps", integer(self.duration_steps, "duration_steps", 1))
        object.__setattr__(self, "force_n", finite_number(self.force_n, "force_n"))


@dataclass(frozen=True)
class TargetChange:
    start_step: int
    velocity_mps: float

    def __post_init__(self):
        object.__setattr__(self, "start_step", integer(self.start_step, "start_step"))
        object.__setattr__(self, "velocity_mps", finite_number(self.velocity_mps, "velocity_mps"))


@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    initial_state: State = State()
    disturbances: tuple[ForcePulse, ...] = ()
    target_schedule: tuple[TargetChange, ...] = ()
    observation_noise_seed: int = 0
    observation_noise_std: tuple[float, float, float, float] = (0., 0., 0., 0.)
    environment: str = "cartpole"
    constant_force_n: float = 0.0
    initial_state_seed: int | None = None
    action_delay_steps: int = 0
    observation_delay_steps: int = 0
    cart_mass_kg: float = 1.0
    pole_mass_kg: float = 0.1
    half_pole_length_m: float = 0.5
    gravity_m_s2: float = 9.8
    velocity_drag_ns_m: float = 0.5

    def __post_init__(self):
        if not isinstance(self.scenario_id, str) or not self.scenario_id.strip():
            raise ValueError("scenario_id must be a nonempty string")
        object.__setattr__(self, "initial_state", State.from_sequence(self.initial_state))
        if self.environment not in ("cartpole", "cart_velocity"):
            raise ValueError("unknown environment")
        if self.environment == "cart_velocity" and (self.initial_state.theta or self.initial_state.omega):
            raise ValueError("the fixed-pole velocity scene requires theta=omega=0")
        for name, item_type in (("disturbances", ForcePulse), ("target_schedule", TargetChange)):
            items = tuple(getattr(self, name))
            if any(not isinstance(item, item_type) for item in items):
                raise TypeError(f"{name} contains the wrong item type")
            object.__setattr__(self, name, items)
        starts = [item.start_step for item in self.target_schedule]
        if starts != sorted(set(starts)):
            raise ValueError("target schedule must have unique increasing start steps")
        std = tuple(finite_number(value, "noise std") for value in self.observation_noise_std)
        if len(std) != 4 or any(value < 0 for value in std):
            raise ValueError("noise std must contain four nonnegative finite values")
        object.__setattr__(self, "observation_noise_std", std)
        object.__setattr__(self, "observation_noise_seed", integer(self.observation_noise_seed, "noise seed"))
        object.__setattr__(self, "action_delay_steps", integer(self.action_delay_steps, "action delay"))
        object.__setattr__(self, "observation_delay_steps", integer(self.observation_delay_steps, "observation delay"))
        if self.observation_delay_steps > 1000:
            raise ValueError("observation delay must not exceed 1000 steps")
        if self.initial_state_seed is not None:
            object.__setattr__(self, "initial_state_seed", integer(self.initial_state_seed, "initial seed"))
        object.__setattr__(self, "constant_force_n", finite_number(self.constant_force_n, "constant force"))
        for name in ("cart_mass_kg", "pole_mass_kg", "half_pole_length_m", "gravity_m_s2"):
            value = finite_number(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        drag = finite_number(self.velocity_drag_ns_m, "velocity drag")
        if drag < 0:
            raise ValueError("velocity drag cannot be negative")
        object.__setattr__(self, "velocity_drag_ns_m", drag)

    def disturbance_at(self, step: int) -> float:
        step = integer(step, "step")
        return self.constant_force_n + sum(
            pulse.force_n for pulse in self.disturbances
            if pulse.start_step <= step < pulse.start_step + pulse.duration_steps
        )

    def target_at(self, step: int, default: float = 0.0) -> float:
        step = integer(step, "step")
        target = finite_number(default, "default target")
        for item in self.target_schedule:
            if item.start_step > step:
                break
            target = item.velocity_mps
        return target


def configuration_hash(spec: EpisodeSpec) -> str:
    payload = json.dumps(asdict(spec), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def seeded_scenario(seed: int, scenario_id: str = "seeded-balance", **kwargs) -> ScenarioConfig:
    """Freeze the same uniform initial distribution used by Gym CartPole reset."""
    seed = integer(seed, "seed")
    values = np.random.default_rng(seed).uniform(-0.05, 0.05, 4)
    if not np.any(values):
        values[2] = 0.01
    return ScenarioConfig(scenario_id, State.from_sequence(values), initial_state_seed=seed, **kwargs)


def get_scenario(scenario_id: str, seed: int | None = None) -> ScenarioConfig:
    states = {
        "upright": State(), "tilt_right": State(theta=0.05),
        "tilt_left": State(theta=-0.05), "moving_right": State(v=0.1, theta=0.02),
        "offset_right": State(x=0.2), "angle_fast_right": State(theta=0.05, omega=0.15),
        "position_right": State(x=0.3), "position_left": State(x=-0.3),
        "angle_recovering": State(theta=0.05, omega=-0.15),
    }
    if scenario_id in states:
        return ScenarioConfig(scenario_id, states[scenario_id])
    if scenario_id in ("cart_velocity", "cart_velocity_unloaded", "cart_velocity_windup"):
        targets = ((TargetChange(0, 4.0), TargetChange(200, 0.3))
                   if scenario_id.endswith("windup") else (TargetChange(0, 0.3),))
        return ScenarioConfig(scenario_id, environment="cart_velocity",
                              constant_force_n=0.0 if scenario_id == "cart_velocity_unloaded" else -0.5,
                              target_schedule=targets)
    if scenario_id in ("measurement_theta_noise", "measurement_omega_noise"):
        standard_deviation = ((0., 0., .002, 0.) if scenario_id == "measurement_theta_noise"
                              else (0., 0., 0., .02))
        return seeded_scenario(42 if seed is None else seed, scenario_id,
                               observation_noise_seed=2026,
                               observation_noise_std=standard_deviation)
    if scenario_id in ("observation_delay_1", "observation_delay_2", "pole_mass_minus10", "pole_mass_plus10"):
        changes = {"observation_delay_1": {"observation_delay_steps": 1},
                   "observation_delay_2": {"observation_delay_steps": 2},
                   "pole_mass_minus10": {"pole_mass_kg": .09},
                   "pole_mass_plus10": {"pole_mass_kg": .11}}
        return seeded_scenario(42 if seed is None else seed, scenario_id, **changes[scenario_id])
    seeds = {"balance_practice": 42, "balance_validation": 100, "balance_test": 10042,
             "robustness_delay": 42}
    if scenario_id in seeds:
        return seeded_scenario(seeds[scenario_id] if seed is None else seed, scenario_id,
                               action_delay_steps=2 if scenario_id == "robustness_delay" else 0)
    raise KeyError(f"unknown scenario: {scenario_id}")


def get_episode_spec(scenario_id: str, seed: int | None = None) -> EpisodeSpec:
    scenario = get_scenario(scenario_id, seed)
    if scenario_id == "upright":
        return EpisodeSpec("free-exploration-v1", scenario, max_steps=500_000,
                           theta_limit_rad=math.radians(80), allow_runtime_disturbances=True)
    if scenario.environment == "cart_velocity":
        return EpisodeSpec(f"{scenario_id}-v1", scenario,
                           force_limit_n=1.0 if scenario_id.endswith("windup") else 10.0,
                           max_steps=600, x_limit_m=1_000_000, allow_runtime_disturbances=True)
    return EpisodeSpec(f"practice-{scenario_id}-v1", scenario, require_nonzero_initial=True,
                       allow_runtime_disturbances=True)


def upright_reset_spec(spec: EpisodeSpec) -> EpisodeSpec:
    """Preserve the scene/limits while making a paused, unscored zero-state reset."""
    return replace(spec, scenario=replace(spec.scenario, initial_state=State()),
                   require_nonzero_initial=False)
