import math
import numpy as np
import pytest

from control_lab.controllers.p import PController
from control_lab.controllers.pd import PDController
from control_lab.controllers.pid import PIDController, VelocityPIController
from control_lab.controllers.centering import CenteringFeedback
from control_lab.controllers.filters import FirstOrderLowPass, FilteredDerivative
from control_lab.controllers.reference_pid import Controller as OldReference


def test_mirror_force_and_velocity_information():
    p, pd = PController(60), PDController(60, 12)
    assert p.act([0, 0, .05, .15], .02) == p.act([0, 0, .05, -.15], .02) == 3
    assert pd.act([0, 0, .05, .15], .02) == pytest.approx(4.8)
    assert pd.act([0, 0, -.05, -.15], .02) == pytest.approx(-4.8)


def test_reference_compatibility_and_components():
    old = OldReference()
    new = PIDController(centering=CenteringFeedback())
    for state in ([.2, 0, .05, .15], [-.1, .2, -.03, -.1], [0, 0, .4, 0]):
        assert new.act(state, .02) == pytest.approx(old.act(state, .02))
        parts = new.diagnostics
        assert parts["unsaturated_n"] == pytest.approx(sum(parts[k] for k in ("p_n", "d_n", "i_n", "centering_n")))
    assert new.diagnostics["unsaturated_n"] == 24
    assert new.diagnostics["applied_n"] == 10
    assert new.integral == 0  # Ki=0 is an intentional PD controller.


def test_conditional_integral_holds_and_unwinds_then_reset():
    controller = VelocityPIController(0, 1, target_velocity_mps=10, force_limit_n=1)
    for _ in range(20):
        controller.act([0, 0, 0, 0], .1)
    assert controller.integral == 1
    assert controller.diagnostics["integral_frozen"]
    controller.target_velocity_mps = -1
    controller.act([0, 0, 0, 0], .1)
    assert controller.integral == pytest.approx(.9)
    assert not controller.diagnostics["integral_frozen"]
    controller.reset()
    assert controller.integral == 0


def test_unwind_allowed_even_when_output_remains_saturated():
    controller = PIDController(0, 1, 0, force_limit_n=1, integral_limit=None)
    controller.integral = 5  # Existing windup from a previous operating condition.
    assert controller.act([0, 0, -1, 0], .1) == pytest.approx(4.9)
    assert not controller.diagnostics["integral_frozen"]


def test_naive_integral_demonstrates_windup_and_pi_rejects_load():
    antiwindup = VelocityPIController(2, 1, target_velocity_mps=4, force_limit_n=1)
    naive = VelocityPIController(2, 1, target_velocity_mps=4, force_limit_n=1, anti_windup=False)
    for _ in range(200):
        antiwindup.act([0, 0, 0, 0], .02)
        naive.act([0, 0, 0, 0], .02)
    assert antiwindup.integral == 0 and naive.integral > 15
    # The documented independent cart model, v_dot=(u-.5*v-.5)/1.
    finals = []
    for ki in (0, 1):
        controller = VelocityPIController(2, ki)
        v = 0.
        for _ in range(1500):
            u = np.clip(controller.act([0, v, 0, 0], .02), -10, 10)
            v += .02 * (u - .5 * v - .5)
        finals.append(v)
    assert finals[0] == pytest.approx(.04, abs=1e-6)
    assert finals[1] == pytest.approx(.3, abs=1e-5)


def test_filter_time_constant_does_not_depend_on_step_count():
    final = []
    for dt in (.01, .02):
        filt = FirstOrderLowPass(.1)
        filt.reset(0)
        for _ in range(round(.2 / dt)):
            result = filt.update(1, dt)
        final.append(result)
    assert final == pytest.approx([1-math.exp(-2)] * 2)
    derivative = FilteredDerivative(0)
    assert derivative.update(10, .02) == 0
    assert derivative.update(10.1, .02) == pytest.approx(5)
    derivative.reset()
    assert derivative.update(-10, .02) == 0


@pytest.mark.parametrize("invalid", [True, "1", float("nan"), float("inf")])
def test_controller_rejects_invalid_states_or_dt(invalid):
    with pytest.raises((ValueError, TypeError)):
        PController().act([0, 0, invalid, 0], .02)
    with pytest.raises((ValueError, TypeError)):
        PController().act([0, 0, 0, 0], invalid)
