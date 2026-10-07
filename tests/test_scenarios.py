"""Physics invariants and explicit, reproducible lesson scenarios."""
from dataclasses import replace
import math

import gymnasium as gym
import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env

from control_lab.core.scenario import (
    ForcePulse, ScenarioConfig, TargetChange, configuration_hash, get_episode_spec,
    get_scenario, seeded_scenario,
)
from control_lab.core.session import EpisodeSession
from control_lab.core.types import Action, EpisodeSpec, State
from control_lab.envs.cartpole import make_env
from control_lab.envs.driven_cartpole import accelerations_for_force, force_for_acceleration, step_driven
from control_lab.envs.wrappers import make_scenario_env


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), "1"])
def test_nonfinite_or_nonphysical_scalars_rejected(value):
    with pytest.raises((TypeError, ValueError)):
        State(theta=value)
    with pytest.raises((TypeError, ValueError)):
        Action(value)
    with pytest.raises((TypeError, ValueError)):
        ForcePulse(0, 1, value)


def test_validation_and_nonzero_scoring():
    zero = ScenarioConfig("zero")
    with pytest.raises(ValueError, match="all-zero"):
        EpisodeSpec("score", zero, require_nonzero_initial=True)
    with pytest.raises(ValueError):
        ScenarioConfig("noise", observation_noise_std=(0, -1, 0, 0))
    with pytest.raises(ValueError):
        ForcePulse(0, 0, 1)
    with pytest.raises(ValueError):
        ScenarioConfig("targets", target_schedule=(TargetChange(2, 0), TargetChange(1, 1)))
    with pytest.raises(ValueError):
        EpisodeSpec("bad", zero, dt_s=0)
    assert get_scenario("cart_velocity_windup").target_at(199) == 4
    assert get_scenario("cart_velocity_windup").target_at(200) == .3
    assert get_episode_spec("balance_test").protocol_id != "balance-v1"
    assert get_scenario("position_right").initial_state.x > .2
    assert get_scenario("position_left").initial_state.x < -.2
    assert get_scenario("offset_right").initial_state.x == .2
    assert get_scenario("cart_velocity_unloaded").constant_force_n == 0
    assert get_scenario("cart_velocity_unloaded").target_at(200) == .3


def test_seed_initials_match_gym_and_hash_freezes_parameters():
    env = gym.make("CartPole-v1")
    try:
        obs, _ = env.reset(seed=123)
        scenario = seeded_scenario(123)
        np.testing.assert_array_equal(np.asarray(scenario.initial_state.as_tuple(), np.float32), obs)
        spec = EpisodeSpec("test", scenario)
        assert configuration_hash(spec) == configuration_hash(replace(spec))
        assert configuration_hash(spec) != configuration_hash(replace(spec, force_limit_n=5))
    finally:
        env.close()


def test_actuator_clip_does_not_clip_external_force():
    scenario = ScenarioConfig("force", disturbances=(ForcePulse(0, 2, 25),))
    with EpisodeSession(EpisodeSpec("test", scenario)) as session:
        result = session.step(100)
        assert result.requested_force_n == 100
        assert result.actuator_force_n == 10
        assert result.disturbance_force_n == 25
        assert result.net_force_n == 35
        assert result.true_state.v > 0


def test_noise_has_no_effect_on_physics_or_initial_seed():
    scenario = seeded_scenario(43)
    clean = EpisodeSpec("test", scenario)
    noisy = replace(clean, scenario=replace(scenario, observation_noise_std=(0.1, .1, .002, .02),
                                            observation_noise_seed=67))
    with EpisodeSession(clean) as a, EpisodeSession(noisy) as b, EpisodeSession(noisy) as c:
        assert a.true_state == b.true_state
        assert b.observed_state == c.observed_state
        assert a.observed_state != b.observed_state
        for force in (1.0, -1.0, .3, 0.0):
            ra, rb, rc = a.step(force), b.step(force), c.step(force)
            assert ra.true_state == rb.true_state == rc.true_state
            assert rb.observed_state == rc.observed_state
        assert b.observed_state.as_tuple() == tuple(float(v) for v in np.asarray(b.observed_state.as_tuple(), np.float32))


