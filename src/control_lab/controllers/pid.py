"""Explicit PID/PI contributions and conditional integration, reset per episode.

act() returns requested force. The environment owns actuator saturation; applied_n
is a diagnostic for the configured controller limit, not a second actuator.
"""
from ._common import components, finite_number, positive, state_values


class PIDController:
    def __init__(self, kp=60.0, ki=0.0, kd=12.0, *, centering=None,
                 force_limit_n=10.0, integral_limit=0.5, anti_windup=True):
        self.kp, self.ki, self.kd = (finite_number(v, n) for v, n in
                                   ((kp, "kp"), (ki, "ki"), (kd, "kd")))
        self.centering = centering
        self.force_limit_n = positive(force_limit_n, "force_limit_n")
        self.integral_limit = None if integral_limit is None else positive(integral_limit, "integral_limit")
        if not isinstance(anti_windup, bool):
            raise TypeError("anti_windup must be a boolean")
        self.anti_windup = anti_windup
        self.reset()

    def reset(self):
        self.integral = 0.0
        self.diagnostics = components(0.0, 0.0, 0.0, 0.0, self.force_limit_n,
                                      integral=0.0, integral_frozen=False)

    def _compute(self, error, derivative, cart, dt):
        p, d = self.kp * error, self.kd * derivative
        candidate = self.integral + error * dt
        if self.integral_limit is not None:
            candidate = max(-self.integral_limit, min(self.integral_limit, candidate))
        increment_n = self.ki * (candidate - self.integral)
        candidate_force = p + d + cart + self.ki * candidate
        worsens_saturation = ((candidate_force > self.force_limit_n and increment_n > 0)
                              or (candidate_force < -self.force_limit_n and increment_n < 0))
        frozen = bool(self.anti_windup and worsens_saturation and self.ki != 0)
        if self.ki == 0:
            self.integral = 0.0
        elif not frozen:
            self.integral = candidate
        self.diagnostics = components(p, d, self.ki * self.integral, cart,
                                      self.force_limit_n, integral=self.integral,
                                      integral_frozen=frozen)
        return self.diagnostics["unsaturated_n"]

    def act(self, observation, dt):
        dt = positive(dt, "dt")
        state = state_values(observation)
        cart = 0.0 if self.centering is None else self.centering(state)
        return self._compute(state[2], state[3], cart, dt)


class VelocityPIController(PIDController):
    """L17/L18 independent cart-velocity bench: error = target_v - measured_v."""
    def __init__(self, kp=2.0, ki=1.0, *, target_velocity_mps=0.3,
                 force_limit_n=10.0, integral_limit=None, anti_windup=True):
        self.target_velocity_mps = finite_number(target_velocity_mps, "target velocity")
        super().__init__(kp, ki, 0.0, force_limit_n=force_limit_n,
                         integral_limit=integral_limit, anti_windup=anti_windup)

    def act(self, observation, dt):
        dt = positive(dt, "dt")
        velocity = state_values(observation)[1]
        return self._compute(self.target_velocity_mps - velocity, 0.0, 0.0, dt)


Controller = PIDController
