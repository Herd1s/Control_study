from pathlib import Path
import ast
import json
import math
import shutil

import pytest

from control_lab.lessons import LessonSession, load_lessons, load_lesson
from control_lab.lessons.rules import evaluate_rule, validate_rule


def test_all_32_lessons_and_resources_are_real():
    lessons = load_lessons()
    assert [item.id for item in lessons] == [f"L{i:02d}" for i in range(1, 33)]
    for lesson in lessons:
        assert len(lesson.steps) >= 6
        assert lesson.reflection and lesson.reference_answer
        assert all(len(step.hints) == 3 and step.instruction for step in lesson.steps)
        if lesson.editor_kind == "none":
            assert not lesson.read_template()
        else:
            assert lesson.template and lesson.solution
            for source in (lesson.read_template(), lesson.read_solution()):
                ast.parse(source)
                namespace = {"__name__": "lesson_test"}
                exec(compile(source, "<lesson>", "exec"), namespace)
                if lesson.editor_kind == "controller":
                    if "reset" in namespace:
                        namespace["reset"]()
                    action = namespace["control"]({"x": .1, "v": .05, "theta": .02,
                                                    "omega": -.01, "target_v": .3, "time_s": 0.0}, .02)
                    assert type(action) in (int, float) and math.isfinite(action)
                else:
                    assert callable(namespace.get("main"))


def test_force_and_velocity_courses_are_explicit():
    assert load_lesson("L11").input_mode == "velocity_mps"
    for i in range(12, 30):
        assert load_lesson(f"L{i:02d}").input_mode == "force_n"
    for i in (17, 18):
        lesson = load_lesson(f"L{i:02d}")
        assert lesson.scenario_id.startswith("cart_velocity")
        assert 'state["target_v"]' in lesson.read_solution()
    for i in (26, 27):
        assert load_lesson(f"L{i:02d}").availability == "external_runtime"
    for i in range(30, 33):
        assert load_lesson(f"L{i:02d}").availability == "external_robot"


def test_whitelist_rules_do_not_execute_strings():
    for invalid in ({"eval": "__import__('os')"}, {"event": "os.system"},
                    {"event": "code.run", "min_count": True}, {"any": []},
                    {"event": "code.run", "field": "value", "min": float("nan")}):
        with pytest.raises(ValueError):
            validate_rule(invalid)
    rule = {"all": [{"event": "experiment.saved", "min_count": 2},
                     {"event": "reflection.submitted", "field": "reflection"}]}
    events = [{"event": "experiment.saved", "payload": {}}, {"event": "experiment.saved", "payload": {}}]
    assert not evaluate_rule(rule, events)
    events.append({"event": "reflection.submitted", "payload": {"field": "reflection", "value": " "}})
    assert not evaluate_rule(rule, events)
    events.append({"event": "reflection.submitted", "payload": {"field": "reflection", "value": "我的发现"}})
    assert evaluate_rule(rule, events)
    numeric = {"event": "answer.checked", "field": "result", "min": 1, "max": 3}
    assert evaluate_rule(numeric, [{"event": "answer.checked", "payload": {"result": 2}}])
    assert not evaluate_rule(numeric, [{"event": "answer.checked", "payload": {"result": True}}])


def test_session_evidence_skip_and_resume():
    session = LessonSession(load_lesson("L01"))
    assert not session.advance()
    assert session.advance(force=True)
    assert session.skipped_step_ids == ["step_01"] and not session.completed_step_ids
    session.go_to(0)
    event = session.step.completion["event"]
    session.emit(event, value="我观察到了反馈")
    assert session.can_advance
    assert session.advance()
    assert not session.skipped_step_ids and session.completed_step_ids == ["step_01"]
    session.hint(2)
    session.emit("hint.opened", level=3)
    assert session.hints_opened[session.step.id] == 3
    assert session.has_attempt
    resumed = LessonSession(session.lesson, session.snapshot())
    assert resumed.step_index == session.step_index
    assert resumed.hints_opened == session.hints_opened
    assert not resumed.can_advance  # old step's event is not reused
    with pytest.raises(ValueError):
        resumed.emit("fake.success")


def copy_resources(tmp_path):
    root = load_lesson("L01").resource_root
    shutil.copytree(root, tmp_path / "lessons", ignore=shutil.ignore_patterns("__pycache__"))
    return tmp_path / "lessons"


@pytest.mark.parametrize("mutation", ["traversal", "cycle", "missing", "unknown_signal", "event"])
def test_loader_rejects_invalid_course(tmp_path, mutation):
    root = copy_resources(tmp_path)
    path = root / "content" / "L01.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "traversal":
        data["template"] = "../outside.py"
    elif mutation == "cycle":
        data["prerequisites"] = ["L02"]
    elif mutation == "missing":
        data["prerequisites"] = ["L99"]
    elif mutation == "unknown_signal":
        data["visible_signals"] = ["password"]
    else:
        data["steps"][0]["completion"] = {"event": "python.exec"}
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_lessons(root)


def test_memory_reset_and_antiwindup_teacher_answers():
    timer = {}
    exec(load_lesson("L09").read_solution(), timer)
    def run():
        timer["reset"]()
        return [timer["control"]({}, .02) for _ in range(50)]
    assert run() == run() == [1.0] * 25 + [0.0] * 25
    pi = {}
    exec(load_lesson("L18").read_solution(), pi)
    pi["reset"]()
    for _ in range(200):
        pi["control"]({"v": 0, "target_v": 4}, .02)
    assert pi["integral"] == 0.0  # cannot wind up further into positive saturation
    pi["integral"] = 2.0
    pi["control"]({"v": .5, "target_v": .3}, .02)
    assert pi["integral"] < 2.0  # reverse error is allowed to release memory


def test_single_step_course_does_not_accept_continuous_running():
    lesson = load_lesson("L08")
    rule = lesson.steps[2].completion
    assert not evaluate_rule(rule, [{"event": "simulation.stepped", "payload": {"single": False}}]*50)
    assert not evaluate_rule(rule, [{"event": "simulation.stepped", "payload": {"single": True}}]*4)
    assert evaluate_rule(rule, [{"event": "simulation.stepped", "payload": {"single": True}}]*5)
