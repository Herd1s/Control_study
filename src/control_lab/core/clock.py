"""Simulation time is based on physical steps, never GUI wall-clock delays."""
from .types import finite_number


class SimulationClock:
    def __init__(self, dt_s=0.02):
        self.dt_s = finite_number(dt_s, "dt")
        if self.dt_s <= 0:
            raise ValueError("dt must be positive")
        self.step_index = 0

    @property
    def time_s(self):
        return self.step_index * self.dt_s

    def advance(self):
        self.step_index += 1
        return self.time_s

    def reset(self):
        self.step_index = 0
