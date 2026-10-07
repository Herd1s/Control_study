"""Command line entry points, with simulation imports deferred until needed."""

from __future__ import annotations

import argparse
import importlib
from importlib.resources import files
from pathlib import Path
import platform
import sys
import json
from datetime import datetime

from control_lab import __version__
from control_lab.paths import default_controller_file, user_data_dir


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return result


def nonnegative_int(value: str) -> int:
    result = int(value)
    if result < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return result


def doctor() -> int:
    print(f"ControlLab {__version__}")
    print(f"Python: {platform.python_version()} ({sys.executable})")
    print(f"Frozen application: {bool(getattr(sys, 'frozen', False))}")
    print(f"Environment prefix: {sys.prefix}")
    failures = []
    for name in ("numpy", "gymnasium", "pygame", "PySide6"):
        try:
            module = importlib.import_module(name)
            version = getattr(module, "__version__", "unknown")
            print(f"[OK] {name} {version}: {getattr(module, '__file__', '(bundled)')}")
        except Exception as exc:
            failures.append(name)
            print(f"[FAIL] {name}: {exc}")
    if not failures:
        try:
            from control_lab.envs.cartpole import make_env

            env = make_env(max_episode_steps=2)
            try:
                observation, _ = env.reset(seed=42)
                env.step([0.0])
                if observation.shape != (4,) or env.action_space.shape != (1,):
                    raise RuntimeError("Unexpected observation/action shape")
            finally:
                env.close()
            print("[OK] Independent CPU CartPole reset/step")
        except Exception as exc:
            failures.append("cartpole")
            print(f"[FAIL] CartPole: {exc}")
    print(f"Student controller: {default_controller_file()}")
    print(f"Default data directory: {user_data_dir()}")
    return 1 if failures else 0


