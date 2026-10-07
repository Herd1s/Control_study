"""Visible optional velocity assistance, distinct from direct force control."""
from dataclasses import dataclass

from control_lab.core.types import State, finite_number


@dataclass(frozen=True)
class VelocityCommand:
    target_velocity_mps: float
    requested_force_n: float
    actuator_force_n: float


class VelocityController:
    def __init__(self, gain=8.0, force_limit_n=10.0):
        self.gain = finite_number(gain, "velocity gain")
        self.force_limit_n = finite_number(force_limit_n, "force limit")
        if self.gain <= 0 or self.force_limit_n <= 0:
            raise ValueError("gain and force limit must be positive")

    def convert(self, target_velocity_mps, state):
        target = finite_number(target_velocity_mps, "target velocity")
        state = State.from_sequence(state)
        request = self.gain * (target - state.v)
        return VelocityCommand(target, request, min(self.force_limit_n, max(-self.force_limit_n, request)))

    def force(self, target_velocity_mps, state):
        return self.convert(target_velocity_mps, state).requested_force_n
