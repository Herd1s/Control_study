import numpy as np
import pytest
from control_lab.inputs.adapters import controller_from_source, FunctionControllerAdapter, LegacyControllerAdapter, load_controller
from control_lab.core.types import State


def test_short_function_loaded_once_and_reset_each_episode():
    source = '''
elapsed = 0
loads = 1
resets = 0
def reset():
    global elapsed, resets
    elapsed = 0
    resets += 1
def control(state, dt):
    global elapsed
    elapsed += dt
    state['x'] = 999
    return elapsed
'''
    adapter = controller_from_source(source)
    state = State(theta=.05)
    for _ in range(2):
        adapter.reset()
        assert adapter.act(state, .02) == .02
        assert adapter.act(state, .02) == .04
    assert state.x == 0
    assert adapter.module.loads == 1 and adapter.module.resets == 2


def test_legacy_controller_receives_array_copy_and_dataclass_loads(tmp_path):
    source = '''
from dataclasses import dataclass
@dataclass
class Controller:
    calls: int = 0
    def reset(self):
        self.calls = 0
    def act(self, observation, dt):
        observation[:] = 99
        self.calls += 1
        return float(self.calls)
'''
    path = tmp_path / 'student.py'
    path.write_text(source)
    adapter = load_controller(path)
    array = np.zeros(4)
    adapter.reset()
    assert adapter.act(array, .02) == 1
    np.testing.assert_array_equal(array, np.zeros(4))
    assert adapter.source == path.read_bytes()  # Preserve Windows CRLF exactly.


def test_optional_reset_and_invalid_actions():
    adapter = controller_from_source('def control(state,dt): return state["theta"]')
    adapter.reset()
    assert adapter.act([0, 0, .05, 0], .02) == .05
    for value in (True, '1', None, float('nan'), float('inf'), np.array([1.])):
        bad = FunctionControllerAdapter(lambda state, dt: value)
        with pytest.raises((ValueError, TypeError)):
            bad.act([0, 0, 0, 0], .02)


def test_same_source_loads_have_independent_memory():
    source = 'n=0\ndef control(state,dt):\n global n\n n+=1\n return n\n'
    first, second = controller_from_source(source), controller_from_source(source)
    assert first.act([0]*4, .02) == first.act([0]*4, .02) - 1
    assert second.act([0]*4, .02) == 1


def test_function_context_is_copied_and_cannot_replace_measurement():
    adapter = controller_from_source('def control(state,dt): return state["target_v"] + state["time_s"] + state["theta"]')
    observation = dict(x=0, v=0, theta=.05, omega=0, target_v=.3, time_s=2.)
    assert adapter.act(observation, .02) == pytest.approx(2.35)
    assert adapter.act(observation, .02, context={"time_s": 1.}) == pytest.approx(1.35)
    assert observation["time_s"] == 2.
    with pytest.raises(ValueError, match='cannot be replaced'):
        adapter.act(observation, .02, context={"theta": 1.})
