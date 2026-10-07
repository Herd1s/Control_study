"""Progressive teaching controls. Editing values never changes an active controller."""
from __future__ import annotations

import math
from numbers import Real

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFrame, QGridLayout,
    QLabel, QPushButton, QVBoxLayout, QWidget,
)


def _label(text="", name="guideText"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class ControllerPanel(QFrame):
    """Emit a new source file only after an explicit click; caller owns saving/loading.

    The diagnostics are reported by the student's running code. Unknown or absent
    components stay unavailable; they are never inferred from edited parameters.
    """
    codeRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("guide")
        self.lesson_id = "L13"
        self.lesson_number = 13
        self._running = False
        self._loading = False
        self._dirty = False
        self.fields = {}
        self.rows = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)
        self.title = _label("本课控制参数", "guideTitle")
        self.scope = _label()
        layout.addWidget(self.title)
        layout.addWidget(self.scope)
        self.form = QGridLayout()
        self.form.setColumnStretch(0, 1)
        self.form.setHorizontalSpacing(10)
        self.form.setVerticalSpacing(6)
        definitions = (
            ("kp", "比例 Kp", 0., 300., 5., 2),
            ("kd", "角速度 Kd", 0., 60., 1., 2),
            ("ki", "积分 Ki", 0., 30., .1, 3),
            ("kx", "位置回中 Kx", 0., 20., .5, 2),
            ("kv", "速度回中 Kv", 0., 20., .5, 2),
            ("integral_limit", "积分上限", .01, 100., .1, 2),
            ("tau", "滤波时间 τ (s)", 0., .5, .01, 3),
        )
        for row, (key, text, minimum, maximum, step, decimals) in enumerate(definitions):
            label = _label(text)
            field = QDoubleSpinBox()
            field.setRange(minimum, maximum)
            field.setSingleStep(step)
            field.setDecimals(decimals)
            field.setMaximumWidth(112)
            field.setMinimumWidth(88)
            field.setAccessibleName(text)
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self._parameters_changed)
            self.form.addWidget(label, row, 0)
            self.form.addWidget(field, row, 1)
            self.fields[key] = field
            self.rows[key] = (label, field)
        layout.addLayout(self.form)
        self.anti_label = _label("积分保护")
        self.anti_windup = QComboBox()
        for text, mode in (("不保护", "none"), ("只限制积分大小", "limit"), ("条件积分 + 积分限幅", "conditional")):
            self.anti_windup.addItem(text, mode)
        self.anti_windup.setAccessibleName("积分保护方式")
        self.anti_windup.currentIndexChanged.connect(self._parameters_changed)
        layout.addWidget(self.anti_label)
        layout.addWidget(self.anti_windup)
        self.filter_enabled = QCheckBox("滤波角速度读数")
        self.filter_enabled.toggled.connect(self._parameters_changed)
        layout.addWidget(self.filter_enabled)
        self.formula = _label(name="tipText")
        self.change_note = _label(name="guideText")
        layout.addWidget(self.formula)
        layout.addWidget(self.change_note)
        self.apply_button = QPushButton("应用并重新实验")
        self.apply_button.setObjectName("primary")
        self.apply_button.setToolTip("生成新的控制代码；由实验窗口保存并载入，之后手动运行。")
        self.apply_button.clicked.connect(self._apply)
        layout.addWidget(self.apply_button)
        self.diagnostics_title = _label("这一步实际计算的推力", "sectionTitle")
        layout.addWidget(self.diagnostics_title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.diagnostic_labels = {}
        for index, (key, text) in enumerate((("p_n", "P"), ("d_n", "D"), ("i_n", "I"), ("centering_n", "回中"))):
            label = _label(f"{text}  —")
            self.diagnostic_labels[key] = (text, label)
            grid.addWidget(label, index // 2, index % 2)
        layout.addLayout(grid)
        self.diagnostic_status = _label("运行带 diagnostics() 的代码后显示。")
        layout.addWidget(self.diagnostic_status)
        self.set_lesson("L13")

    def _show_row(self, key, visible):
        for widget in self.rows[key]:
            widget.setVisible(visible)

    def set_lesson(self, lesson_id):
        if not isinstance(lesson_id, str) or len(lesson_id) != 3 or not lesson_id.startswith("L") or not lesson_id[1:].isdigit():
            raise ValueError("lesson_id must look like L13")
        self.lesson_id = lesson_id
        self.lesson_number = int(lesson_id[1:])
        active = 13 <= self.lesson_number <= 22
        self.setVisible(active)
        if not active:
            return
        self._loading = True
        number = self.lesson_number
        velocity = number in (17, 18)
        values = dict(kp=2.0 if velocity else 60.0, kd=12.0,
                      ki=1.0 if velocity else 0.0, kx=2.0, kv=3.0,
                      integral_limit=1.0 if number == 18 else 20.0 if velocity else .5, tau=.05)
        for name, value in values.items():
            self.fields[name].setValue(value)
        self.fields["kp"].setSingleStep(.5 if velocity else 5)
        self.anti_windup.setCurrentIndex(0 if number == 17 else 2)
        self.filter_enabled.setChecked(number == 20)
        self._show_row("kp", True)
        self._show_row("kd", number >= 15 and not velocity)
        self._show_row("ki", number >= 17)
        self._show_row("kx", number == 16 or number >= 19)
        self._show_row("kv", number == 16 or number >= 19)
        self.anti_label.setVisible(number >= 18)
        self.anti_windup.setVisible(number >= 18)
        self.filter_enabled.setVisible(number >= 20)
        scopes = {
            13: "只看角度。杆向右倾时，给小车向右的推力。",
            14: "只改 Kp，用同样初态比较。更大不一定更稳。",
            15: "加入角速度。角度相同、倾倒速度不同，用力也不同。",
            16: "在保杆之外尝试回中。回中项沿用当前耦合模型的正号。",
            17: "固定杆的速度实验台：误差 = 目标速度 − 实际速度。",
            18: "速度实验台限力 ±1 N。对照三种积分保护方式。",
            19: "保留跨步记忆；重新实验时 reset() 将积分清零。Ki 可为 0。",
            20: "滤波可能减少抖动，也会增加迟滞。先比较，再选择。",
            21: "先冻结代码，再在相同协议下比较。这里的读数不是评分。",
            22: "为个人项目生成起点，保留基线和失败案例。",
        }
        self.scope.setText(scopes[number])
        self._loading = False
        self._dirty = False
        self._refresh()
        self.set_diagnostics({})

    def values(self):
        result = {name: field.value() for name, field in self.fields.items()}
        result["anti_windup"] = self.anti_windup.currentData()
        result["filter_enabled"] = self.filter_enabled.isChecked()
        return result

    def _parameters_changed(self, *_):
        if self._loading:
            return
        self._dirty = True
        self._refresh()

    def _refresh(self):
        number = self.lesson_number
        values = self.values()
        self._show_row("integral_limit", number >= 18 and values["anti_windup"] != "none")
        self._show_row("tau", number >= 20 and values["filter_enabled"])
        if number in (17, 18):
            formula = "u = Kp × (目标速度 − v) + Ki × 累积误差"
        else:
            formula = "u = Kp × θ"
            if number >= 15:
                formula += " + Kd × ω"
            if number >= 19:
                formula += " + Ki × ∫θdt"
            if number == 16 or number >= 19:
                formula += " + Kx × x + Kv × v"
        self.formula.setText(formula + "\n代码角度用 rad，推力用 N。")
        self.apply_button.setEnabled(not self._running and 13 <= number <= 22)
        if self._running:
            message = "参数可先修改；请停止当前实验后再应用。"
        elif self._dirty:
            message = "参数已修改，当前代码未改变。点击后生成新实验代码。"
        else:
            message = "这些数值是参考起点。点击生成代码，再手动运行观察。"
        self.change_note.setText(message)

    def set_running(self, running):
        self._running = bool(running)
        self._refresh()

    def _apply(self):
        if self._running or not 13 <= self.lesson_number <= 22:
            return
        source = self.generate_code()
        self._dirty = False
        self._refresh()
        self.codeRequested.emit(source)

    def set_diagnostics(self, diagnostics):
        values = diagnostics if isinstance(diagnostics, dict) else {}
        known = False
        for key, (text, label) in self.diagnostic_labels.items():
            value = values.get(key)
            valid = isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(float(value))
            label.setText(f"{text}  {float(value):+.3f} N" if valid else f"{text}  —")
            known |= valid
        if not known:
            self.diagnostic_status.setText("本次代码未提供分项，不推测 P / D / I。")
            return
        flags = []
        if values.get("frozen") is True or values.get("integral_frozen") is True:
            flags.append("本步冻结积分")
        if values.get("saturated") is True:
            flags.append("请求推力超出电机上限")
        self.diagnostic_status.setText("；".join(flags) if flags else "以上来自当前代码的实际计算。")

    def generate_code(self):
        if not 13 <= self.lesson_number <= 22:
            raise ValueError("this lesson has no controller parameter panel")
        number, values = self.lesson_number, self.values()
        if number <= 16:
            return self._elementary_code(number, values)
        return self._stateful_code(number, values)

    @staticmethod
    def _elementary_code(number, values):
        lines = [f"# L{number:02d}：参数面板生成的新实验。角度 rad，推力 N。",
                 f"kp = {values['kp']!r}"]
        if number >= 15:
            lines.append(f"kd = {values['kd']!r}")
        if number == 16:
            lines += [f"kx = {values['kx']!r}", f"kv = {values['kv']!r}"]
        lines += ["_parts = {}", "", "def reset():", "    _parts.clear()", "",
                  "def control(state, dt):", "    p = kp * state['theta']"]
        if number >= 15:
            lines.append("    d = kd * state['omega']")
        if number == 16:
            lines.append("    centering = kx * state['x'] + kv * state['v']")
        terms = ["p"] + (["d"] if number >= 15 else []) + (["centering"] if number == 16 else [])
        lines += [f"    force = {' + '.join(terms)}", "    _parts.update(", "        p_n=p,"]
        if number >= 15:
            lines.append("        d_n=d,")
        if number == 16:
            lines.append("        centering_n=centering,")
        lines += ["        unsaturated_n=force,", "        applied_n=max(-10.0, min(10.0, force)),",
                  "        saturated=abs(force) > 10.0,", "    )", "    return force", "",
                  "def diagnostics():", "    return dict(_parts)", ""]
        return "\n".join(lines)

    @staticmethod
    def _stateful_code(number, values):
        velocity = number in (17, 18)
        limit = 1.0 if number == 18 else 10.0
        protection = "none" if number == 17 else values["anti_windup"]
        integral_limit = None if protection == "none" else values["integral_limit"]
        anti = protection == "conditional"
        filtered = number >= 20 and values["filter_enabled"]
        lines = [f"# L{number:02d}：新实验。control 返回推力 N，reset 清空跨步记忆。"]
        if velocity:
            lines += ["from control_lab.controllers.pid import VelocityPIController", "",
                      "# 公共控制器保存积分；不需要在每一步重新创建。",
                      "_controller = VelocityPIController(",
                      f"    kp={values['kp']!r}, ki={values['ki']!r},",
                      f"    force_limit_n={limit!r}, integral_limit={integral_limit!r},",
                      f"    anti_windup={anti!r},", ")"]
        else:
            lines += ["from control_lab.controllers.pid import PIDController",
                      "from control_lab.controllers.centering import CenteringFeedback"]
            if filtered:
                lines.append("from control_lab.controllers.filters import FirstOrderLowPass")
            lines += ["", "# 这是耦合倒立摆的回中项：+Kx*x + Kv*v。",
                      "_controller = PIDController(",
                      f"    kp={values['kp']!r}, ki={values['ki']!r}, kd={values['kd']!r},",
                      f"    centering=CenteringFeedback({values['kx']!r}, {values['kv']!r}),",
                      f"    force_limit_n={limit!r}, integral_limit={integral_limit!r},",
                      f"    anti_windup={anti!r},", ")"]
            if filtered:
                lines += [f"_omega_filter = FirstOrderLowPass(tau_s={values['tau']!r})",
                          "# 滤波使用物理 dt；tau=0 时直接使用当前读数。"]
        lines += ["", "def reset():", "    _controller.reset()"]
        if filtered:
            lines.append("    _omega_filter.reset()")
        lines += ["", "def control(state, dt):"]
        if velocity:
            lines += ["    # 目标由速度实验台提供；误差为 target_v - v。",
                      "    _controller.target_velocity_mps = state['target_v']",
                      "    return _controller.act(state, dt)"]
        elif filtered:
            lines += ["    measured = dict(state)",
                      "    measured['omega'] = _omega_filter.update(state['omega'], dt)",
                      "    return _controller.act(measured, dt)"]
        else:
            lines.append("    return _controller.act(state, dt)")
        lines += ["", "def diagnostics():", "    parts = dict(_controller.diagnostics)",
                  "    parts['frozen'] = parts.get('integral_frozen', False)", "    return parts", ""]
        return "\n".join(lines)


TeachingControllerPanel = ControllerPanel
