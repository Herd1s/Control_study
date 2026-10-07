"""Run an experiment while preserving trajectories, controller code and status."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback

import numpy as np

from control_lab import __version__
from control_lab.controllers import ZeroController
from control_lab.controllers.reference_pid import Controller as ReferenceController
from control_lab.envs.cartpole import CONTINUOUS_ENV_ID, make_env
from control_lab.paths import default_controller_file, user_data_dir


@dataclass
class RunConfig:
    controller: str = "student"
    controller_file: Path | None = None
    render: bool = False
    episodes: int = 3
    seed: int = 42
    max_steps: int = 500
    output_dir: Path | None = None


def _load_student(source_path: Path, source: bytes):
    """Execute exactly the source saved in the experiment snapshot."""
    from control_lab.inputs.adapters import controller_from_source
    return controller_from_source(source, source_path)


def _window_close_requested() -> bool:
    import pygame

    if not pygame.display.get_init() or pygame.display.get_surface() is None:
        return True
    return any(
        event.type in (pygame.QUIT, pygame.WINDOWCLOSE)
        or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE)
        for event in pygame.event.get()
    )


def _finish_episode(current: dict, angles: list, positions: list, status: str) -> dict:
    result = dict(current)
    result.update(
        status=status,
        complete=status in ("terminated", "time_limit"),
        rms_theta_rad=float(np.sqrt(np.mean(np.square(angles)))) if angles else None,
        max_abs_x_m=float(np.max(np.abs(positions))) if positions else None,
        final_x_m=positions[-1] if positions else None,
    )
    return result


def run_experiment(config: RunConfig) -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = (
        config.output_dir
        if config.output_dir is not None
        else user_data_dir() / "runs" / f"{stamp}_{config.controller}"
    ).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    for filename in ("trajectory.csv", "report.json", "controller_snapshot.py", "error.txt"):
        if (output / filename).exists():
            raise FileExistsError(f"Refusing to overwrite experiment data: {output / filename}")

    created_at = datetime.now(timezone.utc).isoformat()
    status = "completed"
    error = None
    env = None
    controller = None
    current = None
    summaries: list[dict] = []
    angles: list[float] = []
    positions: list[float] = []
    source_path = None
    snapshot_hash = None
    dt = None
    fields = [
        "episode", "seed", "step", "time_s", "x_m", "x_dot_m_s", "theta_rad",
        "theta_dot_rad_s", "commanded_force", "applied_force", "reward", "terminated", "truncated",
    ]
    print(f"Results: {output}")
    try:
        with (output / "trajectory.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            if config.controller == "student":
                source_path = (config.controller_file or default_controller_file()).expanduser().resolve()
                if not source_path.is_file():
                    executable = f'"{sys.executable}"' if getattr(sys, "frozen", False) else "control-lab"
                    raise FileNotFoundError(
                        f"Student controller not found: {source_path}\n"
                        f'Create a workspace with: {executable} init-workspace "{source_path.parent}"'
                    )
                source = source_path.read_bytes()
                (output / "controller_snapshot.py").write_bytes(source)
                snapshot_hash = hashlib.sha256(source).hexdigest()
                print(f"Student controller: {source_path}")
                controller = _load_student(source_path, source)
            elif config.controller in ("reference", "reference-angle"):
                from control_lab.controllers import reference_pid

                source_path = Path(reference_pid.__file__).resolve()
                # Source exists in editable installs, wheels and the packaged source resource.
                source = source_path.read_bytes()
                (output / "controller_snapshot.py").write_bytes(source)
                snapshot_hash = hashlib.sha256(source).hexdigest()
                controller = ReferenceController(center_cart=config.controller == "reference")
            elif config.controller == "zero":
                controller = ZeroController()
            else:
                raise ValueError(f"Unknown controller: {config.controller}")

            env = make_env("human" if config.render else None, config.max_steps)
            dt = env.dt
            print(f"{CONTINUOUS_ENV_ID}: force [-10, 10] N, dt={dt} s, controller={config.controller}")
            for episode in range(config.episodes):
                seed = config.seed + episode
                current = dict(episode=episode, seed=seed, steps=0, **{"return": 0.0}, terminated=False, truncated=False)
                angles, positions = [], []
                observation, _ = env.reset(seed=seed)
                angles.append(float(observation[2]))
                positions.append(float(observation[0]))
                controller.reset()
                for step in range(config.max_steps):
                    if config.render and _window_close_requested():
                        status = "window_closed"
                        break
                    force = float(controller.act(observation.copy(), dt))
                    previous = observation
                    observation, reward, terminated, truncated, info = env.step(
                        np.array([force], dtype=np.float64)
                    )
                    current.update(steps=step + 1, terminated=bool(terminated), truncated=bool(truncated))
                    current["return"] += float(reward)
                    angles.append(float(observation[2]))
                    positions.append(float(observation[0]))
                    # States/timestamps describe the instant before applying this row's action.
                    writer.writerow(dict(zip(fields, [
                        episode, seed, step, step * dt, *map(float, previous),
                        info["commanded_force"], info["applied_force"], float(reward),
                        bool(terminated), bool(truncated),
                    ])))
                    if terminated or truncated:
                        break
                stream.flush()
                if status == "window_closed":
                    break
                summary = _finish_episode(
                    current, angles, positions,
                    "terminated" if current["terminated"] else "time_limit",
                )
                summaries.append(summary)
                current = None
                print(
                    f"Episode {episode + 1}: {summary['steps']} steps, "
                    f"return={summary['return']:.0f}, max |x|={summary['max_abs_x_m']:.3f} m, "
                    f"{summary['status']}"
                )
    except KeyboardInterrupt:
        status = "interrupted"
        print("Interrupted; completed steps and the partial episode are saved.")
    except (Exception, SystemExit) as exc:
        status = "error"
        error = {"type": type(exc).__name__, "message": str(exc)}
        (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        print(f"Experiment failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        if env is not None:
            try:
                env.close()
            except Exception as exc:
                if error is None:
                    status = "error"
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    (output / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        if current is not None:
            summaries.append(_finish_episode(current, angles, positions, status))
        completed = [item for item in summaries if item["complete"]]
        report = {
            "schema_version": 1,
            "control_lab_version": __version__,
            "created_at_utc": created_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "error": error,
            "environment": CONTINUOUS_ENV_ID,
            "controller": config.controller,
            "controller_file": str(source_path) if source_path else None,
            "controller_snapshot_sha256": snapshot_hash,
            "output_dir": str(output),
            "dt": dt,
            "seed": config.seed,
            "max_steps": config.max_steps,
            "requested_episodes": config.episodes,
            "completed_episodes": len(completed),
            "episodes": summaries,
            "mean_return": float(np.mean([item["return"] for item in completed])) if completed else None,
            "trajectory_state_timing": "before_action; reward and terminal flags are after_action",
        }
        if isinstance(controller, ReferenceController):
            report["reference_gains"] = vars(controller.gains)
            report["center_cart"] = controller.center_cart
        (output / "report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8",
        )
    print(f"Status: {status}")
    return report
