"""Versioned, inspectable reward components evaluated on post-action true state."""
import math

REWARD_SPECS = {
    "survival-v1": {"version": 1, "alive": 1.0, "angle": 0.0, "position": 0.0, "effort": 0.0},
    "balanced-v1": {"version": 1, "alive": 1.0, "angle": 0.6, "position": 0.2, "effort": 0.02},
}


def reward_components(reward_id: str, state, force_n: float) -> dict[str, float]:
    if reward_id not in REWARD_SPECS:
        raise ValueError(f"Unknown reward version: {reward_id}")
    if hasattr(state, "as_dict"):
        state = state.as_dict()
    if not isinstance(state, dict):
        state = dict(zip(("x", "v", "theta", "omega"), state))
    x, theta, force = float(state["x"]), float(state["theta"]), float(force_n)
    if not all(math.isfinite(v) for v in (x, theta, force)):
        raise ValueError("Reward inputs must be finite")
    cfg = REWARD_SPECS[reward_id]
    return {"survival": cfg["alive"],
            "angle": -cfg["angle"] * (theta / math.radians(12)) ** 2,
            "position": -cfg["position"] * (x / 2.4) ** 2,
            "effort": -cfg["effort"] * (force / 10.0) ** 2}
