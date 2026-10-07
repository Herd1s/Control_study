"""A single, progressive lesson guide; content comes from validated resources."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QPlainTextEdit, QPushButton, QHBoxLayout, QVBoxLayout


def text_label(text="", name="guideText"):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(True)
    return widget


class LessonPanel(QFrame):
    eventRaised = Signal(str, dict)
    advanceRequested = Signal(bool)
    solutionRequested = Signal()
    stepRequested = Signal(int)
    draftChanged = Signal(str)
    notesRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guide")
        self.session = None
        self._shown_step = None
        self._hint_level = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        navigation = QHBoxLayout()
        self.previous_button = QPushButton("← 上一步")
        self.previous_button.clicked.connect(lambda: self.stepRequested.emit(
            max(0, self.session.step_index - 1)))
        self.step_combo = QComboBox()
        self.step_combo.setAccessibleName("返回课程步骤")
        self.step_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.step_combo.setMinimumContentsLength(8)
        self.step_combo.activated.connect(lambda index: self.stepRequested.emit(index))
        navigation.addWidget(self.previous_button)
        navigation.addWidget(self.step_combo, 1)
        layout.addLayout(navigation)
        self.step_title = text_label(name="guideTitle")
        self.instruction = text_label()
        layout.addWidget(self.step_title)
        layout.addWidget(self.instruction)
        row = QHBoxLayout()
        self.hint_button = QPushButton("给我一点提示")
        self.hint_button.clicked.connect(self.show_hint)
        self.solution_button = QPushButton("参考答案")
        self.solution_button.clicked.connect(self.solutionRequested)
        row.addWidget(self.hint_button)
        row.addWidget(self.solution_button)
        layout.addLayout(row)
        self.notes_button = QPushButton("为什么这样学？")
        self.notes_button.clicked.connect(self.notesRequested)
        layout.addWidget(self.notes_button)
        self.hint_text = text_label(name="tipText")
        self.hint_text.hide()
        layout.addWidget(self.hint_text)
        self.reflection = QPlainTextEdit()
        self.reflection.setPlaceholderText("写下你看到了什么、为什么这样调整……")
        self.reflection.setAccessibleName("本步骤的实验观察")
        self.reflection.setMinimumHeight(72)
        self.reflection.setMaximumHeight(110)
        self.reflection.textChanged.connect(lambda: self.draftChanged.emit(self.reflection.toPlainText()))
        layout.addWidget(self.reflection)
        self.submit = QPushButton("保存我的观察")
        self.submit.clicked.connect(self.submit_reflection)
        layout.addWidget(self.submit)
        self.acknowledge = QPushButton("我已观察并完成操作")
        self.acknowledge.clicked.connect(lambda: self.eventRaised.emit("step.acknowledged", {}))
        layout.addWidget(self.acknowledge)
        self.requirement = text_label(name="softText")
        layout.addWidget(self.requirement)
        row = QHBoxLayout()
        self.next_button = QPushButton("下一步  →")
        self.next_button.setObjectName("primary")
        self.next_button.clicked.connect(lambda: self.advanceRequested.emit(False))
        self.skip_button = QPushButton("先跳过")
        self.skip_button.setToolTip("保留未完成标记，稍后可以回来继续。")
        self.skip_button.clicked.connect(lambda: self.advanceRequested.emit(True))
        row.addWidget(self.next_button, 1)
        row.addWidget(self.skip_button)
        layout.addLayout(row)

    def bind(self, session):
        self.session = session
        self._shown_step = None
        self.step_combo.clear()
        for index, step in enumerate(session.lesson.steps):
            self.step_combo.addItem(f"{index + 1}. {step.title}")
        self.refresh()

    def refresh(self):
        if self.session is None:
            return
        step = self.session.step
        self.previous_button.setEnabled(self.session.step_index > 0)
        self.step_combo.setCurrentIndex(-1 if step is None else self.session.step_index)
        for index, item in enumerate(self.session.lesson.steps):
            status = "✓ " if item.id in self.session.completed_step_ids else "待补 · " if item.id in self.session.skipped_step_ids else ""
            self.step_combo.setItemText(index, f"{status}{index + 1}. {item.title}")
        self.solution_button.setEnabled(self.session.has_attempt)
        finished = step is None
        for widget in (self.hint_button, self.reflection, self.submit, self.skip_button, self.acknowledge):
            widget.setVisible(not finished)
        if finished:
            self.step_title.setText("本课学习记录")
            completed = self.session.completed
            self.instruction.setText("本课的操作与观察已记录。继续下一课，或回到本课重新实验。" if completed
                                     else "已浏览到本课末尾。用上方步骤菜单返回，继续补做标记为待补的步骤。")
            self.next_button.setText("进入下一课  →")
            self.next_button.setEnabled(True)
            self.hint_text.hide()
            self.requirement.setText("")
            return
        if self._shown_step != step.id:
            self._shown_step = step.id
            self._hint_level = 0
            self.hint_text.hide()
            self.reflection.blockSignals(True)
            self.reflection.setPlainText(self.session.response_text())
            self.reflection.blockSignals(False)
        total = len(self.session.lesson.steps)
        self.step_title.setText(f"{self.session.step_index + 1} / {total}  {step.title}")
        self.instruction.setText(step.instruction.replace("`", ""))
        self.next_button.setText("完成这一步  →")
        self.next_button.setEnabled(self.session.can_advance)
        self.requirement.setText("已记录本步骤的操作，可以继续。" if self.session.can_advance
                                 else step.evidence or "完成上面的操作后继续；需要时可先跳过。")
        needs_reflection = any(event in str(step.completion) for event in ("reflection.submitted", "prediction.submitted"))
        self.reflection.setVisible(needs_reflection)
        self.submit.setVisible(needs_reflection)
        self.submit.setText("保存我的预测" if "prediction.submitted" in str(step.completion) else "保存我的观察")
        self.acknowledge.setVisible("step.acknowledged" in str(step.completion))

    def show_hint(self):
        if not self.session or self.session.step is None:
            return
        hints = self.session.step.hints
        if not hints:
            return
        index = min(self._hint_level, len(hints) - 1)
        self.hint_text.setText(hints[index])
        self.hint_text.show()
        self._hint_level = min(index + 1, len(hints) - 1)
        self.eventRaised.emit("hint.opened", {"level": index + 1})

    def submit_reflection(self):
        value = self.reflection.toPlainText().strip()
        if not value:
            self.reflection.setFocus()
            return
        kind = "prediction.submitted" if "prediction.submitted" in str(self.session.step.completion) else "reflection.submitted"
        self.eventRaised.emit(kind, {"field": "reflection", "value": value})
