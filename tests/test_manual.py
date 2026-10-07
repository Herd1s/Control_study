import pytest

from control_lab.core.scenario import get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.core.types import State
from control_lab.inputs.manual import ManualPositionAssist, target_from_pointer
from control_lab.inputs.velocity import VelocityController


def test_grab_offset_does_not_move_target_when_pointer_stays_still():
    # User grabs 20px right of center. A stationary pointer requests no movement.
    assert target_from_pointer(220, 200, 20, 100) == 0
    assert target_from_pointer(270, 200, 20, 100) == .5


def test_assist_has_bounded_acceleration_speed_and_drives_pole():
    assist = ManualPositionAssist()
    with EpisodeSession(get_episode_spec("upright")) as session:
        saw_auxiliary_force = False
        for _ in range(12):
            acceleration = assist.acceleration(session.true_state, .5, session.dt)
            assert abs(acceleration) <= 80
            result = session.step_assisted(acceleration)
            assert abs(result.true_state.v) <= 4 + 1e-12
            assert result.input_mode == "manual_position_assist"
            saw_auxiliary_force |= abs(result.actuator_force_n) > 10
        assert saw_auxiliary_force
        assert result.true_state.x > .4
        assert abs(result.true_state.theta) > .01


def test_release_means_zero_actuator_and_preserves_inertia():
    with EpisodeSession(get_episode_spec("upright")) as session:
        session.step_assisted(3)
        before = session.true_state
        released = session.step(0)
        assert released.actuator_force_n == 0
        assert released.true_state.x == pytest.approx(before.x + before.v * .02)
        assert released.true_state.v != 0
        assert released.input_mode == "force_n"


def test_slow_mouse_trajectory_tracking_error_under_5_pixels():
    assist = ManualPositionAssist()
    # Compute only the bounded cart trajectory to avoid scoring a falling free pole.
    state = State()
    errors = []
    for step in range(100):
        target = .2 * step * .02
        acceleration = assist.acceleration(state, target, .02)
        state = State(state.x + state.v * .02, state.v + acceleration * .02, 0, 0)
        if step > 20:
            errors.append(abs(target - state.x) * 150)  # 150px per metre
    assert max(errors) < 5


def test_velocity_mode_reports_request_and_saturation():
    command = VelocityController().convert(2, State(v=.5))
    assert command.requested_force_n == 12
    assert command.actuator_force_n == 10
    assert command.target_velocity_mps == 2
