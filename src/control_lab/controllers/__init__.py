"""Controller protocol shared by student code and reference controllers."""

from typing import Protocol, Sequence


class ControllerProtocol(Protocol):
    def reset(self) -> None:
        """Clear controller state at the beginning of every episode."""
        ...

    def act(self, observation: Sequence[float], dt: float) -> float:
        """Return requested cart force in newtons."""
        ...


class ZeroController:
    def reset(self) -> None:
        pass

    def act(self, observation: Sequence[float], dt: float) -> float:
        return 0.0
