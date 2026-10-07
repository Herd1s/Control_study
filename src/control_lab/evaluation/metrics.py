"""Metrics use true post-step states and actual actuator forces, without padding."""
from collections import Counter
import math
import statistics
from control_lab.controllers._common import positive, state_values

METRICS_VERSION = "balance-metrics-v1"


def _boolean(value):
    if isinstance(value, str):
        if value.lower() in ("true", "1"):
            return True
        if value.lower() in ("false", "0", ""):
            return False
        raise ValueError(f"Invalid boolean {value!r}")
    return bool(value)


def episode_metrics(rows, *, initial_state, max_steps=500, dt_s=0.02,
                    force_limit_n=10.0, end_reason=None, error=None):
    rows = list(rows)
    initial_state = state_values(initial_state)
    dt_s, force_limit_n = positive(dt_s, "dt_s"), positive(force_limit_n, "force_limit_n")
    if isinstance(max_steps, bool) or not isinstance(max_steps, int) or max_steps < 1:
        raise ValueError("max_steps must be a positive integer")
    if len(rows) > max_steps:
        raise ValueError("Trajectory exceeds the declared episode limit")
    theta = [float(initial_state[2])] + [float(row["true_theta_rad"]) for row in rows]
    positions = [float(initial_state[0])] + [float(row["true_x_m"]) for row in rows]
    forces = [float(row["actuator_force_n"]) for row in rows]
    requests = [float(row["requested_force_n"]) for row in rows]
    if not all(math.isfinite(value) for value in theta + positions + forces + requests):
        raise ValueError("Metrics cannot contain nonfinite trajectory values")
    terminated = _boolean(rows[-1]["terminated"]) if rows else False
    truncated = _boolean(rows[-1]["truncated"]) if rows else False
    success = len(rows) == max_steps and truncated and not terminated and error is None
    mean_square = lambda values: math.sqrt(statistics.fmean(value * value for value in values)) if values else None
    return dict(
        episode_steps=len(rows), survival_time_s=len(rows) * dt_s,
        completed=success, terminated=terminated, truncated=truncated,
        end_reason=end_reason or ("time_limit" if success else "terminated" if terminated else "incomplete"),
        controller_error=error, rms_theta_rad=mean_square(theta), max_abs_x_m=max(map(abs, positions)),
        final_x_m=positions[-1],
        final_v_m_s=float(rows[-1]["true_v_m_s"]) if rows else float(initial_state[1]),
        rms_actuator_force_n=mean_square(forces),
        mean_abs_actuator_force_n=statistics.fmean(map(abs, forces)) if forces else None,
        saturation_fraction=statistics.fmean(abs(value) > force_limit_n for value in requests) if requests else None,
        actuator_limit_fraction=statistics.fmean(abs(value) >= force_limit_n - 1e-9 for value in forces) if forces else None,
        mean_abs_force_change_n=statistics.fmean(abs(b - a) for a, b in zip(forces, forces[1:])) if len(forces) > 1 else None,
        episode_return=math.fsum(float(row["reward"]) for row in rows),
        state_sample_count=len(theta), state_sampling="initial_and_each_true_post_step",
    )


def aggregate_metrics(episodes):
    episodes = list(episodes)
    if not episodes:
        raise ValueError("Cannot aggregate an empty evaluation")
    steps = [episode["episode_steps"] for episode in episodes]
    # Every requested case remains in the denominator, including initialization errors.
    return dict(episodes=len(episodes), completed_episodes=sum(e["completed"] for e in episodes),
                completed_fraction=statistics.fmean(e["completed"] for e in episodes),
                mean_steps=statistics.fmean(steps), median_steps=statistics.median(steps),
                worst_steps=min(steps), population_std_steps=statistics.pstdev(steps),
                controller_errors=sum(e.get("controller_error") is not None for e in episodes),
                end_reasons=dict(Counter(e["end_reason"] for e in episodes)),
                mean_episode_return=statistics.fmean(e["episode_return"] for e in episodes),
                mean_episode_rms_theta_rad=statistics.fmean(e["rms_theta_rad"] for e in episodes))
