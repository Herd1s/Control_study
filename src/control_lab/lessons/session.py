"""A learner can always skip a step; skipping never counts as completion."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib

from .rules import EVENTS, evaluate_rule
from .schema import Lesson


class LessonSession:
    def __init__(self, lesson: Lesson, progress: dict | None = None):
        self.lesson = lesson
        saved = progress or {}
        known = {step.id for step in lesson.steps}
        self.completed_step_ids = [s for s in saved.get("completed_step_ids", []) if s in known]
        self.skipped_step_ids = [s for s in saved.get("skipped_step_ids", []) if s in known]
        self.step_index = min(max(int(saved.get("step_index", 0)), 0), len(lesson.steps))
        self.events = list(saved.get("events", []))[-500:]
        self.hints_opened = dict(saved.get("hints_opened", {}))
        self.reflections = dict(saved.get("reflection", {}))
        self.responses = deepcopy(saved.get("responses", {}))
        self.response_drafts = dict(saved.get("response_drafts", {}))
        self.response_revisions = deepcopy(saved.get("response_revisions", {}))
        self.step_events = deepcopy(saved.get("step_events", {}))
        self.step_signatures = {s.id: hashlib.sha256(json.dumps(
            {"instruction": s.instruction, "completion": s.completion},
            ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest() for s in lesson.steps}
        self.prior_versions = deepcopy(saved.get("prior_versions", []))
        self.updated_steps = []
        self.attempt_refs = list(saved.get("attempt_refs", []))
        self.has_attempt = bool(saved.get("has_attempt", False))
        self.solution_views = int(saved.get("solution_views", 0))
        if saved.get("content_version", lesson.content_version) != lesson.content_version:
            self.updated_steps = [s.id for s in lesson.steps
                if saved.get("step_signatures", {}).get(s.id) != self.step_signatures[s.id]]
            if saved:
                self.prior_versions.append({key: deepcopy(value) for key, value in saved.items()
                                            if key != "prior_versions"})
                self.prior_versions = self.prior_versions[-10:]
            self.completed_step_ids = [s for s in self.completed_step_ids if s not in self.updated_steps]
            self.step_index = next((i for i, s in enumerate(lesson.steps) if s.id not in self.completed_step_ids), len(lesson.steps))
            self.events = []
            self.step_events = {}

    @property
    def step(self):
        return None if self.finished else self.lesson.steps[self.step_index]

    @property
    def finished(self) -> bool:
        return self.step_index >= len(self.lesson.steps)

    @property
    def completed(self) -> bool:
        return {s.id for s in self.lesson.steps} <= set(self.completed_step_ids)

    @property
    def can_advance(self) -> bool:
        return bool(self.step and (self.step.id in self.completed_step_ids or
                                  evaluate_rule(self.step.completion, self.events)))

    def save_response_draft(self, text: str) -> None:
        if self.step is not None:
            self.response_drafts[self.step.id] = str(text)

    def response_text(self) -> str:
        if self.step is None:
            return ""
        return self.response_drafts.get(self.step.id,
            self.responses.get(self.step.id, {}).get("value", ""))

    def emit(self, event: str, **payload) -> bool:
        if event not in EVENTS:
            raise ValueError(f"未知课程事件：{event}")
        json.dumps(payload, allow_nan=False)
        item = {"event": event, "payload": deepcopy(payload)}
        self.events.append(item)
        self.events = self.events[-500:]
        if self.step is not None:
            self.step_events[self.step.id] = deepcopy(self.events)
        if event in {"simulation.started", "cart.dragged", "code.run", "prediction.submitted",
                     "step.acknowledged", "experiment.finished", "code.probed", "answer.checked"}:
            self.has_attempt = True
        if event == "hint.opened" and self.step is not None:
            level = payload.get("level", 1)
            if type(level) is int and 1 <= level <= 3:
                self.hints_opened[self.step.id] = max(level, self.hints_opened.get(self.step.id, 0))
        if event == "solution.viewed":
            self.solution_views += 1
        if event == "reflection.submitted":
            self.reflections[str(payload.get("field", "reflection"))] = str(payload.get("value", ""))
        if event in {"reflection.submitted", "prediction.submitted"} and self.step is not None:
            previous = self.responses.get(self.step.id)
            if previous and previous.get("value") != payload.get("value"):
                revisions = self.response_revisions.setdefault(self.step.id, [])
                revisions.append(deepcopy(previous))
                self.response_revisions[self.step.id] = revisions[-20:]
            self.responses[self.step.id] = {"event": event, **deepcopy(payload)}
            self.responses[self.step.id]["submitted_at"] = datetime.now(timezone.utc).isoformat()
            self.save_response_draft(str(payload.get("value", "")))
        if event == "experiment.saved" and payload.get("path"):
            self.attempt_refs.append(str(payload["path"]))
        return self.can_advance

    def advance(self, force: bool = False) -> bool:
        if self.finished or (not force and not self.can_advance):
            return False
        ident = self.step.id
        target = self.skipped_step_ids if force else self.completed_step_ids
        if force and ident in self.completed_step_ids:
            target = self.completed_step_ids
        if ident not in target:
            target.append(ident)
        if not force and ident in self.skipped_step_ids:
            self.skipped_step_ids.remove(ident)
        self.step_index += 1
        self.events = deepcopy(self.step_events.get(self.step.id, [])) if self.step else []
        return True

    def go_to(self, index: int) -> None:
        if not 0 <= index < len(self.lesson.steps):
            raise ValueError("步骤超出课程范围")
        if self.step is not None:
            self.step_events[self.step.id] = deepcopy(self.events)
        self.step_index = index
        self.events = deepcopy(self.step_events.get(self.step.id, []))

    def hint(self, level: int) -> str:
        if self.step is None or level not in (1, 2, 3):
            raise ValueError("提示层级应为1、2、3")
        self.hints_opened[self.step.id] = max(level, self.hints_opened.get(self.step.id, 0))
        self.emit("hint.opened", level=level)
        return self.step.hints[level - 1]

    def snapshot(self) -> dict:
        return deepcopy({"lesson_id": self.lesson.id, "content_version": self.lesson.content_version,
            "step_index": self.step_index, "completed_step_ids": self.completed_step_ids,
            "skipped_step_ids": self.skipped_step_ids, "events": self.events,
            "hints_opened": self.hints_opened, "reflection": self.reflections,
            "responses": self.responses, "response_drafts": self.response_drafts,
            "response_revisions": self.response_revisions, "prior_versions": self.prior_versions,
            "step_signatures": self.step_signatures,
            "step_events": self.step_events,
            "has_attempt": self.has_attempt, "solution_views": self.solution_views,
            "attempt_refs": self.attempt_refs, "updated_at": datetime.now(timezone.utc).isoformat()})
