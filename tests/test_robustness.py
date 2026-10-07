import json
from dataclasses import asdict

from control_lab.evaluation import load_protocol
from control_lab.rl.robustness import run_robustness, run_paired_robustness, robustness_spec, FACTOR_DEFINITIONS, FrozenPD


class Zero:
    def reset(self):
        pass

    def act(self, observation, dt):
        return 0.


def test_factors_change_only_declared_fields_and_keep_explicit_cases():
    protocol = load_protocol(split="practice")
    case = protocol.cases[0]
    baseline = asdict(robustness_spec(protocol, case, "baseline"))
    for factor, definition in FACTOR_DEFINITIONS.items():
        actual = asdict(robustness_spec(protocol, case, factor))
        assert actual["scenario"]["initial_state"] == baseline["scenario"]["initial_state"]
        assert actual["dt_s"] == .02 and actual["force_limit_n"] == 10
        delta = {key for key, value in actual["scenario"].items() if value != baseline["scenario"][key]}
        assert delta <= {"scenario_id", *definition["changes"]}


def test_complete_robustness_study_keeps_all_failures_and_specs(tmp_path):
    events = []
    report = run_robustness(Zero(), tmp_path/"study", identity={"kind": "zero"}, progress=events.append)
    assert report["status"] == "completed" and len(events) == 35
    assert report["standard_balance_score"] is False and report["policy_updated"] is False
    assert len(report["groups"]) == 7
    case_ids = None
    for group in report["groups"]:
        assert group["aggregate"]["episodes"] == 5
        assert group["aggregate"]["controller_errors"] == 0
        assert group["aggregate"]["completed_episodes"] == 0
        current_ids = [episode["case_id"] for episode in group["episodes"]]
        assert case_ids is None or current_ids == case_ids
        case_ids = current_ids
        for episode in group["episodes"]:
            trajectory = tmp_path/"study"/episode["trajectory"]
            assert trajectory.is_file() and (trajectory.parent/"spec.json").is_file()
    assert (tmp_path/"study/report.html").is_file()


def test_stopped_study_is_partial_and_never_success(tmp_path):
    stop = tmp_path/"STOP"
    def cancel_after_one(progress):
        stop.write_text("stop", encoding="utf-8")
    report = run_robustness(Zero(), tmp_path/"study", identity={"kind": "zero"},
                            stop_file=stop, progress=cancel_after_one)
    assert report["status"] == "stopped"
    assert sum(len(group["episodes"]) for group in report["groups"]) == 1
    assert json.loads((tmp_path/"study/report.json").read_text(encoding="utf-8"))["status"] == "stopped"


def test_pd_and_policy_pair_share_specs_and_seeded_noise(tmp_path):
    first, second = FrozenPD(), FrozenPD()
    events = []
    report = run_paired_robustness({"pd": first, "ppo": second}, tmp_path/"pair",
        identities={"pd": first.evaluation_identity(), "ppo": {"test_policy": "same_formula"}},
        factors=("baseline", "measurement_theta_noise", "external_force_pulse"), progress=events.append)
    assert report["status"] == "completed" and report["paired_specs_verified"]
    assert len(events) == 30 and events[-1]["completed"] == events[-1]["total"] == 30
    groups = report["groups"]
    for pd_group, ppo_group in zip(groups[:3], groups[3:]):
        for pd_case, ppo_case in zip(pd_group["episodes"], ppo_group["episodes"]):
            assert pd_case["spec_hash"] == ppo_case["spec_hash"]
            assert (tmp_path/"pair"/pd_case["trajectory"]).read_bytes() == (tmp_path/"pair"/ppo_case["trajectory"]).read_bytes()
    pulse = robustness_spec(load_protocol(split="practice"), load_protocol(split="practice").cases[0], "external_force_pulse")
    assert pulse.scenario.disturbance_at(99) == 0
    assert pulse.scenario.disturbance_at(100) == 1
    assert pulse.scenario.disturbance_at(105) == 0