def test_named_measurement_scenes_share_initial_state_and_reproducible_noise():
    clean = get_episode_spec("balance_practice")
    for name, noisy_index in (("measurement_theta_noise", 2), ("measurement_omega_noise", 3)):
        noisy = get_episode_spec(name)
        assert noisy.scenario.initial_state == clean.scenario.initial_state
        with EpisodeSession(clean) as a, EpisodeSession(noisy) as b, EpisodeSession(noisy) as c:
            for _ in range(3):
                assert a.true_state == b.true_state == c.true_state
                assert b.observed_state == c.observed_state
                assert tuple(a.observed_state)[noisy_index] != tuple(b.observed_state)[noisy_index]
                for index in set(range(4)) - {noisy_index}:
                    assert tuple(a.observed_state)[index] == tuple(b.observed_state)[index]
                a.step(1)
                b.step(1)
                c.step(1)


@pytest.mark.parametrize("delay", [1, 2])
def test_observation_delay_lags_measurements_without_delaying_force_or_physics(delay):
    baseline = get_episode_spec("balance_practice")
    delayed = get_episode_spec(f"observation_delay_{delay}")
    with EpisodeSession(baseline) as a, EpisodeSession(delayed) as b:
        measurements = [a.observed_state]
        for index in range(1, 7):
            ra, rb = a.step(.75), b.step(.75)
            measurements.append(a.observed_state)
            assert ra.true_state == rb.true_state
            assert rb.actuator_force_n == .75
            assert b.observed_state == measurements[max(0, index-delay)]
        b.reset()
        assert b.observed_state == measurements[0]


def test_mass_variations_keep_initial_conditions_and_only_change_mass():
    base = get_scenario("balance_practice")
    for name, mass in (("pole_mass_minus10", .09), ("pole_mass_plus10", .11)):
        changed = get_scenario(name)
        assert changed == replace(base, scenario_id=name, pole_mass_kg=mass)
        with EpisodeSession(get_episode_spec(name)) as session:
            assert session._env.unwrapped.masspole == mass


def test_driven_inverse_dynamics_equals_gym_force_model():
    original, driven = make_env(max_episode_steps=1000), make_env(max_episode_steps=1000)
    try:
        original.reset(seed=44)
        driven.reset(seed=44)
        for force in (0.0, 1.2, -2.0, 4.0, -3.0) * 3:
            state = State.from_sequence(original.unwrapped.state)
            acceleration, _ = accelerations_for_force(state, force)
            assert force_for_acceleration(state, acceleration) == pytest.approx(force, abs=1e-12)
            expected = original.step([force])
            actual = step_driven(driven, acceleration)
            np.testing.assert_allclose(actual[0], expected[0], atol=2e-8, rtol=0)
            np.testing.assert_allclose(driven.unwrapped.state, original.unwrapped.state, atol=1e-12)
            assert actual[1:4] == expected[1:4]
            if actual[2]:
                break
    finally:
        original.close()
        driven.close()


def test_velocity_plant_constant_load_and_target_schedule():
    with EpisodeSession(get_episode_spec("cart_velocity")) as session:
        first = session.step(.5)
        assert first.net_force_n == 0
        assert first.true_state == State()
        assert first.target_velocity_mps == .3
        next_result = session.step(1.5)
        assert next_result.true_state.v == pytest.approx(.02)
        assert next_result.true_state.theta == next_result.true_state.omega == 0


def test_gym_wrapper_uses_identical_physics_and_normalization():
    spec = get_episode_spec("tilt_right")
    env = make_scenario_env(spec, normalized_action=True)
    try:
        env.reset(seed=10)
        with EpisodeSession(spec) as session:
            actual = env.step(np.asarray([.2], np.float32))
            expected = session.step(float(np.float32(.2)) * 10)
            np.testing.assert_array_equal(actual[0], expected.observed_state.as_tuple())
            assert actual[4]["actuator_force_n"] == pytest.approx(2)
    finally:
        env.close()
    checked = make_scenario_env(spec)
    try:
        check_env(checked, skip_render_check=True)
    finally:
        checked.close()
