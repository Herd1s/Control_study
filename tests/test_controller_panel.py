"""Generated lesson controllers are executed, not just compared as strings."""
import ast
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from control_lab.core.scenario import get_episode_spec, seeded_scenario
from control_lab.core.session import EpisodeSession
from control_lab.core.types import EpisodeSpec, State
from control_lab.desktop.panels.controller import ControllerPanel


@pytest.fixture(scope="module")
def qt_app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def panel(qt_app):
    widget = ControllerPanel()
    widget.resize(326, 720)
    yield widget
    widget.close()
    widget.deleteLater()
    qt_app.processEvents()


def load_generated(panel):
    code = panel.generate_code()
    ast.parse(code)
    namespace = {}
    exec(compile(code, "<panel-controller>", "exec"), namespace)
    namespace["reset"]()
    return namespace


def test_parameters_only_emit_source_after_explicit_apply(panel):
    spy = QSignalSpy(panel.codeRequested)
    panel.fields["kp"].setValue(40)
    assert spy.count() == 0
    panel.set_running(True)
    assert not panel.apply_button.isEnabled()
    panel._apply()
    assert spy.count() == 0
    panel.set_running(False)
    panel.apply_button.click()
    assert spy.count() == 1
    assert "kp = 40.0" in spy.at(0)[0]


def test_progressive_fields_and_all_generated_templates_are_executable(panel):
    for number in range(13, 23):
        panel.set_lesson(f"L{number}")
        namespace = load_generated(panel)
        state = State(theta=.03, omega=.01).as_dict()
        state["target_v"] = .3
        assert math.isfinite(namespace["control"](state, .02))
        assert isinstance(namespace["diagnostics"](), dict)
    panel.set_lesson("L13")
    assert panel.fields["kd"].isHidden()
    assert panel.fields["ki"].isHidden()
    panel.set_lesson("L15")
    assert not panel.fields["kd"].isHidden()
    assert panel.fields["ki"].isHidden()
    panel.set_lesson("L17")
    assert panel.fields["kd"].isHidden()
    assert not panel.fields["ki"].isHidden()
    panel.set_lesson("L20")
    assert not panel.fields["tau"].isHidden()
    panel.set_lesson("L05")
    assert panel.isHidden()
    with pytest.raises(ValueError):
        panel.generate_code()


def test_elementary_generated_signs_and_real_contributions(panel):
    panel.set_lesson("L13")
    controller = load_generated(panel)
    assert controller["control"](State(theta=.05).as_dict(), .02) == 3
    assert controller["diagnostics"]()["p_n"] == 3
    assert "d_n" not in controller["diagnostics"]()
    panel.set_lesson("L16")
    controller = load_generated(panel)
    assert controller["control"](State(x=.2).as_dict(), .02) == pytest.approx(.4)
    assert controller["diagnostics"]()["centering_n"] == pytest.approx(.4)


def test_generated_default_centered_controller_balances_nonzero_cases(panel):
    for lesson in ("L16", "L19"):
        panel.set_lesson(lesson)
        controller = load_generated(panel)
        for seed in (100, 101, 102):
            spec = EpisodeSpec("panel-regression", seeded_scenario(seed), require_nonzero_initial=True)
            controller["reset"]()
            with EpisodeSession(spec) as session:
                while not session.finished:
                    force = controller["control"](session.observed_state.as_dict(), session.dt)
                    result = session.step(force)
                assert result.truncated and not result.terminated


def test_generated_velocity_antiwindup_recovers_after_target_drop(panel):
    panel.set_lesson("L18")
    results = {}
    for mode in ("none", "limit", "conditional"):
        panel.anti_windup.setCurrentIndex(panel.anti_windup.findData(mode))
        controller = load_generated(panel)
        with EpisodeSession(get_episode_spec("cart_velocity_windup")) as session:
            while not session.finished:
                state = session.observed_state.as_dict()
                state["target_v"] = session.target_velocity_mps
                force = controller["control"](state, session.dt)
                session.step(force)
                if session.step_index == 200:
                    first_integral = controller["diagnostics"]()["integral"]
            results[mode] = (first_integral, abs(session.true_state.v - .3))
        controller["reset"]()
        assert controller["diagnostics"]()["integral"] == 0
    assert results["none"][0] > 1
    assert results["conditional"][0] == 0
    assert results["conditional"][1] < .03
    assert results["conditional"][1] < results["none"][1]


def test_generated_filter_uses_physical_dt_and_clears_memory(panel):
    panel.set_lesson("L20")
    controller = load_generated(panel)
    controller["control"](State(omega=1).as_dict(), .02)
    controller["control"](State().as_dict(), .02)
    assert controller["diagnostics"]()["d_n"] == pytest.approx(12 * math.exp(-.02 / .05))
    controller["reset"]()
    assert controller["control"](State().as_dict(), .02) == 0


def test_diagnostics_never_infer_missing_or_invalid_components(panel):
    panel.set_diagnostics({"p_n": 1.25, "d_n": float("nan"), "i_n": True, "frozen": True})
    assert "+1.250 N" in panel.diagnostic_labels["p_n"][1].text()
    assert panel.diagnostic_labels["d_n"][1].text().endswith("—")
    assert panel.diagnostic_labels["i_n"][1].text().endswith("—")
    assert "冻结" in panel.diagnostic_status.text()
    panel.set_diagnostics({})
    assert "未提供" in panel.diagnostic_status.text()