def init_workspace(destination: Path) -> int:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / "my_controller.py"
    if target.exists():
        print(f"Kept existing controller (not overwritten): {target}")
    else:
        source = files("control_lab.templates").joinpath("my_controller.py").read_bytes()
        with target.open("xb") as stream:
            stream.write(source)
        print(f"Created student controller: {target}")
    executable = f'"{sys.executable}"' if getattr(sys, "frozen", False) else "control-lab"
    print(f'Run: {executable} run --controller student --controller-file "{target}" --render')
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ControlLab: learn control with continuous-force CartPole")
    parser.add_argument("--version", action="version", version=f"ControlLab {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    run_parser = commands.add_parser("run", help="run and record a control experiment")
    run_parser.add_argument("--controller", choices=["student", "reference", "reference-angle", "zero"], default="student")
    run_parser.add_argument("--controller-file", type=Path, help="student Controller Python file; only used with --controller student")
    run_parser.add_argument("--render", action="store_true", help="open the animation window; close it or press Escape to stop")
    run_parser.add_argument("--episodes", type=positive_int, default=3)
    run_parser.add_argument("--seed", type=nonnegative_int, default=42)
    run_parser.add_argument("--max-steps", type=positive_int, default=500)
    run_parser.add_argument("--output-dir", type=Path, help="directory for this run; existing experiment files are never overwritten")
    commands.add_parser("doctor", help="check independent Python dependencies and simulate one step")
    initialize = commands.add_parser("init-workspace", help="copy editable student code into a folder without overwriting")
    initialize.add_argument("path", type=Path)
    lessons = commands.add_parser("lesson", help="list or open a guided lesson")
    lessons.add_argument("--id", default="L01")
    lessons.add_argument("--list", action="store_true")
    evaluate = commands.add_parser("evaluate", help="evaluate all fixed cases of one benchmark split")
    evaluate.add_argument("--protocol", default="balance-v1")
    evaluate.add_argument("--controller", choices=["reference", "reference-angle", "zero", "student"], default="reference")
    evaluate.add_argument("--controller-file", type=Path)
    evaluate.add_argument("--model-dir", type=Path)
    evaluate.add_argument("--split", choices=["practice", "validation", "held_out"], default="validation")
    evaluate.add_argument("--frozen-controller-sha256")
    evaluate.add_argument("--output-dir", type=Path)
    compare = commands.add_parser("compare", help="compare complete reports with identical benchmark conditions")
    compare.add_argument("reports", nargs="+", type=Path)
    compare.add_argument("--output", type=Path)
    train = commands.add_parser("train", help="train in the separate RL Python environment")
    train.add_argument("--output-dir", type=Path, required=True)
    train.add_argument("--steps", type=positive_int, default=25600)
    train.add_argument("--seed", type=nonnegative_int, default=0)
    train.add_argument("--reward", choices=["survival-v1", "balanced-v1"], default="survival-v1")
    return parser


def main(argv: list[str] | None = None) -> int:
    # QProcess and release logs use UTF-8 even when a Windows console defaults
    # to a legacy code page. The GUI executable may have no stdout/stderr.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "gui":
        from control_lab.desktop.app import main as desktop_main
        return desktop_main(argv[1:] if argv else [])
    parser = make_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor()
        if args.command == "init-workspace":
            return init_workspace(args.path)
        if args.command == "lesson":
            from control_lab.lessons import load_lessons
            if args.list:
                for lesson in load_lessons():
                    print(f"{lesson.id}  {lesson.title}  [{lesson.availability}]")
                return 0
            from control_lab.desktop.app import main as desktop_main
            return desktop_main(["--lesson", args.id])
        if args.command == "train":
            from control_lab.rl.train import TrainConfig, train
            train(TrainConfig(args.output_dir, total_timesteps=args.steps, seed=args.seed, reward_id=args.reward))
            return 0
        if args.command == "compare":
            from control_lab.evaluation import compare_reports
            report = compare_reports(json.loads(path.read_text(encoding="utf-8")) for path in args.reports)
            body = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x", encoding="utf-8") as stream:
                    stream.write(body)
            else:
                print(body)
            return 0
        if args.command == "evaluate":
            output = args.output_dir or user_data_dir() / "evaluations" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            if args.model_dir:
                from control_lab.rl.evaluate import evaluate_model
                report = evaluate_model(args.model_dir, split=args.split, output_dir=output,
                                        frozen_controller_sha256=args.frozen_controller_sha256)
            else:
                from control_lab.evaluation import evaluate, load_protocol
                from control_lab.controllers import ZeroController
                from control_lab.controllers.reference_pid import Controller as Reference
                from control_lab.inputs.adapters import controller_from_source
                if args.controller == "student":
                    path = (args.controller_file or default_controller_file()).resolve()
                    source = path.read_bytes()
                    factory = lambda: controller_from_source(source, path)
                elif args.controller == "zero":
                    factory = ZeroController
                else:
                    if args.controller_file:
                        parser.error("--controller-file requires --controller student")
                    factory = lambda: Reference(center_cart=args.controller == "reference")
                print(f"Evaluating {args.controller}: {args.protocol}/{args.split}", flush=True)
                report = evaluate(factory, load_protocol(args.protocol, split=args.split), output_dir=output,
                                  controller_name=args.controller, allow_held_out=bool(args.frozen_controller_sha256),
                                  expected_controller_sha256=args.frozen_controller_sha256,
                                  progress_callback=lambda done, total, episode: print(f"{done}/{total} {episode['case_id']}: {episode['episode_steps']} steps", flush=True))
            print(json.dumps({"report": str(output / "report.json"), **report["aggregate"]}, ensure_ascii=False), flush=True)
            return 1 if report["aggregate"]["controller_errors"] else 0
        if args.controller_file is not None and args.controller != "student":
            parser.error("--controller-file requires --controller student")
        from control_lab.runner import RunConfig, run_experiment

        report = run_experiment(RunConfig(
            controller=args.controller,
            controller_file=args.controller_file,
            render=args.render,
            episodes=args.episodes,
            seed=args.seed,
            max_steps=args.max_steps,
            output_dir=args.output_dir,
        ))
        return 1 if report["status"] == "error" else 130 if report["status"] == "interrupted" else 0
    except (OSError, ValueError, ImportError) as exc:
        print(f"ControlLab: {exc}", file=sys.stderr)
        return 1
