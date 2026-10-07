"""Typed course resources. No imports from Qt or a training runtime."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LessonStep:
    id: str
    title: str
    instruction: str
    hints: tuple[str, ...]
    completion: dict
    activity: str = "observe"
    evidence: str = ""
    visible_signals: tuple[str, ...] | None = None
    show_chart: bool | None = None


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    title: str
    summary: str
    duration_minutes: int
    prerequisites: tuple[str, ...]
    scenario_id: str
    scenario_options: tuple[str, ...]
    input_mode: str
    visible_signals: tuple[str, ...]
    steps: tuple[LessonStep, ...]
    template: str | None
    solution: str | None
    requires: tuple[str, ...]
    availability: str
    editor_kind: str
    reflection: str
    reference_answer: str
    content_version: int = 1
    notes: str = ""
    objectives: tuple[str, ...] = ()
    resource_root: Path = field(default_factory=lambda: Path(__file__).parent, repr=False, compare=False)

    @property
    def id(self) -> str:
        return self.lesson_id

    def _read(self, relative: str | None) -> str:
        if not relative:
            return ""
        root = self.resource_root.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("课程资源不能越出资源目录")
        return target.read_text(encoding="utf-8")

    def read_template(self) -> str:
        return self._read(self.template)

    def read_solution(self) -> str:
        return self._read(self.solution)
