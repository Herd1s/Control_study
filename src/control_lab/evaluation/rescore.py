"""Recompute reward on recorded trajectories without claiming a new rollout."""
import csv
from dataclasses import asdict, dataclass
import math
from pathlib import Path

from control_lab.controllers._common import finite_number
from .protocol import canonical_hash


@dataclass(frozen=True)
class RewardConfig:
    reward_id: str = "quadratic-balance-v1"
    alive_per_step: float = 1.0
    theta_weight: float = 1.0
    position_weight: float = 0.1
    force_weight: float = 0.001
    termination_penalty: float = 0.0

    def __post_init__(self):
        if not isinstance(self.reward_id, str) or not self.reward_id.strip():
            raise ValueError("Reward ID must be nonempty")
        for name, value in asdict(self).items():
            if name != "reward_id":
                finite_number(value, name)
        if min(self.theta_weight, self.position_weight, self.force_weight, self.termination_penalty) < 0:
            raise ValueError("Quadratic penalty weights must be nonnegative")


def rescore_trajectory(rows, config=None):
    config = config or RewardConfig()
    if isinstance(rows, (str, Path)):
        with Path(rows).open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
    else:
        rows = list(rows)
    scores = []
    for index, row in enumerate(rows):
        # The evaluation recorder uses post-action true state, never noisy measurement.
        try:
            theta = finite_number(float(row["true_theta_rad"]), "true theta")
            x = finite_number(float(row["true_x_m"]), "true x")
            force = finite_number(float(row["actuator_force_n"]), "actuator force")
        except KeyError as exc:
            raise ValueError("Rescoring requires the evaluation true-post-step trajectory schema") from exc
        terminal = row.get("terminated", False)
        if isinstance(terminal, str):
            if terminal.lower() not in ("true", "false", "1", "0"):
                raise ValueError("Invalid termination flag")
            terminal = terminal.lower() in ("true", "1")
        parts = dict(alive=config.alive_per_step,
                     angle_penalty=-config.theta_weight * theta * theta,
                     position_penalty=-config.position_weight * x * x,
                     force_penalty=-config.force_weight * force * force,
                     termination_penalty=-config.termination_penalty if terminal else 0.0)
        for name, value in parts.items():
            finite_number(value, name)
        scores.append(dict(step_id=int(row.get("step_id", index)), reward=math.fsum(parts.values()), components=parts))
    return dict(schema_version=1, reward_config=asdict(config), reward_hash=canonical_hash(asdict(config)),
                steps=len(scores), rescored_return=math.fsum(item["reward"] for item in scores),
                rewards=scores, rollout_unchanged=True,
                interpretation="Same recorded states/actions; this is not a policy trained with the new reward.")
