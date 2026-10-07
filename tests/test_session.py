from dataclasses import replace
import pytest

from control_lab.core.scenario import ForcePulse, ScenarioConfig, get_episode_spec
from control_lab.core.session import EpisodeSession, SessionStatus
from control_lab.core.types import Action, EpisodeSpec, State


def test_async_only_matching_reply_steps_once_and_old_episode_is_ignored():
    with EpisodeSession(get_episode_spec("upright")) as session:
        request = session.request_action()
        assert session.step_index == 0
        with pytest.raises(RuntimeError):
            session.request_action()
        result = session.submit_action(request, 1.0)
        assert result.step_id == 0
        assert result.simulation_time_s == .02
        assert session.submit_action(request, 1.0) is None
        assert session.step_index == 1
        old = session.request_action()
        session.reset()
        assert session.submit_action(old, 1.0) is None
        assert session.step_index == 0


def test_pause_caches_exactly_one_response_and_resume_steps_once():
    with EpisodeSession(get_episode_spec("upright")) as session:
        request = session.request_action()
        session.pause()
        assert session.submit_action(request, 0.0) is None
        assert session.submit_action(request, 2.0) is None
        assert session.step_index == 0
        result = session.resume()
        assert result.requested_force_n == 0
        assert session.step_index == 1
        assert session.status == SessionStatus.READY
        assert session.resume() is None


def test_fixed_clock_limit_and_finished_guard():
    spec = replace(get_episode_spec("upright"), max_steps=3)
    with EpisodeSession(spec) as session:
        for _ in range(3):
            last = session.step(0)
        assert last.truncated and not last.terminated
        assert last.end_reason == "time_limit"
        assert session.simulation_time_s == .06
        with pytest.raises(RuntimeError):
            session.step(0)
        session.reset()
        assert session.true_state == State()
        assert not session.finished


def test_delay_is_explicit_steps_and_zero_actions_fill_initial_queue():
    spec = get_episode_spec("robustness_delay")
    with EpisodeSession(spec) as session:
        results = [session.step(value) for value in (1, 2, 3, 4)]
    assert [r.requested_force_n for r in results] == [1, 2, 3, 4]
    assert [r.actuator_force_n for r in results] == [0, 0, 1, 2]


def test_interactive_disturbance_recorded_then_cleared_by_reset():
    with EpisodeSession(get_episode_spec("upright")) as session:
        original_hash = session.config_hash
        session.add_disturbance(2, 2)
        assert session.config_hash != original_hash
        assert session.runtime_events[0]["step_id"] == 0
        assert [session.step(0).disturbance_force_n for _ in range(3)] == [2, 2, 0]
        session.reset()
        assert session.config_hash == original_hash
        assert session.step(0).disturbance_force_n == 0
    fixed = EpisodeSpec("fixed", ScenarioConfig("angle", State(theta=.02)))
    with EpisodeSession(fixed) as session:
        with pytest.raises(ValueError):
            session.add_disturbance()


def test_termination_uses_true_state_not_extreme_sensor_noise():
    scenario = ScenarioConfig("noise", observation_noise_std=(10, 10, 10, 10))
    with EpisodeSession(EpisodeSpec("noise-test", scenario)) as session:
        result = session.step(0)
        assert not result.terminated
        assert result.true_state == State()
        assert result.observed_state != State()


def test_bad_action_does_not_advance_simulation():
    with EpisodeSession(get_episode_spec("upright")) as session:
        for value in (True, float("nan"), float("inf")):
            with pytest.raises((TypeError, ValueError)):
                session.step(value)
        assert session.step_index == 0
        assert session.true_state == State()


def test_velocity_action_records_command_target_and_force_without_renormalizing():
    with EpisodeSession(get_episode_spec("upright")) as session:
        result = session.step(Action(.5, "velocity_mps"))
        assert result.input_mode == "velocity_mps"
        assert result.target_velocity_mps == .5
        assert result.requested_force_n == result.actuator_force_n == 4
