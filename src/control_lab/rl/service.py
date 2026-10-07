"""External Python JSON-lines service; never runs training in the Qt process."""
import argparse
import json
from pathlib import Path
import sys
import time
import traceback


def emit(kind, **values):
    print(json.dumps({"type": kind, **values}, ensure_ascii=False, allow_nan=False), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    training = sub.add_parser("train")
    training.add_argument("--output-dir", type=Path, required=True)
    training.add_argument("--steps", type=int, default=25600)
    training.add_argument("--seed", type=int, default=0)
    training.add_argument("--reward", choices=("survival-v1", "balanced-v1"), default="survival-v1")
    training.add_argument("--reward-config", type=Path)
    training.add_argument("--stop-file", type=Path)
    training.add_argument("--resume-from", type=Path)
    baseline = sub.add_parser("baseline")
    baseline.add_argument("--output-dir", type=Path, required=True)
    baseline.add_argument("--seed", type=int, default=0)
    baseline.add_argument("--stop-file", type=Path)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--model-dir", type=Path, required=True)
    evaluation.add_argument("--output-dir", type=Path, required=True)
    evaluation.add_argument("--split", choices=("practice", "validation", "held_out"), default="validation")
    evaluation.add_argument("--frozen-controller-sha256")
    evaluation.add_argument("--validation-report", type=Path)
    evaluation.add_argument("--stop-file", type=Path)
    replay = sub.add_parser("replay")
    replay.add_argument("--model-dir", type=Path, required=True)
    replay.add_argument("--case-index", type=int, default=0)
    replay.add_argument("--speed", type=float, default=1.0)
    replay.add_argument("--stop-file", type=Path)
    robustness = sub.add_parser("robustness")
    robustness.add_argument("--model-dir", type=Path, required=True)
    robustness.add_argument("--output-dir", type=Path, required=True)
    robustness.add_argument("--stop-file", type=Path)
    robustness.add_argument("--pd-gains", nargs=4, type=float, default=(60., 12., 2., 3.),
                            metavar=("THETA", "OMEGA", "X", "V"))
    args = parser.parse_args(argv)
    from .evaluate import StopRequested
    try:
        if args.command == "doctor":
            import torch
            import stable_baselines3
            from .artifacts import runtime_versions
            from .env_factory import make_training_env, demonstrate_contract
            from stable_baselines3.common.env_checker import check_env
            env = make_training_env()
            try:
                check_env(env, warn=False)
            finally:
                env.close()
            emit("doctor", status="ready", python=sys.executable,
                 versions=runtime_versions(), device="cpu", contract_examples=demonstrate_contract())
        elif args.command == "baseline":
            from .train import create_untrained_baseline
            result = create_untrained_baseline(args.output_dir, seed=args.seed, stop_file=args.stop_file)
            emit("baseline", status="completed", path=result["artifact"], report=result["report"],
                 aggregate=result["aggregate"], training_steps=0)
        elif args.command == "train":
            from .train import TrainConfig, train
            from .rewards import load_reward_config
            config = load_reward_config(args.reward_config) if args.reward_config else None
            train(TrainConfig(args.output_dir, args.steps, args.seed, config["reward_id"] if config else args.reward,
                              stop_file=args.stop_file, resume_from=args.resume_from, reward_config=config))
        elif args.command == "evaluate":
            from .evaluate import evaluate_model
            emit("started", operation="evaluate", split=args.split)
            report = evaluate_model(args.model_dir, split=args.split, output_dir=args.output_dir,
                                    frozen_controller_sha256=args.frozen_controller_sha256,
                                    validation_report=args.validation_report,
                                    stop_file=args.stop_file)
            emit("evaluation" if report.get("is_complete", True) else "stopped",
                 status="completed" if report.get("is_complete", True) else "stopped", path=str(args.output_dir.resolve()),
                 aggregate=report["aggregate"], controller_sha256=report["controller_sha256"], split=report["split"])
        elif args.command == "robustness":
            from .robustness import compare_model_robustness
            report = compare_model_robustness(args.model_dir, args.output_dir, pd_gains=args.pd_gains, stop_file=args.stop_file,
                progress=lambda value: emit("robustness_progress", **value))
            emit("robustness", status=report["status"], path=str(args.output_dir/"report.json"),
                 html=str(args.output_dir/"report.html"), groups=len(report["groups"]), study_hash=report["study_hash"],
                 methods=list(report["definition"]["methods"]), paired_specs_verified=report["paired_specs_verified"])
        elif args.command == "replay":
            if not .1 <= args.speed <= 10:
                raise ValueError("Replay speed must be between .1 and 10")
            from control_lab.evaluation import load_protocol
            from control_lab.core.session import EpisodeSession
            from .evaluate import load_policy_adapter
            protocol = load_protocol(split="validation")
            if not 0 <= args.case_index < len(protocol.cases):
                raise ValueError("Replay case index is outside the validation set")
            case = protocol.cases[args.case_index]
            controller = load_policy_adapter(args.model_dir, stop_file=args.stop_file)
            session = EpisodeSession(protocol.spec_for(case))
            try:
                controller.reset()
                emit("started", operation="replay", scenario=case.case_id, input_mode="force_n")
                emit("replay_state", state=list(session.true_state), force=0.0,
                     step_count=0, scenario=case.case_id, input_mode="force_n")
                while not session.finished:
                    force = controller.act(session.observed_state, session.dt)
                    result = session.step(force)
                    emit("replay_state", state=list(result.true_state), force=result.actuator_force_n,
                         step_count=result.step_id, scenario=case.case_id, input_mode="force_n")
                    time.sleep(session.dt / args.speed)
                emit("replay_completed", status="completed", step_count=session.step_index,
                     end_reason=result.end_reason, scenario=case.case_id)
            finally:
                session.close()
        return 0
    except StopRequested:
        emit("stopped", status="stopped", operation=args.command,
             message="操作已停止；已经写入的实验文件保留，未完成结果不算完整评价。")
        return 0
    except Exception as exc:
        emit("error", operation=args.command, error_type=type(exc).__name__, message=str(exc),
             traceback=traceback.format_exc(limit=10))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
