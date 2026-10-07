"""Causal first-order filtering with a physical time constant in seconds."""
import math
from ._common import finite_number, positive


class FirstOrderLowPass:
    def __init__(self, tau_s: float = 0.04):
        self.tau_s = finite_number(tau_s, "tau_s")
        if self.tau_s < 0:
            raise ValueError("tau_s must be nonnegative")
        self.reset()

    def reset(self, value=None):
        self.value = None if value is None else finite_number(value, "initial value")

    def update(self, value, dt):
        value, dt = finite_number(value), positive(dt, "dt")
        if self.value is None or self.tau_s == 0:
            self.value = value
        else:
            # Exact zero-order-hold discretization; valid across sample rates.
            alpha = -math.expm1(-dt / self.tau_s)
            self.value += alpha * (value - self.value)
        return self.value


class FilteredDerivative:
    """Backward difference followed by a causal low-pass; first sample is zero."""
    def __init__(self, tau_s=0.04):
        self.filter = FirstOrderLowPass(tau_s)
        self.reset()

    def reset(self):
        self.previous = None
        self.filter.reset(0.0)

    def update(self, value, dt):
        value, dt = finite_number(value), positive(dt, "dt")
        derivative = 0.0 if self.previous is None else (value - self.previous) / dt
        self.previous = value
        return self.filter.update(derivative, dt)
