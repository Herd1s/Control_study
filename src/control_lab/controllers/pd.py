"""L15/L16: direct angular-velocity feedback and optional coupled cart feedback."""
from ._common import components, finite_number, positive, state_values


class PDController:
    def __init__(self, kp=60.0, kd=12.0, *, centering=None, force_limit_n=10.0,
                 derivative_filter=None):
        self.kp, self.kd = finite_number(kp, "kp"), finite_number(kd, "kd")
        self.centering = centering
        self.force_limit_n = positive(force_limit_n, "force_limit_n")
        self.derivative_filter = derivative_filter
        self.reset()

    def reset(self):
        self.diagnostics = components(0.0, 0.0, 0.0, 0.0, self.force_limit_n)
        if self.derivative_filter is not None:
            self.derivative_filter.reset()

    def act(self, observation, dt):
        dt = positive(dt, "dt")
        state = state_values(observation)
        omega = state[3]
        if self.derivative_filter is not None:
            omega = self.derivative_filter.update(omega, dt)
        cart = 0.0 if self.centering is None else self.centering(state)
        self.diagnostics = components(self.kp * state[2], self.kd * omega,
                                      0.0, cart, self.force_limit_n)
        return self.diagnostics["unsaturated_n"]


Controller = PDController
