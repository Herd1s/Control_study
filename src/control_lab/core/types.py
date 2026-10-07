"""Small immutable contracts. All physical quantities use SI units."""
from __future__ import annotations

from dataclasses import dataclass
import math
from numbers import Integral, Real
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .scenario import ScenarioConfig


def finite_number(value, name="value") -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, not a boolean or string")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def integer(value, name="value", minimum=0) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return int(value)


@dataclass(frozen=True)
class State:
    x: float = 0.0
    v: float = 0.0
    theta: float = 0.0
    omega: float = 0.0

    def __post_init__(self):
        for name in ("x", "v", "theta", "omega"):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))

    def as_tuple(self) -> tuple[float, float, float, float]:
        return self.x, self.v, self.theta, self.omega

    def as_dict(self) -> dict[str, float]:
        return dict(zip(("x", "v", "theta", "omega"), self.as_tuple()))

    def __iter__(self):
        return iter(self.as_tuple())

    @classmethod
    def from_sequence(cls, values) -> State:
        if isinstance(values, cls):
            return values
        values = tuple(values)
        if len(values) != 4:
            raise ValueError("state must contain x, v, theta, omega")
        return cls(*values)


@dataclass(frozen=True)
class Action:
    value: float
    kind: Literal["force_n", "velocity_mps", "position_m"] = "force_n"

    def __post_init__(self):
        object.__setattr__(self, "value", finite_number(self.value, "action"))
        if self.kind not in ("force_n", "velocity_mps", "position_m"):
            raise ValueError("unknown action kind")


@dataclass(frozen=True)
class EpisodeSpec:
    protocol_id: str
    scenario: ScenarioConfig
    dt_s: float = 0.02
    force_limit_n: float = 10.0
    max_steps: int = 500
    theta_limit_rad: float = math.radians(12)
    x_limit_m: float = 2.4
    require_nonzero_initial: bool = False
    allow_runtime_disturbances: bool = False

    def __post_init__(self):
        from .scenario import ScenarioConfig
        if not isinstance(self.protocol_id, str) or not self.protocol_id.strip():
            raise ValueError("protocol_id must be a nonempty string")
        if not isinstance(self.scenario, ScenarioConfig):
            raise TypeError("scenario must be a ScenarioConfig")
        for name in ("dt_s", "force_limit_n", "theta_limit_rad", "x_limit_m"):
            value = finite_number(getattr(self, name), name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "max_steps", integer(self.max_steps, "max_steps", 1))
        if not isinstance(self.require_nonzero_initial, bool):
            raise TypeError("require_nonzero_initial must be boolean")
        if not isinstance(self.allow_runtime_disturbances, bool):
            raise TypeError("allow_runtime_disturbances must be boolean")
        if self.require_nonzero_initial and not any(self.scenario.initial_state):
            raise ValueError("a scored challenge cannot start at the all-zero state")
        if self.scenario.environment == "cartpole":
            initial = self.scenario.initial_state
            if abs(initial.x) > self.x_limit_m or abs(initial.theta) > self.theta_limit_rad:
                raise ValueError("initial state is outside the episode limits")


@dataclass(frozen=True)
class StepResult:
    episode_id: str
    step_id: int
    simulation_time_s: float
    true_state: State
    observed_state: State
    requested_force_n: float
    actuator_force_n: float
    disturbance_force_n: float
    net_force_n: float
    reward: float
    terminated: bool
    truncated: bool
    end_reason: str | None
    input_mode: str = "force_n"
    target_velocity_mps: float = 0.0

    def __post_init__(self):
        for name in ("simulation_time_s", "requested_force_n", "actuator_force_n",
                     "disturbance_force_n", "net_force_n", "reward", "target_velocity_mps"):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))
        object.__setattr__(self, "step_id", integer(self.step_id, "step_id"))
        if self.simulation_time_s < 0:
            raise ValueError("simulation time cannot be negative")
        if not isinstance(self.true_state, State) or not isinstance(self.observed_state, State):
            raise TypeError("step states must be State instances")
        if not isinstance(self.terminated, bool) or not isinstance(self.truncated, bool):
            raise TypeError("end flags must be boolean")


@dataclass(frozen=True)
class ActionRequest:
    episode_id: str
    step_id: int
    observation: State
    dt_s: float
