from copy import deepcopy
import csv
import json
import pytest

from control_lab.controllers import ZeroController
from control_lab.controllers.p import PController
from control_lab.controllers.pd import PDController
from control_lab.controllers.centering import CenteringFeedback
from control_lab.evaluation import evaluate, load_protocol, compare_reports
from control_lab.evaluation.protocol import EvaluationProtocol
from control_lab.evaluation.metrics import episode_metrics
from control_lab.evaluation.sweep import sweep
from control_lab.evaluation.rescore import rescore_trajectory, RewardConfig
from control_lab.evaluation.batch import controller_identity


def test_frozen_cases_are_explicit_nonzero_and_hash_validated():
    protocol = load_protocol()
    assert len(protocol.cases) == 20
    assert [case.seed for case in protocol.cases] == list(range(100, 120))
    assert all(.01 <= abs(case.initial_state[2]) <= .05 for case in protocol.cases)
    assert protocol.cases_hash == load_protocol().cases_hash
    damaged = protocol.definition
    damaged['cases'][0]['initial_state'][2] = 0
    with pytest.raises(ValueError, match='hash'):
        EvaluationProtocol(json.dumps(damaged))
    assert len(load_protocol(split='held_out').cases) == 20  # Loaded only, never evaluated.


def test_validation_baseline_reproducible_and_errors_keep_denominator(tmp_path):
    protocol = load_protocol()
    zero = evaluate(ZeroController, protocol)
    reference = evaluate(lambda: PDController(centering=CenteringFeedback()), protocol,
                         output_dir=tmp_path / 'reference', controller_name='PD+centering')
    repeated = evaluate(lambda: PDController(centering=CenteringFeedback()), protocol)
    assert zero['aggregate']['completed_episodes'] == 0
    assert reference['aggregate']['completed_episodes'] == 20
    assert reference['aggregate'] == repeated['aggregate']
    assert reference['controller_sha256'] == repeated['controller_sha256']
    assert reference['aggregate']['mean_steps'] == 500
    assert (tmp_path / 'reference' / 'controller_snapshot.json').is_file()
    assert len(compare_reports([zero, reference])['methods']) == 2
    class Broken:
        def reset(self):
            pass
        def act(self, state, dt):
            raise RuntimeError('intentional student bug')
    broken = evaluate(Broken, protocol)
    assert broken['aggregate']['episodes'] == broken['aggregate']['controller_errors'] == 20
    assert broken['aggregate']['completed_fraction'] == 0
    assert broken['aggregate']['worst_steps'] == 0
    assert compare_reports([reference, broken])
    incompatible = deepcopy(reference)
    incompatible['input_mode'] = 'manual_position_assist'
    with pytest.raises(ValueError, match='input_mode'):
        compare_reports([reference, incompatible])
    missing = deepcopy(reference)
    missing['episodes'].pop()
    with pytest.raises(ValueError, match='hash'):
        compare_reports([missing, missing])


def test_sweep_reuses_validation_and_rejects_held_out():
    result = sweep(PController, {'kp': [20, 60]})
    assert len(result['candidates']) == 2
    reports = [candidate['report'] for candidate in result['candidates']]
    assert reports[0]['cases_hash'] == reports[1]['cases_hash']
    assert reports[0]['aggregate']['mean_steps'] != reports[1]['aggregate']['mean_steps']
    with pytest.raises(ValueError, match='held-out'):
        sweep(PController, {'kp': [20]}, load_protocol(split='held_out'))
    with pytest.raises(ValueError, match='frozen'):
        evaluate(ZeroController, load_protocol(split='held_out'))


def test_metrics_and_rescore_use_true_state_and_actuator_force():
    rows = [dict(step_id=0, true_theta_rad=.1, true_x_m=.2, true_v_m_s=0,
                 observed_theta_rad=100, requested_force_n=15, actuator_force_n=10,
                 reward=1, terminated=False, truncated=True)]
    metrics = episode_metrics(rows, initial_state=[0, 0, 0, 0], max_steps=1)
    assert metrics['rms_theta_rad'] == pytest.approx((.01/2)**.5)
    assert metrics['rms_actuator_force_n'] == 10 and metrics['saturation_fraction'] == 1
    assert metrics['completed']
    result = rescore_trajectory(rows, RewardConfig(theta_weight=2, position_weight=3, force_weight=.01))
    assert result['rescored_return'] == pytest.approx(1 - .02 - .12 - 1)
    assert rows[0]['reward'] == 1 and result['rollout_unchanged']


def test_private_parameters_and_model_identity_change_frozen_fingerprint():
    class Feedback:
        def __init__(self, gain):
            self._gain = gain
    assert controller_identity(Feedback(1))[0] != controller_identity(Feedback(2))[0]
    class Policy:
        def __init__(self, model_hash):
            self._model = object()
            self.model_hash = model_hash
        def evaluation_identity(self):
            return {'model_sha256': self.model_hash, 'action_scale_n': 10}
    assert controller_identity(Policy('a'))[0] != controller_identity(Policy('b'))[0]
