import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from control_lab.rl.rewards import (normalize_reward_config, resolve_reward_config,
    load_reward_config, reward_components)
from control_lab.rl.env_factory import make_training_env, demonstrate_contract
from control_lab.rl.reward_analysis import analyze_rewards, rescore_rows
from control_lab.rl.artifacts import save_artifact, validate_artifact


def custom_config():
    return {"schema_version": 1, "reward_id": "lesson-effort-v1", "version": 1,
            "alive": 1., "angle": .6, "position": .2, "effort": .2}


def test_cancelled_model_evaluation_never_becomes_complete(tmp_path, monkeypatch):
    import control_lab.rl.evaluate as module
    class Adapter:
        _metadata = {"training": {"seed": 0}}
        def reset(self):
            pass
        def act(self, observation, dt):
            raise AssertionError("Cancelled evaluation must not request an action")
        def evaluation_identity(self):
            return {"test": "cancelled adapter"}
    monkeypatch.setattr(module, "load_policy_adapter", lambda *args, **kwargs: Adapter())
    stop = tmp_path/"STOP"
    stop.touch()
    report = module.evaluate_model(tmp_path/"unused-model", split="practice", output_dir=tmp_path/"evaluation", stop_file=stop)
    assert report["status"] == "cancelled" and report["is_complete"] is False
    assert not report["episodes"]


def write_csv(path, evaluation=False, force=2.):
    fields = (["time_s", "true_theta_rad", "true_x_m", "actuator_force_n"] if evaluation
              else ["simulation_time_s", "true_theta", "true_x", "actuator_force_n"])
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows([[.02*i, .04, .12, force] for i in range(1, 11)])


def test_versioned_config_rejects_aliases_nonfinite_and_builtin_overwrite(tmp_path):
    original = custom_config()
    normalized = normalize_reward_config(original)
    original["effort"] = 30
    assert normalized["effort"] == .2
    for changed in ({"effort": float("nan")}, {"effort": -1}, {"reward_id": "../outside"},
                    {"version": True}, {"schema_version": True}, {"reward_id": "balanced-v1"}):
        with pytest.raises(ValueError):
            normalize_reward_config({**custom_config(), **changed})
    path = tmp_path / "reward.json"
    path.write_text(json.dumps(custom_config()), encoding="utf-8")
    assert load_reward_config(path) == custom_config()


def test_offline_training_and_builtin_formula_are_identical():
    config = custom_config()
    env = make_training_env(seed=42, reward_id=config["reward_id"], reward_config=config)
    try:
        env.reset(seed=42)
        _, actual, _, _, info = env.step(np.array([.3], dtype=np.float32))
        true = info["true_state"]
        row = {"step_id": 0, "time_s": .02, "x": true["x"], "theta": true["theta"], "force_n": info["actuator_force_n"]}
        scored = rescore_rows([row], config)
        assert scored["return"] == pytest.approx(actual)
        assert scored["rows"][0]["effort"] == pytest.approx(-.2*(3/10)**2)
        builtin = reward_components("balanced-v1", true, info["actuator_force_n"])
        assert scored["rows"][0]["effort"] == pytest.approx(10*builtin["effort"])
        assert env.contract["reward_definition"]["effort"] == .2
    finally:
        env.close()


def test_reward_analysis_two_schemas_original_unchanged_and_all_outputs(tmp_path):
    first, second = tmp_path/"classroom.csv", tmp_path/"evaluation.csv"
    write_csv(first)
    write_csv(second, evaluation=True, force=4)
    before = first.read_bytes(), second.read_bytes()
    result = analyze_rewards([first, second], [resolve_reward_config("survival-v1"),
        resolve_reward_config("balanced-v1"), custom_config()], tmp_path/"report")
    assert result["trajectories"] == 2
    report = result["report"]
    assert report["rollout_unchanged"] and report["policy_updated"] is False
    assert len(report["results"]) == 6
    assert report["results"][0]["return"] == 10
    assert report["results"][2]["parts"]["effort"] == pytest.approx(10*report["results"][1]["parts"]["effort"])
    assert report["results"][5]["parts"]["effort"] == pytest.approx(4*report["results"][2]["parts"]["effort"])
    assert before == (first.read_bytes(), second.read_bytes())
    assert Path(result["html"]).is_file()
    assert len(list((tmp_path/"report").glob("*.csv"))) == 6
    with pytest.raises(FileExistsError):
        analyze_rewards([first], [custom_config()], tmp_path/"report")


def test_custom_reward_is_saved_and_checked_in_model_contract(tmp_path):
    class Model:
        def save(self, path):
            Path(path).write_bytes(b"test-policy")
    config = custom_config()
    directory = save_artifact(Model(), tmp_path/"model", reward_id=config["reward_id"], reward_config=config,
        status="completed", training={"seed": 0, "requested_timesteps": 256, "actual_timesteps": 256})
    metadata = validate_artifact(directory)
    assert metadata["environment"]["reward_definition"]["effort"] == .2
    changed = json.loads((directory/"metadata.json").read_text(encoding="utf-8"))
    changed["environment"]["reward_definition"]["effort"] = .02
    (directory/"metadata.json").write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        validate_artifact(directory)


def test_doctor_examples_run_actual_termination_and_truncation():
    report = demonstrate_contract()
    assert report["policy_trained"] is False
    assert abs(report["initial_observation"][2]) >= .01
    assert [row["actuator_force_n"] for row in report["mappings"]] == [-10, 0, 10]
    zero, reference = report["examples"]["zero_force"], report["examples"]["reference_feedback"]
    assert zero["terminated"] and not zero["truncated"] and zero["steps"] < 500
    assert reference["truncated"] and not reference["terminated"] and reference["steps"] == 500
