"""Behavioral regression checks for extracting the standalone teaching project."""
from pathlib import Path

import gymnasium as gym
import numpy as np
import pytest

from control_lab.cli import init_workspace
from control_lab.envs.cartpole import make_env
from control_lab.runner import RunConfig, run_experiment


def test_continuous_extremes_match_original_physics():
    original, continuous = gym.make('CartPole-v1'), make_env()
    try:
        original.reset(seed=42)
        continuous.reset(seed=42)
        for direction in [1, 0] * 8:
            a = original.step(direction)
            b = continuous.step([10.0 if direction else -10.0])
            np.testing.assert_array_equal(a[0], b[0])
            assert a[1:4] == b[1:4]
            if a[2] or a[3]:
                break
    finally:
        original.close()
        continuous.close()


def test_force_clipping_and_invalid_values():
    env = make_env()
    try:
        env.reset(seed=42)
        *_, info = env.step([500.0])
        assert info['applied_force'] == 10.0
        assert info['commanded_force'] == 500.0
        with pytest.raises(ValueError):
            env.step([float('nan')])
    finally:
        env.close()


def test_student_workspace_preserves_edits(tmp_path):
    assert init_workspace(tmp_path) == 0
    student = tmp_path / 'my_controller.py'
    student.write_text('# user changes\n', encoding='utf-8')
    assert init_workspace(tmp_path) == 0
    assert student.read_text(encoding='utf-8') == '# user changes\n'


def test_reference_runner_records_complete_episodes(tmp_path):
    report = run_experiment(RunConfig(controller='reference', episodes=3, seed=10042, output_dir=tmp_path))
    assert report['status'] == 'completed'
    assert report['mean_return'] == 500.0
    assert (tmp_path / 'controller_snapshot.py').is_file()
    with pytest.raises(FileExistsError):
        run_experiment(RunConfig(controller='reference', output_dir=tmp_path))


def test_invalid_student_code_creates_error_report(tmp_path):
    source = tmp_path / 'bad.py'
    source.write_text('raise ValueError("student experiment")\n', encoding='utf-8')
    output = tmp_path / 'results'
    report = run_experiment(RunConfig(controller='student', controller_file=source, output_dir=output))
    assert report['status'] == 'error'
    assert report['completed_episodes'] == 0
    assert report['error']['type'] == 'ValueError'
    assert 'student experiment' in (output / 'error.txt').read_text(encoding='utf-8')
