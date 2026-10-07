"""Painted, resolution-independent widgets for the ControlLab desktop lessons."""

from __future__ import annotations

from collections import deque
import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QTextCharFormat, QSyntaxHighlighter
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget, QToolTip


INK = QColor("#21333B")
TEAL = QColor("#248577")
ORANGE = QColor("#E79451")


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(42, 44)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2F9485"))
        painter.drawRoundedRect(QRectF(0, 2, 40, 40), 12, 12)
        painter.setPen(QPen(QColor("#E3F6EF"), 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(10, 30), QPointF(31, 30))
        painter.drawLine(QPointF(21, 26), QPointF(25, 12))
        painter.setBrush(QColor("#E3F6EF"))
        painter.drawRoundedRect(QRectF(14, 23, 14, 7), 2, 2)
        painter.setBrush(ORANGE)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(25, 12), 3.2, 3.2)


class SimulationCanvas(QWidget):
    dragStarted = Signal(float)
    dragMoved = Signal(float)
    dragEnded = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(330)
        self.setMouseTracking(True)
        self.state = [0.0, 0.0, 0.0, 0.0]
        self.force = 0.0
        self.paused = True
        self.dragging = False
        self.allow_drag = True
        self.target_x = 0.0
        self._grab_offset_px = 0.0
        self.show_pole = True
        self.show_observations = False
        self.show_force = False
        self.show_angle = False
        self.show_trend = False
        self.disturbance_force = 0.0
        self.disturbance_caption = "外部轻推"
        self.center_band_m = 0.0
        self.fell = False
        self.tail = deque(maxlen=35)
        self._last_tip = None
        self.setAccessibleName("倒立摆互动实验区：按住中间小车并左右拖动")

    def geometry_values(self):
        margin = 54.0
        rail_width = max(100.0, self.width() - margin * 2)
        pixels_per_meter = rail_width / 4.8
        ground_y = self.height() * 0.74
        return margin, rail_width, pixels_per_meter, ground_y

    def x_to_screen(self, x):
        _, _, scale, _ = self.geometry_values()
        origin = 0.0 if self.show_pole else self.state[0]
        return self.width() / 2.0 + (x - origin) * scale

    def screen_to_x(self, x):
        _, _, scale, _ = self.geometry_values()
        return min(2.3, max(-2.3, (x - self.width() / 2.0) / scale))

    def cart_rect(self):
        _, _, _, rail_y = self.geometry_values()
        return QRectF(self.x_to_screen(self.state[0]) - 34, rail_y - 39, 68, 33)

    def set_state(self, state, force=0.0, paused=False, fell=False):
        self.state = list(state)
        self.force = float(force)
        self.paused = paused
        self.fell = fell
        _, _, _, rail_y = self.geometry_values()
        pivot = QPointF(self.x_to_screen(self.state[0]), rail_y - 37)
        length = min(155.0, self.height() * 0.35)
        tip = QPointF(pivot.x() + math.sin(self.state[2]) * length, pivot.y() - math.cos(self.state[2]) * length)
        if not paused and (self._last_tip is None or (tip - self._last_tip).manhattanLength() > 1.1):
            self.tail.append(tip)
            self._last_tip = tip
        self.update()

    def clear_trail(self):
        self.tail.clear()
        self._last_tip = None
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.allow_drag and self.cart_rect().adjusted(-18, -20, 18, 22).contains(event.position()):
            self.dragging = True
            self._grab_offset_px = event.position().x() - self.x_to_screen(self.state[0])
            self.target_x = self.state[0]
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.grabMouse()
            self.dragStarted.emit(self.target_x)
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.target_x = self.screen_to_x(event.position().x() - self._grab_offset_px)
            self.dragMoved.emit(self.target_x)
            self.update()
        else:
            active = self.allow_drag and self.cart_rect().adjusted(-18, -20, 18, 22).contains(event.position())
            self.setCursor(Qt.CursorShape.OpenHandCursor if active else Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.end_drag()
            event.accept()

    def end_drag(self):
        if self.dragging:
            self.dragging = False
            self.releaseMouse()
            self.dragEnded.emit()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def resizeEvent(self, event):
        # A layout change invalidates the screen-space grab anchor. End the
        # gesture rather than interpreting the new scale as a physical impulse.
        self.end_drag()
        self.clear_trail()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        margin, rail_width, scale, rail_y = self.geometry_values()
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor("#FAFCFA"))
        gradient.setColorAt(1, QColor("#F1F5F1"))
        painter.fillRect(self.rect(), gradient)

        # A quiet plotting grid leaves the moving mechanism as the visual focus.
        painter.setPen(QPen(QColor("#E5ECE6"), 1))
        for x in range(28, width, 36):
            for y in range(28, max(29, int(rail_y)), 36):
                painter.drawPoint(x, y)
        painter.setPen(QPen(QColor("#D7E2D9"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(width / 2, 48), QPointF(width / 2, rail_y + 10))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E5ECE4"))
        painter.drawRoundedRect(QRectF(margin - 12, rail_y + 10, rail_width + 24, 8), 4, 4)
        painter.setPen(QPen(QColor("#A0B2A6"), 2))
        painter.drawLine(QPointF(margin, rail_y), QPointF(width - margin, rail_y))
        for index in range(-4, 5):
            px = width / 2 + index * scale / 2
            painter.setPen(QPen(QColor("#CAD6CB"), 1))
            painter.drawLine(QPointF(px, rail_y + 21), QPointF(px, rail_y + (30 if index % 2 == 0 else 26)))
            if self.show_observations and index % 2 == 0:
                painter.setPen(QColor("#94A197"))
                painter.setFont(QFont("Microsoft YaHei UI", 9))
                coordinate = index / 2 + (0.0 if self.show_pole else self.state[0])
                painter.drawText(QRectF(px - 30, rail_y + 32, 60, 20), Qt.AlignmentFlag.AlignCenter, f"{coordinate:.1f} m")

        if self.dragging:
            target_px = self.x_to_screen(self.target_x)
            painter.setPen(QPen(QColor("#53A995"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(target_px, rail_y - 50), QPointF(target_px, rail_y + 5))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(60, 158, 135, 30))
            painter.drawEllipse(QPointF(target_px, rail_y - 20), 24, 24)

        if self.show_pole and len(self.tail) > 2:
            points = list(self.tail)
            for index in range(1, len(points)):
                painter.setPen(QPen(QColor(225, 151, 84, int(65 * index / len(points))), 2))
                painter.drawLine(points[index - 1], points[index])

        cart = self.cart_rect()
        pivot = QPointF(cart.center().x(), cart.top() + 2)
        length = min(155.0, height * 0.35)
        tip = QPointF(pivot.x() + math.sin(self.state[2]) * length, pivot.y() - math.cos(self.state[2]) * length)
        if self.center_band_m > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(40, 140, 115, 28))
            painter.drawRect(QRectF(self.x_to_screen(-self.center_band_m), rail_y - 48,
                2 * self.center_band_m * scale, 58))
        if self.show_pole and self.show_angle:
            painter.setPen(QPen(QColor("#9AAF9D"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(pivot, pivot + QPointF(0, -length - 12))
            painter.setPen(QPen(TEAL, 2))
            radius = min(55., length * .65)
            painter.drawArc(QRectF(pivot.x() - radius, pivot.y() - radius, radius * 2, radius * 2),
                90 * 16, round(-math.degrees(self.state[2]) * 16))
        if self.show_pole and self.show_trend and abs(self.state[3]) > .005:
            direction = 1 if self.state[3] > 0 else -1
            tangent = QPointF(math.cos(self.state[2]), math.sin(self.state[2]))
            start = tip + QPointF(0, -18)
            end = start + tangent * (direction * 30)
            painter.setPen(QPen(QColor("#AC7A51"), 2))
            painter.drawLine(start, end)
            normal = QPointF(-tangent.y(), tangent.x())
            painter.drawLine(end, end - tangent * (direction * 6) + normal * 4)
            painter.drawLine(end, end - tangent * (direction * 6) - normal * 4)
        if self.show_pole:
            painter.setPen(QPen(QColor("#C97737"), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(pivot, tip)
            painter.setPen(QPen(QColor("#EDA365"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(pivot, tip)
        painter.setPen(Qt.PenStyle.NoPen)
        if self.show_pole:
            painter.setBrush(QColor("#F6C18B"))
            painter.drawEllipse(tip, 9, 9)
            painter.setBrush(QColor("#B66B32"))
            painter.drawEllipse(tip, 3.5, 3.5)

        painter.setBrush(QColor(26, 50, 42, 18))
        painter.drawRoundedRect(cart.translated(0, 4).adjusted(-2, -1, 2, 1), 10, 10)
        painter.setBrush(QColor("#2B6E63") if self.dragging else QColor("#3E8476"))
        painter.drawRoundedRect(cart, 9, 9)
        painter.setBrush(QColor("#79B7A5"))
        painter.drawRoundedRect(cart.adjusted(7, 6, -7, -17), 3, 3)
        painter.setBrush(QColor("#24483F"))
        painter.drawEllipse(QPointF(cart.left() + 15, rail_y - 4), 7, 7)
        painter.drawEllipse(QPointF(cart.right() - 15, rail_y - 4), 7, 7)
        painter.setBrush(QColor("#AFC3B5"))
        painter.drawEllipse(QPointF(cart.left() + 15, rail_y - 4), 3, 3)
        painter.drawEllipse(QPointF(cart.right() - 15, rail_y - 4), 3, 3)
        painter.setBrush(QColor("#E6F0DE"))
        painter.drawEllipse(pivot, 7, 7)
        painter.setBrush(QColor("#2D695D"))
        painter.drawEllipse(pivot, 3, 3)

        if self.paused and self.allow_drag and not self.fell and not self.show_observations:
            painter.setPen(QPen(QColor("#8BB7A5"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for direction in (-1, 1):
                start = QPointF(cart.center().x() + direction * 53, cart.center().y())
                end = start + QPointF(direction * 35, 0)
                painter.drawLine(start, end)
                painter.drawLine(end, end + QPointF(-direction * 6, -4))
                painter.drawLine(end, end + QPointF(-direction * 6, 4))

        if self.show_force and abs(self.force) > .05:
            direction = 1 if self.force > 0 else -1
            start = QPointF(cart.center().x() + direction * 46, cart.center().y())
            end = start + QPointF(direction * (25 + abs(self.force) * 3.5), 0)
            painter.setPen(QPen(TEAL, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, end)
            painter.drawLine(end, end + QPointF(-direction * 7, -5))
            painter.drawLine(end, end + QPointF(-direction * 7, 5))
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(QRectF(min(start.x(), end.x()) - 10, start.y() - 30, abs(end.x() - start.x()) + 20, 24), Qt.AlignmentFlag.AlignCenter, f"{self.force:+.1f} N")
        if abs(self.disturbance_force) > .001:
            direction = 1 if self.disturbance_force > 0 else -1
            start = QPointF(cart.center().x() - direction * 110, cart.center().y() - 48)
            end = start + QPointF(direction * 55, 0)
            painter.setPen(QPen(ORANGE, 3))
            painter.drawLine(start, end)
            painter.drawLine(end, end + QPointF(-direction * 7, -5))
            painter.drawLine(end, end + QPointF(-direction * 7, 5))
            painter.drawText(QRectF(start.x() - 48, start.y() - 29, 155, 24), Qt.AlignmentFlag.AlignCenter,
                             f"{self.disturbance_caption} {self.disturbance_force:+g} N")


class SignalChart(QWidget):
    """SI-time plot with optional paired signals and one explicitly pinned run."""
    LABELS = {
        "x": ("小车位置", "m"), "v": ("实际速度", "m/s"),
        "target_v": ("目标速度", "m/s"), "theta": ("观测角度", "°"),
        "true_theta": ("真实角度", "°"), "omega": ("角速度", "°/s"),
        "force": ("实际推力", "N"), "requested_force": ("请求推力", "N"),
        "p": ("P 分项", "N"), "d": ("D 分项", "N"), "i": ("I 分项", "N"),
        "integral": ("误差积分", ""), "time": ("仿真时间", "s"), "reward": ("单步奖励", ""),
    }
    PARTNER = {"v": "target_v", "force": "requested_force", "theta": "true_theta"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = deque(maxlen=5000)
        self.reference_history = ()
        self.reference_label = "上次实验"
        self.available_channels = set()
        self.channel = "theta"
        self.cursor_time = None
        self._plot_rect = QRectF()
        self.setMouseTracking(True)
        self.setMinimumHeight(112)

    def append(self, observation, force=0.0, *, true_state=None, target_v=0, time_s=None,
               requested_force=0, reward=0, diagnostics=None):
        parts = diagnostics or {}
        truth = observation if true_state is None else true_state
        if time_s is None:
            time_s = (self.history[-1]["time"] if self.history else 0) + .02

        def diagnostic(name):
            value = parts.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return None
            return float(value) if math.isfinite(value) else None

        self.history.append(dict(x=float(observation[0]), v=float(observation[1]),
                                 theta=math.degrees(float(observation[2])),
                                 omega=math.degrees(float(observation[3])), force=float(force),
                                 true_theta=math.degrees(float(truth[2])),
                                 target_v=float(target_v), time=float(time_s),
                                 requested_force=float(requested_force), reward=float(reward),
                                 integral=diagnostic("integral"), p=diagnostic("p_n"),
                                 d=diagnostic("d_n"), i=diagnostic("i_n")))
        self.update()

    def clear(self):
        """A new attempt clears live samples, preserving an intentional A/B pin."""
        self.history.clear()
        self.cursor_time = None
        self.update()

    def pin_reference(self, label="上次实验"):
        if not self.history:
            return False
        self.reference_history = tuple(dict(sample) for sample in self.history)
        self.reference_label = str(label)
        self.update()
        return True

    def clear_reference(self):
        self.reference_history = ()
        self.update()

    def readout_at(self, time_s):
        """Read all visible runs at one physical time, never stretch a short run."""
        lines = [f"仿真时间 {float(time_s):.2f} s"]
        for channel, title, samples, _, _ in self.series():
            unit = self.LABELS.get(channel, (channel, ""))[1]
            if not samples or time_s < samples[0]["time"] - 1e-9 or time_s > samples[-1]["time"] + 1e-9:
                lines.append(f"{title}：该时刻无记录")
                continue
            sample = min(samples, key=lambda row: abs(row["time"] - time_s))
            value = sample.get(channel)
            lines.append(f"{title}：{value:+.4g} {unit}" if self._valid_value(value) else f"{title}：未提供读数")
        return "\n".join(lines)

    def mouseMoveEvent(self, event):
        if self._plot_rect.contains(event.position()):
            left, right, _, _ = self.ranges()
            raw_time = left + (event.position().x() - self._plot_rect.left()) / self._plot_rect.width() * (right - left)
            samples = tuple(self.history) + self.reference_history
            self.cursor_time = min(samples, key=lambda row: abs(row["time"] - raw_time))["time"] if samples else None
            if self.cursor_time is not None:
                QToolTip.showText(event.globalPosition().toPoint(), self.readout_at(self.cursor_time), self)
            self.update()
        else:
            self.cursor_time = None
            QToolTip.hideText()
            self.update()

    def leaveEvent(self, event):
        self.cursor_time = None
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def series(self):
        """The exact displayed data, useful for export and tests without image guesses."""
        result = [(self.channel, self.LABELS.get(self.channel, (self.channel, ""))[0],
                   tuple(self.history), QColor("#DA9657"), False)]
        partner = self.PARTNER.get(self.channel)
        if partner is not None and partner in self.available_channels:
            result.append((partner, self.LABELS[partner][0], tuple(self.history), QColor("#248577"), True))
        if self.reference_history:
            result.append((self.channel, self.reference_label, self.reference_history, QColor("#7888AB"), True))
        return result

    @staticmethod
    def _valid_value(value):
        return value is not None and isinstance(value, (int, float)) and math.isfinite(value)

    def ranges(self):
        series = self.series()
        values = [sample.get(channel) for channel, _, samples, _, _ in series for sample in samples
                  if self._valid_value(sample.get(channel))]
        times = [sample["time"] for _, _, samples, _, _ in series for sample in samples]
        floor = 12.0 if self.channel in ("theta", "true_theta", "omega") else 1.0
        limit = max(floor, max((abs(value) for value in values), default=0) * 1.15)
        left = min(times, default=0)
        if left <= .02:
            left = 0.0
        right = max(left + .02, max(times, default=1.0))
        return left, right, -limit, limit

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        metrics = painter.fontMetrics()
        inset = max(48, metrics.horizontalAdvance("−100.0") + 8)
        legend_x, legend_y = float(inset), 13.0
        series = self.series()
        for _, title, _, color, dashed in series:
            needed = metrics.horizontalAdvance(title) + 34
            if legend_x + needed > self.width() - 8 and legend_x > inset:
                legend_x, legend_y = float(inset), legend_y + metrics.height() + 3
            painter.setPen(QPen(color, 2, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            painter.drawLine(QPointF(legend_x, legend_y - 3), QPointF(legend_x + 16, legend_y - 3))
            painter.setPen(INK)
            painter.drawText(QPointF(legend_x + 21, legend_y), title)
            legend_x += needed
        top = legend_y + 12
        area = QRectF(inset, top, max(20, self.width() - inset - 12), max(18, self.height() - top - 25))
        self._plot_rect = area
        left, right, low, high = self.ranges()
        for fraction, label in ((0., f"+{high:.2g}"), (.5, "0"), (1., f"{low:.2g}")):
            y = area.top() + area.height() * fraction
            painter.setPen(QColor("#809186"))
            painter.drawText(QRectF(0, y - 9, inset - 8, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)
            painter.setPen(QPen(QColor("#E6ECE7"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
        unit = self.LABELS.get(self.channel, ("", ""))[1]
        painter.setPen(QColor("#809186"))
        painter.drawText(QRectF(0, 2, inset - 8, 18), Qt.AlignmentFlag.AlignRight, unit)
        painter.drawText(QRectF(area.left(), area.bottom() + 5, area.width() / 2, 18),
                         Qt.AlignmentFlag.AlignLeft, f"{left:.2f} s")
        painter.drawText(QRectF(area.center().x(), area.bottom() + 5, area.width() / 2, 18),
                         Qt.AlignmentFlag.AlignRight, f"{right:.2f} s")
        painter.save()
        painter.setClipRect(area.adjusted(-1, -1, 1, 1))
        any_data = False
        for channel, _, samples, color, dashed in series:
            path = QPainterPath()
            connected = False
            for sample in samples:
                value = sample.get(channel)
                if not self._valid_value(value):
                    connected = False
                    continue
                any_data = True
                point = QPointF(area.left() + (sample["time"] - left) / (right - left) * area.width(),
                                area.bottom() - (value - low) / (high - low) * area.height())
                if not connected:
                    path.moveTo(point)
                    connected = True
                else:
                    path.lineTo(point)
            painter.setPen(QPen(color, 2.0, Qt.PenStyle.DashLine if dashed else Qt.PenStyle.SolidLine))
            painter.drawPath(path)
        painter.restore()
        if self.cursor_time is not None and left <= self.cursor_time <= right:
            x = area.left() + (self.cursor_time - left) / (right - left) * area.width()
            painter.setPen(QPen(QColor("#697C75"), 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, area.top()), QPointF(x, area.bottom()))
        if not any_data:
            painter.setPen(QColor("#84948B"))
            text = "本次代码未提供该分项" if self.channel in ("integral", "p", "d", "i") else "运行后显示曲线"
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, text)


class FlowIndicator(QWidget):
    """A presentation-only animation. It never requests actions or steps physics."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(92)
        self.setAccessibleName("读取状态、计算动作、施加推力的单步流程")
        self.observation = (0., 0., 0., 0.)
        self.force = 0.0
        self.dt = .02
        self.stage = -1
        self.step_count = 0
        self._animation = QTimer(self)
        self._animation.setInterval(130)
        self._animation.timeout.connect(self._advance_visual)

    def display_step(self, observation, force, dt):
        values = tuple(float(value) for value in observation)
        force, dt = float(force), float(dt)
        if len(values) != 4 or not all(math.isfinite(value) for value in (*values, force, dt)) or dt <= 0:
            raise ValueError("flow display requires four finite observations, force and positive dt")
        self.observation, self.force, self.dt = values, force, dt
        self.step_count += 1
        if not self._animation.isActive():
            self.stage = 0
            self._animation.start()
        self.update()

    def _advance_visual(self):
        if self.stage < 2:
            self.stage += 1
        else:
            self._animation.stop()
        self.update()

    def clear(self):
        self._animation.stop()
        self.stage = -1
        self.step_count = 0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        gap = 14.0
        card_width = max(50., (self.width() - 2 * gap - 4) / 3)
        cards = [QRectF(2 + index * (card_width + gap), 3, card_width, 64) for index in range(3)]
        details = (f"v={self.observation[1]:+.3f} m/s", f"dt={self.dt:g} s", f"F={self.force:+.3f} N")
        for index, (card, title, detail) in enumerate(zip(cards, ("读取状态", "计算动作", "施加推力"), details)):
            active = index == self.stage
            painter.setPen(QPen(QColor("#74AD97") if active else QColor("#DEE7DD"), 1))
            painter.setBrush(QColor("#E2F1E7") if active else QColor("#F7F9F4"))
            painter.drawRoundedRect(card, 8, 8)
            painter.setPen(INK)
            painter.setFont(QFont("Microsoft YaHei UI", 10))
            painter.drawText(card.adjusted(3, 8, -3, -30), Qt.AlignmentFlag.AlignCenter, title)
            painter.setFont(QFont("Consolas", 9))
            painter.drawText(card.adjusted(2, 31, -2, -4), Qt.AlignmentFlag.AlignCenter, detail)
            if index < 2:
                painter.setPen(QColor("#709887"))
                painter.drawText(QRectF(card.right(), card.top(), gap, card.height()), Qt.AlignmentFlag.AlignCenter, "→")
        painter.setPen(QColor("#687F70"))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(QRectF(3, 71, self.width() - 6, 20), Qt.AlignmentFlag.AlignLeft,
                         "一次函数调用只推进一个物理步；动画速度不改变 dt。")


class MetricCard(QFrame):
    def __init__(self, title, symbol, unit, parent=None):
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 11, 15, 12)
        layout.setSpacing(3)
        title_label = QLabel(f"{title}  ·  {symbol}")
        title_label.setObjectName("metricTitle")
        self.value_label = QLabel("0.00")
        self.value_label.setObjectName("metricValue")
        unit_label = QLabel(unit)
        unit_label.setObjectName("metricUnit")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(unit_label)

    def set_value(self, value):
        self.value_label.setText(f"{value:+.2f}" if abs(value) >= .005 else "0.00")


class PythonHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        for pattern, color in [
            (r"\b(?:def|return|if|elif|else|for|while|in|import|from|as|True|False|None|and|or|not)\b", "#9260AD"),
            (r"\b(?:state|dt|control)\b", "#277F75"),
            (r"\b\d+(?:\.\d+)?\b", "#BE7F35"),
            (r"[\"'][^\"']*[\"']", "#478753"),
            (r"#.*$", "#879792"),
        ]:
            style = QTextCharFormat()
            style.setForeground(QColor(color))
            self.rules.append((re.compile(pattern), style))

    def highlightBlock(self, text):
        for pattern, style in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), style)
