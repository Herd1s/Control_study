"""Deterministic, zero-input physics clips for direction and trend comparisons."""

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path

from control_lab.core.scenario import get_episode_spec
from control_lab.core.session import EpisodeSession
from control_lab.core.types import State


def make_comparison(lesson_id):
    if lesson_id == "L03":
        initial = (State(v=-.4), State(v=.4))
        captions = ("从中心向左", "从中心向右")
    elif lesson_id in {"L04", "L15"}:
        initial = (State(theta=.05, omega=.15), State(theta=.05, omega=-.15))
        captions = ("向右倾，继续向右转", "向右倾，正在回正")
    else:
        raise ValueError("本课没有预置对照片段")
    clips = []
    for index, state in enumerate(initial):
        base = get_episode_spec("upright")
        spec = replace(base, max_steps=50, protocol_id="foundation-clip-v1",
            scenario=replace(base.scenario, scenario_id=f"{lesson_id}-clip-{index}", initial_state=state))
        session = EpisodeSession(spec)
        try:
            frames = [{"time_s": 0., "state": list(session.true_state), "force_n": 0.}]
            rows = []
            for _ in range(spec.max_steps):
                result = session.step(0.)
                rows.append({key: value for key, value in asdict(result).items() if key != "episode_id"})
                frames.append({"time_s": result.simulation_time_s, "state": list(result.true_state), "force_n": 0.})
                if result.terminated or result.truncated:
                    break
        finally:
            session.close()
        clips.append({"caption": captions[index], "spec": asdict(spec), "frames": frames, "trajectory": rows})
    return {"schema_version": 1, "kind": "foundation_comparison", "lesson_id": lesson_id,
            "scored_benchmark": False, "source": "EpisodeSession zero-force integration", "clips": clips}


def save_comparison(root, lesson_id):
    data = make_comparison(lesson_id)
    content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    path = Path(root) / "examples" / lesson_id / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != content:
            raise ValueError("预置片段记录被修改，未覆盖原文件")
    else:
        path.write_bytes(content)
    return data, path
