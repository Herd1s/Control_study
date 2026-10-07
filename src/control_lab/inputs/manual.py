"""Bounded physical mouse assistance. The GUI is responsible for grab offset."""
import math

from control_lab.core.types import State, finite_number


class ManualPositionAssist:
    def __init__(self, max_speed_mps=4.0, max_acceleration_mps2=80.0,
                 position_limit_m=2.3, response_time_s=0.04):
        for name, value in locals().copy().items():
            if name == "self":
                continue
            value = finite_number(value, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            setattr(self, name, value)

    def acceleration(self, state, target_x, dt):
        state = State.from_sequence(state)
        target = finite_number(target_x, "target position")
        dt = finite_number(dt, "dt")
        if dt <= 0:
            raise ValueError("dt must be positive")
        target = max(-self.position_limit_m, min(self.position_limit_m, target))
        # Damped continuous target tracking; a bounded velocity command
        # limits jumps, and acceleration limits sudden reversals/window exits.
        horizon = max(self.response_time_s, 2.0 * dt)
        desired_v = max(-self.max_speed_mps,
                        min(self.max_speed_mps, (target - state.x) / horizon))
        acceleration = (desired_v - state.v) / horizon
        acceleration = max(-self.max_acceleration_mps2,
                           min(self.max_acceleration_mps2, acceleration))
        # The integrator's next velocity must stay within the declared speed bound.
        if abs(state.v) <= self.max_speed_mps:
            acceleration = max((-self.max_speed_mps - state.v) / dt,
                               min((self.max_speed_mps - state.v) / dt, acceleration))
        return acceleration


def target_from_pointer(pointer_x_px, cart_center_x_px, grab_offset_px, pixels_per_meter):
    """Optional pure helper for GUI tests; returns target displacement from center."""
    pointer = finite_number(pointer_x_px, "pointer")
    center = finite_number(cart_center_x_px, "center")
    offset = finite_number(grab_offset_px, "grab offset")
    scale = finite_number(pixels_per_meter, "pixels per meter")
    if scale <= 0:
        raise ValueError("pixels_per_meter must be positive")
    return (pointer - offset - center) / scale
