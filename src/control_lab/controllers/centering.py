"""Cart feedback for the coupled inverted pendulum, not an isolated cart servo."""
from dataclasses import dataclass
from ._common import finite_number, state_values


@dataclass(frozen=True)
class CenteringFeedback:
    kx: float = 2.0
    kv: float = 3.0

    def __post_init__(self):
        finite_number(self.kx, "kx")
        finite_number(self.kv, "kv")

    def __call__(self, state) -> float:
        x, v, _, _ = state_values(state)
        # The initial positive force creates a lean; the angle loop then responds.
        # Do not replace these signs with those of an independent position servo.
        return self.kx * x + self.kv * v
