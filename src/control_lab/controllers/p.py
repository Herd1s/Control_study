"""L13: positive pole angle requires positive cart force in this model."""
from ._common import components, finite_number, positive, state_values


class PController:
    def __init__(self, kp=60.0, force_limit_n=10.0):
        self.kp = finite_number(kp, "kp")
        self.force_limit_n = positive(force_limit_n, "force_limit_n")
        self.reset()

    def reset(self):
        self.diagnostics = components(0.0, 0.0, 0.0, 0.0, self.force_limit_n)

    def act(self, observation, dt):
        positive(dt, "dt")
        _, _, theta, _ = state_values(observation)
        self.diagnostics = components(self.kp * theta, 0.0, 0.0, 0.0, self.force_limit_n)
        return self.diagnostics["unsaturated_n"]


Controller = PController
