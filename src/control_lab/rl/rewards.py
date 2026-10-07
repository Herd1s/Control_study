"""Versioned, inspectable reward components evaluated on post-action true state."""
import math
import json
from pathlib import Path
import re

REWARD_SPECS = {
    "survival-v1": {"version": 1, "alive": 1.0, "angle": 0.0, "position": 0.0, "effort": 0.0},
    "balanced-v1": {"version": 1, "alive": 1.0, "angle": 0.6, "position": 0.2, "effort": 0.02},
}


def normalize_reward_config(config):
    """Canonical portable declaration, shared by offline scoring and training."""
    if not isinstance(config, dict) or set(config) != {
            "schema_version", "reward_id", "version", "alive", "angle", "position", "effort"}:
        raise ValueError("奖励配置需要schema_version/reward_id/version/alive/angle/position/effort")
    if config["schema_version"] != 1 or type(config["schema_version"]) is not int:
        raise ValueError("不支持的奖励配置格式")
    name = config["reward_id"]
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{2,63}", name):
        raise ValueError("奖励版本名使用3–64个小写字母、数字、点、横线或下划线")
    if type(config["version"]) is not int or config["version"] < 1:
        raise ValueError("奖励版本号必须是正整数")
    normalized = dict(config)
    for key in ("alive", "angle", "position", "effort"):
        value = config[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1000:
            raise ValueError(f"奖励权重{key}必须为0–1000之间的有限数")
        normalized[key] = float(value)
    specification = {key: normalized[key] for key in ("version", "alive", "angle", "position", "effort")}
    if name in REWARD_SPECS and specification != REWARD_SPECS[name]:
        raise ValueError("内置奖励版本不可改写；请给新权重取一个新的版本名")
    return normalized


def resolve_reward_config(reward_id="survival-v1", reward_config=None):
    if reward_config is None:
        if reward_id not in REWARD_SPECS:
            raise ValueError(f"Unknown reward version: {reward_id}")
        return {"schema_version": 1, "reward_id": reward_id, **REWARD_SPECS[reward_id]}
    config = normalize_reward_config(reward_config)
    if config["reward_id"] != reward_id:
        raise ValueError("奖励配置中的版本名与请求不一致")
    return config


def load_reward_config(path):
    path = Path(path)
    if path.stat().st_size > 100_000:
        raise ValueError("奖励配置文件过大")
    return normalize_reward_config(json.loads(path.read_text(encoding="utf-8-sig")))


def reward_config_from_contract(contract):
    return normalize_reward_config({"schema_version": 1, "reward_id": contract["reward_id"],
                                    **contract["reward_definition"]})


def components_for_config(cfg, state, force_n):
    if hasattr(state, "as_dict"):
        state = state.as_dict()
    if not isinstance(state, dict):
        state = dict(zip(("x", "v", "theta", "omega"), state))
    x, theta, force = float(state["x"]), float(state["theta"]), float(force_n)
    if not all(math.isfinite(v) for v in (x, theta, force)):
        raise ValueError("Reward inputs must be finite")
    return {"survival": cfg["alive"],
            "angle": -cfg["angle"] * (theta / math.radians(12)) ** 2,
            "position": -cfg["position"] * (x / 2.4) ** 2,
            "effort": -cfg["effort"] * (force / 10.0) ** 2}


def reward_components(reward_id: str, state, force_n: float, *, reward_config=None) -> dict[str, float]:
    return components_for_config(resolve_reward_config(reward_id, reward_config), state, force_n)
