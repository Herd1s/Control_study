"""Recorded physical comparisons, sign prediction cards, and explicit angle units."""

import math
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QPushButton, QSlider, QVBoxLayout, QWidget)

from control_lab.desktop.ui_widgets import SimulationCanvas
from control_lab.lessons.foundation_clips import save_comparison


class FoundationsPanel(QFrame):
    eventRaised = Signal(str, dict)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self._lesson_id = None
        self.data = None
        self.timer = QTimer(self)
        self.timer.setInterval(40)  # half speed, timestamps still use recorded physics dt
        self.timer.timeout.connect(self._advance)
        self.setObjectName("surface")
        layout = QVBoxLayout(self)
        title = QLabel("同一时刻，两种运动趋势")
        title.setStyleSheet("font-size:16px;font-weight:600")
        layout.addWidget(title)
        row = QHBoxLayout()
        self.canvases, self.readings = [], []
        for index in range(2):
            group = QVBoxLayout()
            group.addWidget(QLabel("片段 A" if index == 0 else "片段 B"))
            canvas = SimulationCanvas()
            canvas.allow_drag = False
            canvas.setMinimumHeight(165)
            canvas.show_angle = True
            canvas.show_trend = True
            self.canvases.append(canvas)
            group.addWidget(canvas)
            reading = QLabel("")
            reading.setWordWrap(True)
            self.readings.append(reading)
            group.addWidget(reading)
            row.addLayout(group, 1)
        layout.addLayout(row)
        controls = QHBoxLayout()
        self.play = QPushButton("播放片段")
        self.play.clicked.connect(self._play_pause)
        self.reveal = QPushButton("揭示读数")
        self.reveal.setCheckable(True)
        self.reveal.toggled.connect(self._show_frame)
        self.inspect = QPushButton("记录这一帧的对照")
        self.inspect.clicked.connect(self._inspect)
        for button in (self.play, self.reveal, self.inspect):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._show_frame)
        layout.addWidget(self.slider)
        self.clock = QLabel("")
        layout.addWidget(self.clock)
        self.quiz = QWidget()
        quiz = QGridLayout(self.quiz)
        quiz.addWidget(QLabel("预测卡 · 先判断，再检查"), 0, 0, 1, 3)
        self.answers = []
        for row_index, caption in enumerate(("右侧，正在向左", "左侧，正在向右", "中心，静止"), 1):
            quiz.addWidget(QLabel(caption), row_index, 0)
            pair = []
            for column, quantity in ((1, "位置"), (2, "速度")):
                combo = QComboBox()
                combo.addItem(f"{quantity}符号", None)
                for text, value in (("正", 1), ("零", 0), ("负", -1)):
                    combo.addItem(text, value)
                combo.setAccessibleName(caption + "的" + quantity + "符号")
                quiz.addWidget(combo, row_index, column)
                pair.append(combo)
            self.answers.append(pair)
        self.check = QPushButton("检查这三张预测卡")
        self.check.clicked.connect(self._check)
        quiz.addWidget(self.check, 4, 0, 1, 3)
        self.feedback = QLabel("")
        self.feedback.setWordWrap(True)
        quiz.addWidget(self.feedback, 5, 0, 1, 3)
        layout.addWidget(self.quiz)
        self.conversion = QWidget()
        conversion = QHBoxLayout(self.conversion)
        self.degrees = QDoubleSpinBox()
        self.degrees.setRange(-180, 180)
        self.degrees.setValue(5.)
        self.degrees.setSuffix(" °")
        conversion.addWidget(self.degrees)
        self.convert_button = QPushButton("代码里如何表示？")
        self.convert_button.clicked.connect(self._convert)
        conversion.addWidget(self.convert_button)
        self.radians = QLabel("")
        conversion.addWidget(self.radians)
        layout.addWidget(self.conversion)

    def bind(self, session):
        self.shutdown()
        self._lesson_id = session.lesson.id
        self.data, self.path = save_comparison(self.data_dir, self._lesson_id)
        self.slider.setRange(0, min(len(c["frames"]) for c in self.data["clips"]) - 1)
        self.slider.setValue(0)
        self.reveal.setChecked(False)
        self.quiz.setVisible(self._lesson_id == "L03")
        self.conversion.setVisible(self._lesson_id == "L04")
        self.feedback.clear()
        for pair in self.answers:
            for combo in pair:
                combo.setCurrentIndex(0)
        for event in session.step_events.get("step_07", []):
            payload = event.get("payload", {})
            if payload.get("kind") == "sign_prediction":
                for pair, values in zip(self.answers, payload.get("answers", [])):
                    for combo, value in zip(pair, values):
                        combo.setCurrentIndex(combo.findData(value))
        self._show_frame()

    def _show_frame(self, *_):
        if self.data is None:
            return
        index = self.slider.value()
        for canvas, reading, clip in zip(self.canvases, self.readings, self.data["clips"]):
            frame = clip["frames"][index]
            state = frame["state"]
            canvas.set_state(state, 0., not self.timer.isActive())
            canvas.show_angle = self._lesson_id != "L03"
            canvas.show_trend = self._lesson_id != "L03"
            if self.reveal.isChecked():
                text = (f"位置 {state[0]:+.3f} m · 速度 {state[1]:+.3f} m/s" if self._lesson_id == "L03" else
                        f"角度 {math.degrees(state[2]):+.2f}° ({state[2]:+.3f} rad)\n角速度 {state[3]:+.3f} rad/s")
                reading.setText(text)
            else:
                reading.setText("先看动画，判断运动方向。")
        self.clock.setText(f"共同时间 {self.data['clips'][0]['frames'][index]['time_s']:.2f} s · ½ 倍速 · 固定零推力")

    def _play_pause(self):
        if self.timer.isActive():
            self.shutdown()
        else:
            if self.slider.value() == self.slider.maximum():
                self.slider.setValue(0)
            self.timer.start()
            self.play.setText("暂停片段")

    def _advance(self):
        if self.slider.value() >= self.slider.maximum():
            self.shutdown()
            self.eventRaised.emit("answer.checked", {"kind": "paired_replay", "path": str(self.path)})
        else:
            self.slider.setValue(self.slider.value() + 1)

    def _inspect(self):
        self.shutdown()
        self.reveal.setChecked(True)
        self._show_frame()
        self.eventRaised.emit("answer.checked", {"kind": "paired_inspection", "path": str(self.path),
            "frame_index": self.slider.value(), "states": [c["frames"][self.slider.value()]["state"] for c in self.data["clips"]]})

    def _check(self):
        answers = [[combo.currentData() for combo in pair] for pair in self.answers]
        if any(value is None for pair in answers for value in pair):
            self.feedback.setText("请先为每张卡选择两个符号。")
            return
        expected = [[1, -1], [-1, 1], [0, 0]]
        correct = [answer == truth for answer, truth in zip(answers, expected)]
        self.feedback.setText(f"答对 {sum(correct)} / 3 张。" + ("可以继续，并用自己的话解释。" if all(correct)
            else "位置看在中心哪一边；速度看正在朝哪一边走。再看一遍片段后可以重做。"))
        self.eventRaised.emit("answer.checked", {"kind": "sign_prediction", "answers": answers,
            "correct_count": sum(correct), "correct": correct})

    def _convert(self):
        value = math.radians(self.degrees.value())
        self.radians.setText(f"{value:+.4f} rad")
        self.eventRaised.emit("answer.checked", {"kind": "angle_conversion", "degrees": self.degrees.value(), "radians": value})

    def shutdown(self):
        self.timer.stop()
        self.play.setText("播放片段")
        return True
