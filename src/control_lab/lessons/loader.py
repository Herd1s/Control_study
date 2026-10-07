"""Validate the whole course before exposing it to the GUI."""

import json
import re
from pathlib import Path

from .rules import validate_rule
from .schema import Lesson, LessonStep

SIGNALS = frozenset({"x", "v", "theta", "omega", "force", "requested_force", "time",
                     "target_v", "integral", "p", "d", "i", "reward", "true_theta"})
MODES = frozenset({"manual_position_assist", "force_n", "velocity_mps", "none"})


def _strings(value, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{name} 必须为文字列表")
    return tuple(value)


def _resource(root: Path, value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("资源使用相对路径和正斜杠")
    relative = Path(value)
    candidate = (root / relative).resolve()
    if relative.is_absolute() or not candidate.is_relative_to(root) or candidate.suffix != ".py":
        raise ValueError("资源路径越界或类型不受支持")
    if not candidate.is_file():
        raise ValueError(f"课程资源不存在：{value}")
    return value


def load_lessons(resource_root: str | Path | None = None) -> list[Lesson]:
    root = Path(resource_root or Path(__file__).parent).resolve()
    lessons = []
    for path in sorted((root / "content").glob("L*.json")):
        if not path.resolve().is_relative_to(root):
            raise ValueError("课程清单路径越界")
        data = json.loads(path.read_text(encoding="utf-8"))
        ident = data.get("lesson_id", "")
        if data.get("schema_version") != 1 or not re.fullmatch(r"L\d{2}", ident) or path.stem != ident:
            raise ValueError(f"课程版本/ID错误：{path.name}")
        if not isinstance(data.get("title"), str) or not data["title"].strip():
            raise ValueError("课程标题为空")
        version = data.get("content_version", 1)
        if type(version) is not int or version < 1:
            raise ValueError("课程内容版本错误")
        duration = data.get("duration_minutes")
        if type(duration) is not int or not 1 <= duration <= 240:
            raise ValueError("课时无效")
        signals = _strings(data.get("visible_signals", []), "visible_signals")
        if set(signals) - SIGNALS or data.get("input_mode") not in MODES:
            raise ValueError("未知显示字段或输入模式")
        if data.get("availability") not in {"built_in", "external_runtime", "external_robot"}:
            raise ValueError("未知能力状态")
        if data.get("editor_kind") not in {"none", "controller", "script", "report"}:
            raise ValueError("未知编辑器类型")
        steps = []
        for item in data.get("steps", []):
            if not isinstance(item, dict) or not re.fullmatch(r"[a-z][a-z0-9_]*", item.get("id", "")):
                raise ValueError("课内步骤ID错误")
            hints = _strings(item.get("hints"), "hints")
            if len(hints) != 3 or not str(item.get("instruction", "")).strip():
                raise ValueError("每步需要操作说明和三层提示")
            validate_rule(item.get("completion"))
            step_signals = _strings(item["visible_signals"], "step.visible_signals") if "visible_signals" in item else None
            if step_signals is not None and set(step_signals) - set(signals):
                raise ValueError("步骤显示字段必须来自本课信号")
            show_chart = item.get("show_chart")
            if show_chart is not None and type(show_chart) is not bool:
                raise ValueError("show_chart 必须是布尔值")
            steps.append(LessonStep(item["id"], item.get("title", "动手试试"), item["instruction"], hints,
                                    item["completion"], item.get("activity", "observe"), item.get("evidence", ""),
                                    step_signals, show_chart))
        if not steps or len({s.id for s in steps}) != len(steps):
            raise ValueError("课内步骤缺失或ID重复")
        lessons.append(Lesson(ident, data["title"], data.get("summary", ""), duration,
            _strings(data.get("prerequisites", []), "prerequisites"), data.get("scenario_id", "upright"),
            _strings(data.get("scenario_options", []), "scenario_options"), data["input_mode"], signals,
            tuple(steps), _resource(root, data.get("template")), _resource(root, data.get("solution")),
            _strings(data.get("requires", []), "requires"), data["availability"], data["editor_kind"],
            data.get("reflection", ""), data.get("reference_answer", ""), version,
            data.get("notes", ""), _strings(data.get("objectives", []), "objectives"), root))
    if not lessons or len({l.id for l in lessons}) != len(lessons):
        raise ValueError("课程列表为空或ID重复")
    by_id = {lesson.id: lesson for lesson in lessons}
    visiting, visited = set(), set()
    def visit(ident):
        if ident in visiting:
            raise ValueError(f"课程前置存在循环：{ident}")
        if ident not in by_id:
            raise ValueError(f"前置课程不存在：{ident}")
        if ident in visited:
            return
        visiting.add(ident)
        for prerequisite in by_id[ident].prerequisites:
            visit(prerequisite)
        visiting.remove(ident)
        visited.add(ident)
    for ident in by_id:
        visit(ident)
    return lessons


def load_lesson(lesson_id: str, resource_root: str | Path | None = None) -> Lesson:
    for lesson in load_lessons(resource_root):
        if lesson.id == lesson_id:
            return lesson
    raise KeyError(lesson_id)
