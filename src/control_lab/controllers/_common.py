"""Validation shared by classroom controllers; all control outputs are newtons."""
from collections.abc import Mapping
import math
from numbers import Real


def finite_number(value, name="value") -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{name} must be a real number, not a boolean or string")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def positive(value, name) -> float:
    value = finite_number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def state_values(state) -> tuple[float, float, float, float]:
    fields = ("x", "v", "theta", "omega")
    if isinstance(state, Mapping):
        values = [state[name] for name in fields]
    elif all(hasattr(state, name) for name in fields):
        values = [getattr(state, name) for name in fields]
    else:
        values = list(state)
        if len(values) != 4:
            raise ValueError("state must contain x, v, theta, omega in that order")
    return tuple(finite_number(value, name) for name, value in zip(fields, values))


def components(p, d, i, centering, force_limit, **extra):
    requested = finite_number(p + d + i + centering, "requested force")
    return dict(p_n=p, d_n=d, i_n=i, centering_n=centering,
                unsaturated_n=requested,
                applied_n=max(-force_limit, min(force_limit, requested)),
                saturated=abs(requested) > force_limit, **extra)
