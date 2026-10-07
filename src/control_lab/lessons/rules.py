"""Small allowlisted event rules, deliberately without eval/exec."""

import math
from collections.abc import Mapping, Sequence

EVENTS = frozenset({
    "lesson.viewed", "simulation.started", "simulation.paused", "simulation.reset",
    "scenario.changed", "input.changed",
    "simulation.stepped", "cart.dragged", "signal.selected", "scenario.selected",
    "disturbance.applied", "mode.changed", "code.edited", "code.run", "code.stopped",
    "code.error", "code.saved", "experiment.finished", "experiment.saved",
    "reflection.submitted", "prediction.submitted", "hint.opened", "solution.viewed",
    "step.acknowledged", "comparison.saved", "training.started", "training.completed",
    "model.loaded", "external.verified", "artifact.saved", "answer.checked",
    "signal.analysis.completed", "signal.kick.completed",
    "code.probed", "centering.reached",
    "reward.analysis.completed", "reward.configuration.saved", "robustness.completed", "baseline.saved",
    "robustness.reviewed",
    "sweep.completed", "evaluation.replayed", "comparison.completed", "project.exported",
})


def validate_rule(rule: dict, depth: int = 0) -> None:
    if not isinstance(rule, dict) or depth > 8:
        raise ValueError("课程完成规则格式错误或嵌套过深")
    if "all" in rule or "any" in rule:
        key = "all" if "all" in rule else "any"
        if set(rule) != {key} or not isinstance(rule[key], list) or not 1 <= len(rule[key]) <= 32:
            raise ValueError("all/any 只能包含非空规则列表")
        for child in rule[key]:
            validate_rule(child, depth + 1)
        return
    if set(rule) - {"event", "min_count", "field", "equals", "min", "max"}:
        raise ValueError("规则包含不支持的运算")
    if rule.get("event") not in EVENTS:
        raise ValueError("课程事件不在白名单内")
    count = rule.get("min_count", 1)
    if type(count) is not int or not 1 <= count <= 10000:
        raise ValueError("min_count 必须是正整数")
    if "field" in rule and (not isinstance(rule["field"], str) or not rule["field"]):
        raise ValueError("field 必须是非空名称")
    if any(key in rule for key in ("equals", "min", "max")) and "field" not in rule:
        raise ValueError("数值/相等检查必须指定 field")
    for key in ("min", "max"):
        if key in rule and (type(rule[key]) not in (int, float) or not math.isfinite(rule[key])):
            raise ValueError("数值边界必须有限")
    if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
        raise ValueError("数值范围倒置")


def _match(rule: Mapping, item: Mapping) -> bool:
    if item.get("event") != rule["event"]:
        return False
    data = item.get("payload", {})
    if not isinstance(data, Mapping):
        return False
    name = rule.get("field")
    if name is None:
        return True
    # Reflections use an explicit field/value pair; other events use named data.
    value = data.get("value") if data.get("field") == name else data.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        return False
    if "equals" in rule and value != rule["equals"]:
        return False
    if "min" in rule or "max" in rule:
        if type(value) not in (int, float) or not math.isfinite(value):
            return False
        return rule.get("min", -math.inf) <= value <= rule.get("max", math.inf)
    return True


def evaluate_rule(rule: dict, events: Sequence[Mapping]) -> bool:
    validate_rule(rule)
    if "all" in rule:
        return all(evaluate_rule(child, events) for child in rule["all"])
    if "any" in rule:
        return any(evaluate_rule(child, events) for child in rule["any"])
    return sum(_match(rule, item) for item in events) >= rule.get("min_count", 1)
