"""Measured error area and reported controller memory, with explicit saturation."""

from collections import deque
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class ErrorArea(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = deque(maxlen=5000)
        self.setMinimumHeight(95)

    def paintEvent(self, event):
        painter = QPainter(self)
        area = QRectF(12, 12, max(20, self.width()-24), max(30, self.height()-36))
        painter.setPen(QPen(QColor("#A6B5AA"), 1))
        painter.drawLine(area.left(), area.center().y(), area.right(), area.center().y())
        if not self.samples:
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, "运行后显示误差随时间积累的面积")
            return
        span = max(.02, sum(sample[1] for sample in self.samples))
        limit = max(.1, max(abs(sample[0]) for sample in self.samples))
        position = 0.
        painter.setPen(Qt.PenStyle.NoPen)
        for error, dt, saturated, frozen in self.samples:
            height = error / limit * area.height() / 2
            painter.setBrush(QColor("#80B9A4") if error >= 0 else QColor("#E8BB8A"))
            x = area.left() + position / span * area.width()
            width = max(1., dt/span*area.width())
            painter.drawRect(QRectF(x, min(area.center().y(), area.center().y()-height), width, abs(height)))
            if saturated or frozen:
                painter.setBrush(QColor("#9B829F") if frozen else QColor("#CDA361"))
                painter.drawRect(QRectF(x, area.bottom()+4, width, 4))
            position += dt
        painter.setPen(QColor("#607666"))
        painter.drawText(QRectF(12, area.bottom()+10, self.width()-24, 18),
            Qt.AlignmentFlag.AlignLeft, "横轴：时间 · 绿色：正误差 · 杏色：负误差")


class IntegralPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.current = QLabel("误差 = 目标速度 − 当前速度")
        self.current.setWordWrap(True)
        layout.addWidget(self.current)
        self.area = ErrorArea()
        layout.addWidget(self.area)
        self.memory = QLabel("")
        self.memory.setWordWrap(True)
        layout.addWidget(self.memory)
        self.clear()

    def clear(self):
        self.total_area = 0.
        self.area.samples.clear()
        self.current.setText("误差 = 目标速度 − 当前速度；每步面积 = 误差 × dt")
        self.memory.setText("面积用于理解积累；控制器的积分值以代码实际报告为准。")
        self.area.update()

    def push(self, target, observed_velocity, dt, requested_force, force_limit, diagnostics):
        error = target - observed_velocity
        self.total_area += error * dt
        saturated = abs(requested_force) > force_limit + 1e-9
        frozen = diagnostics.get("frozen") is True
        self.area.samples.append((error, dt, saturated, frozen))
        self.current.setText(f"目标 {target:+.3f} − 实际 {observed_velocity:+.3f} = 误差 {error:+.3f} m/s\n"
                             f"本步面积 {error * dt:+.5f} m · 累计有符号面积 {self.total_area:+.4f} m")
        integral = diagnostics.get("integral")
        memory = "代码未报告积分记忆" if integral is None else f"代码报告积分记忆 {integral:+.4f} m"
        self.memory.setText(f"{memory} · 推力上限 ±{force_limit:g} N\n"
            "下方金色段：推力超出上限；紫色段：代码报告暂停积分。")
        self.area.update()
