from dataclasses import asdict

import pytest

from control_lab.controllers.reference_pid import Controller
from control_lab.core.scenario import get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.core.types import State
from control_lab.evaluation.centering import CenteringTracker, analyze_centering


def test_outside_stationary_cart_never_counts_and_one_crossing_is_not_settled():
    tracker = CenteringTracker()
    tracker.reset(State(x=.2))
    for step in range(1, 101):
        result = tracker.observe(State(x=.2), step*.02)
    assert result["first_reached_time_s"] is None and result["current_duration_s"] == 0
    result = tracker.observe(State(x=0, v=.2), 2.02)
    assert not result["inside_region"]
    tracker.observe(State(x=0, v=0), 2.04)
    result = tracker.observe(State(x=.11, v=0), 2.06)
    assert result["first_reached_time_s"] is None and result["current_duration_s"] == 0


def test_full_second_requires_endpoints_and_survival_is_independent():
    tracker = CenteringTracker()
    tracker.reset(State(x=.1, v=.1))
    for step in range(1, 50):
        result = tracker.observe(State(x=.1, v=.1), step*.02)
    assert result["current_duration_s"] == .98 and result["first_reached_time_s"] is None
    result = tracker.observe(State(x=.1, v=.1), 1.)
    assert result["first_reached_time_s"] == 1. and result["first_window_start_time_s"] == 0.
    result = tracker.observe(State(x=.2, theta=.3), 1.02, terminated=True)
    assert result["first_reached_time_s"] == 1. and result["current_duration_s"] == 0
    assert not result["currently_settled"] and not result["pole_survived"]


def test_cart_boundary_failure_is_separate_from_pole_failure():
    tracker = CenteringTracker()
    tracker.reset(State(x=2.39))
    result = tracker.observe(State(x=2.41, theta=.02), .02, terminated=True)
    assert result["pole_survived"] and result["episode_terminated"]
    assert result["first_reached_time_s"] is None


def test_missing_samples_break_the_dwell_window():
    tracker = CenteringTracker()
    tracker.reset(State())
    tracker.observe(State(), .02)
    result = tracker.observe(State(), 1.02)
    assert result["current_duration_s"] == 0 and result["first_reached_time_s"] is None
    with pytest.raises(ValueError, match="increasing"):
        tracker.observe(State(), 1.02)


def test_real_offset_episode_offline_and_online_agree():
    spec = get_episode_spec("offset_right")
    controller = Controller()
    online = CenteringTracker(dt_s=spec.dt_s)
    online.reset(spec.scenario.initial_state)
    rows = []
    with EpisodeSession(spec) as session:
        controller.reset()
        while not session.finished:
            result = session.step(controller.act(session.observed_state, session.dt))
            rows.append(asdict(result))
            online.observe(result.true_state, result.simulation_time_s, terminated=result.terminated)
    offline = analyze_centering(rows, initial_state=spec.scenario.initial_state, dt_s=spec.dt_s)
    assert offline == online.snapshot()
    assert offline["first_reached_time_s"] is not None and offline["first_reached_time_s"] > 1
    assert offline["pole_survived"]
    assert offline["definition"]["position_tolerance_m"] == .1
