"""L16 position/velocity dwell evidence, independent from pole survival.

The classroom declaration is |x| <= .1 m and |v| <= .1 m/s for a full
second. This is a local teaching criterion, not a universal stability proof.
"""
import math

from control_lab.controllers._common import finite_number, positive, state_values


class CenteringTracker:
    def __init__(self, *, position_tolerance_m=.1, velocity_tolerance_m_s=.1,
                 dwell_s=1., dt_s=.02, pole_angle_limit_rad=math.radians(12)):
        self.position_tolerance_m = positive(position_tolerance_m, "position tolerance")
        self.velocity_tolerance_m_s = positive(velocity_tolerance_m_s, "velocity tolerance")
        self.dwell_s = positive(dwell_s, "dwell time")
        self.dt_s = positive(dt_s, "dt")
        self.pole_angle_limit_rad = positive(pole_angle_limit_rad, "pole angle limit")
        self.reset()

    def _inside(self, state):
        x, velocity, _, _ = state_values(state)
        return abs(x) <= self.position_tolerance_m and abs(velocity) <= self.velocity_tolerance_m_s

    def reset(self, initial_state=None, *, time_s=0.):
        time_s = finite_number(time_s, "initial time")
        if time_s < 0:
            raise ValueError("time must be nonnegative")
        self.last_time_s = time_s if initial_state is not None else None
        self.inside_region = self._inside(initial_state) if initial_state is not None else False
        self.window_start_time_s = time_s if self.inside_region else None
        self.first_reached_time_s = None
        self.first_window_start_time_s = None
        self.pole_survived = (initial_state is None or
                              abs(state_values(initial_state)[2]) <= self.pole_angle_limit_rad)
        self.episode_terminated = False
        return self.snapshot()

    def observe(self, true_state, time_s, *, terminated=False):
        """Consume one true sample; a skipped interval breaks continuity.

        The first attained window remains evidence after the cart leaves again;
        current duration resets independently. Pole failure is a separate field.
        """
        time_s = finite_number(time_s, "simulation time")
        if time_s < 0 or self.last_time_s is not None and time_s <= self.last_time_s:
            raise ValueError("centering observations need strictly increasing nonnegative times")
        if not isinstance(terminated, bool):
            raise TypeError("terminated must be boolean")
        continuous = self.last_time_s is not None and math.isclose(
            time_s-self.last_time_s, self.dt_s, abs_tol=1e-9, rel_tol=1e-9)
        self.inside_region = self._inside(true_state)
        if not self.inside_region:
            self.window_start_time_s = None
        elif self.window_start_time_s is None or not continuous:
            self.window_start_time_s = time_s
        self.last_time_s = time_s
        self.pole_survived = self.pole_survived and abs(state_values(true_state)[2]) <= self.pole_angle_limit_rad
        self.episode_terminated = self.episode_terminated or terminated
        duration = self.current_duration_s
        if self.first_reached_time_s is None and self.inside_region and duration + 1e-9 >= self.dwell_s:
            self.first_reached_time_s = time_s
            self.first_window_start_time_s = self.window_start_time_s
        return self.snapshot()

    @property
    def current_duration_s(self):
        return 0. if self.window_start_time_s is None or self.last_time_s is None else self.last_time_s-self.window_start_time_s

    def snapshot(self):
        return {"first_reached_time_s": self.first_reached_time_s,
                "first_window_start_time_s": self.first_window_start_time_s,
                "current_duration_s": self.current_duration_s,
                "inside_region": self.inside_region,
                "currently_settled": self.inside_region and self.current_duration_s+1e-9 >= self.dwell_s,
                "pole_survived": self.pole_survived,
                "episode_terminated": self.episode_terminated,
                "definition": {"position_tolerance_m": self.position_tolerance_m,
                               "velocity_tolerance_m_s": self.velocity_tolerance_m_s,
                               "dwell_s": self.dwell_s, "dt_s": self.dt_s,
                               "pole_angle_limit_rad": self.pole_angle_limit_rad,
                               "state_source": "true", "first_reached": "end of the first complete dwell window",
                               "incomplete": None}}


def analyze_centering(rows, *, initial_state=None, dt_s=.02, **tolerances):
    """Accept saved interactive rows or formal evaluation CSV row dictionaries."""
    tracker = CenteringTracker(dt_s=dt_s, **tolerances)
    tracker.reset(initial_state)
    for row in rows:
        if "true_state" in row:
            state = row["true_state"]
            time_s = row["simulation_time_s"]
        else:
            state = [float(row["true_"+key]) for key in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")]
            time_s = row["time_s"]
        terminated = row.get("terminated", False)
        if isinstance(terminated, str):
            if terminated.lower() not in {"true", "false", "1", "0"}:
                raise ValueError("Invalid termination flag")
            terminated = terminated.lower() in {"true", "1"}
        tracker.observe(state, float(time_s), terminated=terminated)
    return tracker.snapshot()
