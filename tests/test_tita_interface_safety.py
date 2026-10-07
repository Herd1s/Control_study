"""Interface provenance and real simulated command-gate failures are observable."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from control_lab.integrations.tita_interface import (
    INTERFACE_PROBE, check_policy_compatibility, interface_summary, load_interface,
)
from control_lab.integrations.tita_safety import MockCommandGate, run_safety_experiment
from control_lab.lessons import load_lesson
from control_lab.lessons.rules import evaluate_rule


@pytest.fixture
def interface_path(tmp_path):
    data = dict(schema_version=1, kind="tita_runtime_interface", environment_id="DDT-Velocity-Flat-Tita-v0",
        control_dt_s=.02, hardware_control=False,
        observation_groups={"policy": {"tensor_shape": [1, 10, 33], "terms": [
            dict(start=0, stop=3, name="base_ang_vel", components=["x", "y", "z"], raw_units=["rad/s"]*3, scale=.25)]}},
        actions=[dict(index=i, joint=f"joint_{i}", type="JointPositionAction", target_unit="rad",
                      scale=.25, offset=.1, clip={".*": [-100,100]}) for i in range(8)],
        train_play_differences=[], zero_action_note="Raw zero is not motor disable.")
    data["interface_sha256"] = hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    path = tmp_path / "interface.json"
    path.write_text(json.dumps(data),encoding="utf-8")
    return path


def test_interface_provenance_tampering_and_no_robotics_import(interface_path):
    before = set(sys.modules)
    compile(INTERFACE_PROBE, "external_probe", "exec")
    data = load_interface(interface_path)
    assert "[1, 10, 33]" in interface_summary(data)
    data["actions"][0]["scale"] = 500
    interface_path.write_text(json.dumps(data),encoding="utf-8")
    with pytest.raises(ValueError, match="SHA256"):
        load_interface(interface_path)
    assert not any(n.startswith(("torch", "isaaclab", "isaacsim")) for n in set(sys.modules)-before)


def test_model_identity_and_shape_must_all_match(interface_path):
    interface = load_interface(interface_path)
    metadata = dict(environment_id=interface["environment_id"], observation_shape=[10,33], action_dim=8,
                    interface_sha256=interface["interface_sha256"])
    assert check_policy_compatibility(interface,metadata)["compatible"]
    for key, value in (("environment_id","ContinuousCartPole"),("observation_shape",[4]),
                       ("action_dim",1),("interface_sha256","changed")):
        result = check_policy_compatibility(interface,{**metadata,key:value})
        assert not result["compatible"] and len(result["reasons"]) == 1
        assert result["model_executed"] is False
    cartpole = dict(environment={"environment_id": "control-lab-continuous-balance-training-v1",
                                "observation": {"fields": ["x", "v", "theta", "omega"]},
                                "action": {"fields": ["normalized_force"]}})
    result = check_policy_compatibility(interface, cartpole)
    assert result["candidate_interface"]["observation_shape"] == [4]
    assert result["candidate_interface"]["action_dim"] == 1 and not result["compatible"]
    with pytest.raises(ValueError, match="可识别"):
        check_policy_compatibility(interface, {})


def test_timeout_stop_and_latched_emergency_require_fresh_command():
    gate = MockCommandGate(2)
    assert gate.receive([2,-3],0)
    assert gate.sample(.02) == ((1.,-1.),True,"active")
    assert gate.sample(.06) == ((0.,0.),False,"timeout")
    gate.receive([.5,.5],.08)
    gate.emergency_stop(.09)
    assert not gate.receive([1,1],.10)
    with pytest.raises(ValueError,match="explicit"):
        gate.rearm(.10)
    assert gate.sample(.11) == ((0.,0.),False,"emergency_stop")
    gate.rearm(.12,explicit=True)
    assert gate.sample(.12) == ((0.,0.),False,"stopped")
    gate.receive([.5,.5],.13)
    assert gate.sample(.13)[1] is True
    gate.stop(.14)
    assert gate.sample(.15)[0] == (0.,0.)


@pytest.mark.parametrize("bad", [[1], [float("nan"),0], [float("inf"),1], ["bad",0], None])
def test_invalid_command_disables_mock_actuator(bad):
    gate=MockCommandGate(2)
    gate.receive([.5,.5],0)
    with pytest.raises(ValueError): gate.receive(bad,.02)
    assert gate.sample(.03)[1] is False
    with pytest.raises(ValueError,match="monotonic"): gate.sample(-1)


def test_experiment_records_actual_trace_and_detects_broken_stop(interface_path,tmp_path):
    path, report = run_safety_experiment(interface_path,tmp_path/"good")
    assert report["passed"] and len(report["cases"]) == 4 and report["trace_rows"] == 18
    assert report["ready_for_hardware"] is False
    assert report["trace_sha256"] == hashlib.sha256(path.with_name("trace.csv").read_bytes()).hexdigest()
    _, duplicate = run_safety_experiment(interface_path,tmp_path/"repeat")
    assert duplicate == report
    with pytest.raises(FileExistsError): run_safety_experiment(interface_path,tmp_path/"good")
    class BrokenStop(MockCommandGate):
        def stop(self,now_s): self._time(now_s)
    _, failed = run_safety_experiment(interface_path,tmp_path/"broken",gate_factory=BrokenStop)
    assert failed["passed"] is False
    assert any(not c["passed"] and c["failures"] for c in failed["cases"])


def test_lesson_evidence_cannot_be_replaced_by_acknowledgement():
    for lesson_id, step_id, kind in (("L30","step_03","tita_interface"),
                                     ("L30","step_06","tita_incompatible_model"),
                                     ("L32","step_03","tita_safety")):
        lesson=load_lesson(lesson_id)
        rule=next(s.completion for s in lesson.steps if s.id==step_id)
        assert not evaluate_rule(rule,[dict(event="step.acknowledged",payload={})])
        assert evaluate_rule(rule,[dict(event="external.verified",payload={"kind":kind})])


def test_panel_saves_actual_external_result_and_runs_mock(interface_path,tmp_path,monkeypatch):
    from control_lab.desktop.panels import tita
    from control_lab.integrations.tita_profile import ExternalCommand
    app=QApplication.instance() or QApplication([])
    output=tmp_path/'data/tita/interfaces/external/interface.json'
    code="import pathlib,sys; p=pathlib.Path(sys.argv[2]);p.parent.mkdir(parents=True);p.write_bytes(pathlib.Path(sys.argv[1]).read_bytes())"
    command=ExternalCommand(sys.executable,('-u','-c',code,str(interface_path),str(output)),str(tmp_path),{},'interface','test')
    monkeypatch.setattr(tita,'build_command',lambda *args,**kwargs:command)
    panel=tita.TitaPanel(tmp_path/'data')
    saved, completed, safety = QSignalSpy(panel.interfaceSaved),QSignalSpy(panel.runFinished),QSignalSpy(panel.safetyValidated)
    try:
        panel.start('interface')
        deadline=time.monotonic()+8
        while completed.count()==0 and time.monotonic()<deadline:
            app.processEvents();QTest.qWait(10)
        assert completed.count()==saved.count()==1
        assert completed.at(0)[0]['status']=='completed'
        assert Path(saved.at(0)[0]['report_path']).is_file()
        panel.run_safety()
        assert safety.count()==1 and safety.at(0)[0]['report']['passed']
        rejected=QSignalSpy(panel.compatibilityChecked)
        cart=tmp_path/'metadata.json';cart.write_text('{"environment_id":"CartPole","observation_shape":[4],"action_dim":1}')
        panel.check_compatibility(metadata_path=cart)
        assert rejected.count()==1 and rejected.at(0)[0]['compatible'] is False
    finally:
        panel.shutdown();panel.close();panel.deleteLater();app.processEvents()
