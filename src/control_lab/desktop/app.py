"""A gentle, offline desktop introduction to feedback control."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import os
import sys
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent, QFont, QFontDatabase, QIcon, QTextCursor
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow,
    QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget, QDialog, QTabWidget,
)

from control_lab.paths import user_data_dir
from control_lab.desktop.engine import CodeController, TeachingSimulation
from control_lab.desktop.ui_widgets import BrandMark, MetricCard, PythonHighlighter, SignalChart, SimulationCanvas, FlowIndicator
from control_lab.desktop.panels.lesson import LessonPanel
from control_lab.lessons import load_lessons, LessonSession
from control_lab.storage.progress import ProgressStore
from control_lab.desktop.panels.controller import ControllerPanel
from control_lab.desktop.panels.evaluation import EvaluationPanel
from control_lab.desktop.panels.training import TrainingPanel
from control_lab.desktop.panels.tita import TitaPanel
from control_lab.desktop.panels.updates import UpdatesPanel
from control_lab.desktop.panels.signals import SignalsPanel
from control_lab.desktop.panels.history import HistoryDialog
from control_lab.core.types import Action


STYLES = """
QMainWindow, QWidget#appRoot { background: #F5F6F1; color: #23373D; }
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei', sans-serif; font-size: 13px; }
QLabel { background: transparent; color: #23373D; }
QFrame#sidebar { background: #1D333A; border: none; }
QLabel#brandName { color: #F2F5ED; font-size: 19px; font-weight: 600; }
QLabel#sidebarCaption { color: #8FA7A2; font-size: 13px; }
QPushButton#nav { text-align: left; padding: 15px 15px; border: 0; border-radius: 9px; background: transparent; color: #ADBEBA; font-size: 13px; }
QPushButton#nav:hover { background: #28454A; color: #FFFFFF; }
QPushButton#nav:checked { background: #365650; color: #EFF8ED; font-weight: 600; }
QLabel#futureNav { color: #6F8A87; padding: 8px 15px; font-size: 12px; }
QLabel#pageTitle { color: #23373D; font-size: 27px; font-weight: 600; }
QFrame#surface { background: #FFFFFF; border: 1px solid #E1E7DE; border-radius: 13px; }
QFrame#guide { background: #FEFEFA; border: 1px solid #E1E7DE; border-radius: 13px; }
QLabel#sectionTitle { color: #34463D; font-size: 14px; font-weight: 600; }
QLabel#smallLabel { color: #8B998F; font-size: 11px; }
QLabel#guideNumber { color: #4E8C7A; background: #EAF3E8; border-radius: 12px; font-size: 12px; font-weight: 600; }
QLabel#guideTitle { font-size: 15px; font-weight: 600; color: #32473B; }
QLabel#guideText { color: #7B8A80; font-size: 12px; line-height: 1.6; }
QLabel#softText { color: #7B8A80; font-size: 12px; }
QLabel#tipTitle { color: #9A6A39; font-size: 12px; font-weight: 600; }
QLabel#tipText { color: #9D815C; font-size: 12px; }
QFrame#tip { background: #F8F0E1; border: 0; border-radius: 10px; }
QLabel#status { color: #607666; font-size: 13px; }
QPushButton { background: #FFFFFF; border: 1px solid #DAE3D9; border-radius: 7px; padding: 7px 12px; color: #607666; }
QPushButton:hover { background: #EEF5EA; border-color: #B9CEC0; }
QPushButton:pressed { background: #E0EDDF; }
QPushButton:disabled { color: #B3BCB3; border-color: #E5E9E2; background: #F6F8F3; }
QPushButton#primary { background: #2D8375; color: #FFFFFF; border: 1px solid #2D8375; padding: 10px 13px; font-weight: 600; }
QPushButton#primary:hover { background: #246E62; }
QPushButton#primary:disabled { background: #A8C6B9; border-color: #A8C6B9; }
QPushButton#quiet { background: transparent; border: 0; color: #799083; padding: 5px 7px; font-size: 11px; }
QFrame#metricCard { background: #FFFFFF; border: 1px solid #E1E7DE; border-radius: 10px; }
QLabel#metricTitle { color: #829185; font-size: 11px; }
QLabel#metricValue { color: #325344; font-family: 'Consolas', monospace; font-size: 23px; font-weight: 600; }
QLabel#metricUnit { color: #A0ADA0; font-size: 10px; }
QPlainTextEdit { background: #F4F7F2; color: #335347; border: 1px solid #E1E8DD; border-radius: 8px; padding: 12px; selection-background-color: #CAE5D5; font-family: 'Consolas', 'Microsoft YaHei UI', monospace; font-size: 13px; }
QComboBox { color: #567362; background: #FFFFFF; border: 1px solid #DCE5D8; border-radius: 7px; padding: 7px 10px; min-height: 18px; }
QComboBox::drop-down { border: 0; width: 22px; }
QComboBox QAbstractItemView { background: #FFFFFF; color: #3D5C4C; selection-background-color: #E6F1E1; }
QLabel#error { color: #A56846; background: #FFF2E8; border-radius: 6px; padding: 8px; font-size: 11px; }
QFrame#divider { background: #E6EBE2; border: 0; max-height: 1px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #EEF2EA; width: 6px; margin: 0; border-radius: 3px; }
QScrollBar::handle:vertical { background: #BCD0C0; min-height: 30px; border-radius: 3px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: #EAF0E7; color: #607666; padding: 9px 22px; border-radius: 6px; margin-right: 5px; }
QTabBar::tab:selected { background: #2D8375; color: white; }
"""

LESSONS = (
    "先动手，感受平衡",
    "把感觉，变成可以观察的信息",
    "让你的第一段 Python 推动小车",
)

_fonts_loaded = False


def load_system_fonts():
    """Also expose installed Windows fonts to Qt's offscreen renderer."""
    global _fonts_loaded
    if _fonts_loaded:
        return
    _fonts_loaded = True
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for filename in ("msyh.ttc", "msyhbd.ttc", "consola.ttf"):
            candidate = fonts / filename
            if candidate.is_file():
                QFontDatabase.addApplicationFont(str(candidate))


def label(text, name=None, wrap=False):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    item.setWordWrap(wrap)
    if wrap:
        item.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return item


def divider():
    frame = QFrame()
    frame.setObjectName("divider")
    frame.setFixedHeight(1)
    return frame


def scrollable(panel):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(panel)
    return scroll


class ControlLabWindow(QMainWindow):
    """Compose the experiment, progressive course guide and student workspace."""

    def __init__(self, stage=None, lesson_id=None, data_dir=None):
        super().__init__()
        load_system_fonts()
        self.setWindowTitle("ControlLab · 从直觉到算法")
        self.resize(1380, 860)
        self.setMinimumSize(1080, 680)
        self.lessons = load_lessons()
        self.lesson_by_id = {lesson.lesson_id: lesson for lesson in self.lessons}
        self.progress_store = ProgressStore(root=data_dir)
        self.lesson_session = None
        self._drafts = {}
        self._loading_lesson = False
        self._pending_action = None
        self._episode_reset_pending = False
        self._step_once = False
        self._experiment_rows = []
        self._experiment_saved = False
        self._experiment_code = None
        self._pending_installer = None
        self.updates_dialog = None
        self._replay_dialog = None
        self.sim = TeachingSimulation()
        self.controller = CodeController()
        self.state = list(self.sim.reset(seed=42))
        self.stage = 1
        self.paused = True
        self.code_running = False
        self.last_output = 0.0
        self.has_code_output = False
        self.applied_force = 0.0
        self.target_x = 0.0
        self.fell = False
        self.has_interacted = False
        self._build_ui()
        self.setStyleSheet(STYLES)
        self.draft_timer = QTimer(self)
        self.draft_timer.setSingleShot(True)
        self.draft_timer.setInterval(750)
        self.draft_timer.timeout.connect(self._save_progress)
        initial_lesson = lesson_id or ({1: "L01", 2: "L03", 3: "L05"}[stage] if stage else
                                       self.progress_store.load().get("last_lesson_id", "L01"))
        self.select_lesson(initial_lesson if initial_lesson in self.lesson_by_id else "L01")
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 16)
        content_layout.setSpacing(15)
        self.title = label("", "pageTitle")
        self.title.setWordWrap(True)
        content_layout.addWidget(self.title)

        self.lesson_combo = QComboBox()
        self.lesson_combo.setAccessibleName("选择课程")
        for lesson in self.lessons:
            self.lesson_combo.addItem(f"{lesson.lesson_id}  {lesson.title}", lesson.lesson_id)
        self.lesson_combo.currentIndexChanged.connect(self._lesson_selected)
        content_layout.addWidget(self.lesson_combo)

        body = QHBoxLayout()
        body.setSpacing(20)
        lab_content = QWidget()
        left = QVBoxLayout(lab_content)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(15)
        self.experiment_panel = self._build_experiment()
        left.addWidget(self.experiment_panel, 1)
        self.external_overview = QPlainTextEdit()
        self.external_overview.setReadOnly(True)
        self.external_overview.hide()
        left.addWidget(self.external_overview, 1)
        self.training_panel = TrainingPanel(self.progress_store.root)
        self.training_panel.completed.connect(self._training_completed)
        self.training_panel.operationStarted.connect(self._training_started)
        self.training_panel.replayState.connect(self._replay_state)
        self.training_scroll = scrollable(self.training_panel)
        self.training_scroll.hide()
        left.addWidget(self.training_scroll, 1)
        self.tita_panel = TitaPanel(self.progress_store.root)
        self.tita_panel.inspectionFinished.connect(self._tita_inspected)
        self.tita_panel.runFinished.connect(self._tita_finished)
        self.tita_scroll = scrollable(self.tita_panel)
        self.tita_scroll.hide()
        left.addWidget(self.tita_scroll, 1)
        self.below_stack = QStackedWidget()
        self.below_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.below_stack.addWidget(QWidget())
        self.below_stack.addWidget(self._build_observations())
        left.addWidget(self.below_stack)
        # Keep the cart, flow animation and chart at usable sizes. On short
        # windows the lab scrolls instead of overlapping its minimum-size items.
        self.lab_scroll = scrollable(lab_content)
        self.lab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        body.addWidget(self.lab_scroll, 1)
        self.side_stack = QStackedWidget()
        self.side_stack.setFixedWidth(354)
        lesson_side = QWidget()
        lesson_side_layout = QVBoxLayout(lesson_side)
        lesson_side_layout.setContentsMargins(0, 0, 0, 0)
        self.lesson_panel = LessonPanel()
        self.lesson_panel.eventRaised.connect(self._lesson_event)
        self.lesson_panel.advanceRequested.connect(self._advance_lesson)
        self.lesson_panel.solutionRequested.connect(self._show_solution)
        self.lesson_scroll = scrollable(self.lesson_panel)
        self.lesson_scroll.setMinimumHeight(180)
        lesson_side_layout.addWidget(self.lesson_scroll, 3)
        self.parameters = ControllerPanel()
        self.parameters.codeRequested.connect(self._apply_controller_code)
        self.code_panel = self._build_code_panel()
        self.editor_tabs = QTabWidget()
        self.editor_tabs.addTab(scrollable(self.code_panel), "代码")
        self.editor_tabs.addTab(scrollable(self.parameters), "参数")
        self.signals_panel = SignalsPanel(self.progress_store.root)
        self.signals_panel.completed.connect(self._signal_analysis_completed)
        self.signals_panel.error.connect(self._signal_analysis_error)
        self.signals_tab = self.editor_tabs.addTab(scrollable(self.signals_panel), "信号实验")
        lesson_side_layout.addWidget(self.editor_tabs, 4)
        self.side_stack.addWidget(lesson_side)
        body.addWidget(self.side_stack)
        content_layout.addLayout(body, 1)
        self.status = label("", "status", True)
        self.status.hide()
        content_layout.addWidget(self.status)
        layout.addWidget(content, 1)

    def _build_sidebar(self):
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(194)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(19, 31, 19, 23)
        layout.setSpacing(7)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.addWidget(BrandMark())
        brand.addWidget(label("ControlLab", "brandName"))
        layout.addLayout(brand)
        layout.addSpacing(30)
        self.nav_buttons = []
        sections = (("自由探索", "L01"), ("认识系统", "L03"), ("Python 起步", "L05"),
                    ("传统控制", "L13"), ("强化学习", "L23"), ("走近 TITA", "L30"))
        for number, (title, lesson_id) in enumerate(sections, 1):
            button = QPushButton(f"0{number}    {title}")
            button.setObjectName("nav")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, lid=lesson_id: self.select_lesson(lid))
            self.nav_buttons.append(button)
            layout.addWidget(button)
        layout.addStretch()
        self.evaluation_button = QPushButton("对照实验与报告")
        self.evaluation_button.clicked.connect(self.open_evaluation)
        layout.addWidget(self.evaluation_button)
        self.update_button = QPushButton("软件更新")
        self.update_button.clicked.connect(self.open_updates)
        layout.addWidget(self.update_button)
        return sidebar

    def _build_experiment(self):
        panel = QFrame()
        panel.setObjectName("surface")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(19, 13, 15, 13)
        self.experiment_title = label("倒立摆实验台", "sectionTitle")
        toolbar.addWidget(self.experiment_title)
        toolbar.addStretch()
        self.export_button = QPushButton("保存实验")
        self.export_button.clicked.connect(self.save_experiment)
        toolbar.addWidget(self.export_button)
        layout.addLayout(toolbar)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(15, 0, 15, 10)
        self.pause_button = QPushButton("开始")
        self.pause_button.clicked.connect(self.toggle_pause)
        toolbar.addWidget(self.pause_button)
        self.step_button = QPushButton("单步")
        self.step_button.clicked.connect(self.single_step)
        toolbar.addWidget(self.step_button)
        self.reset_button = QPushButton("重新扶正")
        self.reset_button.clicked.connect(self.reset_experiment)
        toolbar.addWidget(self.reset_button)
        self.challenge_button = QPushButton("开始挑战")
        self.challenge_button.clicked.connect(self.start_challenge)
        toolbar.addWidget(self.challenge_button)
        self.disturbance_button = QPushButton("轻推一下")
        self.disturbance_button.clicked.connect(self.apply_disturbance)
        toolbar.addWidget(self.disturbance_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.playback_combo = QComboBox()
        for caption, speed in (("慢放 ¼ 倍速", .25), ("慢放 ½ 倍速", .5), ("正常播放", 1), ("2 倍速", 2)):
            self.playback_combo.addItem(caption, speed)
        self.playback_combo.setCurrentIndex(2)
        self.playback_combo.currentIndexChanged.connect(self._playback_changed)
        toolbar.addWidget(self.playback_combo)
        self.scenario_combo = QComboBox()
        self.scenario_combo.setAccessibleName("实验初始条件")
        self.scenario_combo.currentIndexChanged.connect(self._scenario_changed)
        layout.addWidget(self.scenario_combo)
        layout.addWidget(divider())
        self.canvas = SimulationCanvas()
        self.canvas.setObjectName("simulation_canvas")
        self.canvas.dragStarted.connect(self.begin_drag)
        self.canvas.dragMoved.connect(self.move_drag)
        self.canvas.dragEnded.connect(self.end_drag)
        layout.addWidget(self.canvas, 1)
        self.flow_indicator = FlowIndicator()
        layout.addWidget(self.flow_indicator)
        return panel

    def _build_observations(self):
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(11)
        metrics = QHBoxLayout()
        metrics.setSpacing(10)
        self.metrics = [MetricCard(*args) for args in (("小车位置", "x", "米 · m"), ("小车速度", "v", "米 / 秒 · m/s"), ("摆杆角度", "θ", "度 · °"), ("摆杆角速度", "ω", "度 / 秒 · °/s"))]
        self.metrics_by_name = dict(zip(("x", "v", "theta", "omega"), self.metrics))
        for name, title, symbol, unit in (("force", "电机推力", "F", "牛顿 · N"),
                                           ("target_v", "目标速度", "v*", "米 / 秒 · m/s"),
                                           ("time", "仿真时间", "t", "秒 · s"),
                                           ("integral", "误差积分", "I", "米 · m")):
            self.metrics_by_name[name] = MetricCard(title, symbol, unit)
        for card in self.metrics_by_name.values():
            metrics.addWidget(card, 1)
        layout.addLayout(metrics)
        chart_frame = QFrame()
        chart_frame.setObjectName("surface")
        chart_layout = QVBoxLayout(chart_frame)
        chart_layout.setContentsMargins(15, 10, 15, 6)
        chart_layout.setSpacing(1)
        bar = QHBoxLayout()
        bar.addWidget(label("让变化留下轨迹", "sectionTitle"))
        bar.addStretch()
        self.pin_button = QPushButton("保留这次曲线")
        self.pin_button.clicked.connect(self._pin_curve)
        bar.addWidget(self.pin_button)
        self.history_button = QPushButton("实验记录")
        self.history_button.clicked.connect(self._open_history)
        bar.addWidget(self.history_button)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("摆杆角度 · °", "theta")
        self.channel_combo.addItem("小车位置 · m", "x")
        self.channel_combo.currentIndexChanged.connect(self.change_channel)
        bar.addWidget(self.channel_combo)
        chart_layout.addLayout(bar)
        self.chart = SignalChart()
        chart_layout.addWidget(self.chart)
        layout.addWidget(chart_frame)
        return holder

    def _guide_item(self, number, title, text):
        row = QHBoxLayout()
        row.setSpacing(12)
        badge = label(str(number), "guideNumber")
        badge.setFixedSize(25, 25)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(8)
        column.addWidget(label(title, "guideTitle", True))
        column.addWidget(label(text, "guideText", True))
        row.addLayout(column, 1)
        return row

    def _build_guide(self, stage):
        frame = QFrame()
        frame.setObjectName("guide")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(23, 23, 23, 21)
        layout.setSpacing(22)
        layout.addWidget(label("一步一步，试着发现", "sectionTitle"))
        layout.addWidget(divider())
        if stage == 1:
            items = (
                ("握住小车", "把鼠标放在绿色小车上，按住左键，轻轻左右移动。"),
                ("接住摆杆", "它向左倒的时候，试试向左推；再试试反方向。哪一种更容易接住它？"),
                ("自由试一试", "快一点、慢一点、小幅度调整……不用急着寻找答案，先熟悉这种感觉。"),
            )
            tip_title = "倒下，也是一次发现"
            tip_text = "点一下「重新扶正」，就能从头再试。这里没有失败惩罚。"
        else:
            items = (
                ("认识四个状态", "x 是小车位置，v 是小车速度；θ 表示摆杆倾斜，ω 表示它转动得多快。"),
                ("停下来，看一看", "暂停实验，看看速度为零时，位置是否一定为零？角度和角速度又有什么不同？"),
                ("找到变化的方向", "向右是正方向；摆杆向右倾斜，角度为正。拖动小车，观察下方曲线。"),
            )
            tip_title = "这就是系统的「观测」"
            tip_text = "控制器根据这些信息决定下一步动作。界面用度显示角度；代码里使用弧度。"
        for i, (title, text) in enumerate(items, 1):
            layout.addLayout(self._guide_item(i, title, text))
        layout.addStretch(1)
        tip = QFrame()
        tip.setObjectName("tip")
        tip_layout = QVBoxLayout(tip)
        tip_layout.setContentsMargins(15, 15, 15, 16)
        tip_layout.setSpacing(8)
        tip_layout.addWidget(label(tip_title, "tipTitle", True))
        tip_layout.addWidget(label(tip_text, "tipText", True))
        layout.addWidget(tip)
        next_button = QPushButton("下一步：认识系统  →" if stage == 1 else "下一步：写下动作  →")
        next_button.setObjectName("primary")
        next_button.clicked.connect(lambda: self.select_stage(stage + 1))
        layout.addWidget(next_button)
        return frame

    def _build_code_panel(self):
        frame = QFrame()
        frame.setObjectName("guide")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 21, 20, 18)
        layout.setSpacing(12)
        self.code_title = label("我的控制代码", "sectionTitle")
        layout.addWidget(self.code_title)
        self.external_note = label("", "guideText", True)
        layout.addWidget(self.external_note)
        mode_row = QHBoxLayout()
        self.output_mode_label = label("输出类型", "smallLabel")
        mode_row.addWidget(self.output_mode_label)
        self.output_mode = QComboBox()
        self.output_mode.addItems(["推力 · N", "目标速度 · m/s"])
        self.output_mode.currentIndexChanged.connect(self.mode_changed)
        mode_row.addWidget(self.output_mode, 1)
        layout.addLayout(mode_row)
        code_header = QHBoxLayout()
        code_header.addStretch()
        self.example_button = QPushButton("载入示例")
        self.example_button.setObjectName("quiet")
        self.example_button.clicked.connect(self.load_example)
        code_header.addWidget(self.example_button)
        layout.addLayout(code_header)
        self.editor = QPlainTextEdit()
        self.editor.setObjectName("code_editor")
        self.editor.setAccessibleName("Python 控制代码编辑器")
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setTabStopDistance(28)
        self.editor.setMinimumHeight(185)
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setPlainText(self.example_code())
        self.editor.textChanged.connect(self._code_edited)
        self.highlighter = PythonHighlighter(self.editor.document())
        layout.addWidget(self.editor, 1)
        controls = QHBoxLayout()
        self.run_button = QPushButton("运行代码")
        self.run_button.setObjectName("primary")
        self.run_button.clicked.connect(self.run_code)
        self.stop_button = QPushButton("停止")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_code)
        controls.addWidget(self.run_button, 1)
        controls.addWidget(self.stop_button)
        layout.addLayout(controls)
        self.next_episode_button = QPushButton("新回合 · 保留代码")
        self.next_episode_button.setToolTip("保持同一个 Python 模块，调用可选 reset()，回到相同初始条件并暂停。")
        self.next_episode_button.clicked.connect(self.new_controller_episode)
        layout.addWidget(self.next_episode_button)
        self.error_label = label("", "error", True)
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.mode_description = label("", "guideText", True)
        layout.addWidget(self.mode_description)
        layout.addWidget(divider())
        self.state_help_title = label("这段代码会得到什么？", "guideTitle")
        self.state_help = label("state['x']   位置 · m\nstate['v']   速度 · m/s\nstate['theta']   角度 · rad\nstate['omega']   角速度 · rad/s\ndt   仿真步长 · 0.02 s", "guideText", True)
        layout.addWidget(self.state_help_title)
        layout.addWidget(self.state_help)
        save = QPushButton("保存练习到我的文档")
        save.clicked.connect(self.save_code)
        layout.addWidget(save)
        return frame

    @staticmethod
    def example_code(velocity=False):
        if velocity:
            return "# 返回目标速度，单位：m/s\n# 试试 0.2、-0.2 和 0.0\ndef control(state, dt):\n    return 0.2\n"
        return "# 返回推力，单位：牛顿 N\n# 正数向右，负数向左\ndef control(state, dt):\n    return 1.0\n"

    def select_stage(self, stage):
        """Keep the original three-stage command line / VS Code entry points."""
        self.select_lesson({1: "L01", 2: "L03", 3: "L05"}[max(1, min(3, int(stage)))])

    def _lesson_selected(self, index):
        if not self._loading_lesson and index >= 0:
            self.select_lesson(self.lesson_combo.itemData(index))

    def select_lesson(self, lesson_id):
        if lesson_id not in self.lesson_by_id:
            raise ValueError(f"没有这节课程：{lesson_id}")
        self._save_progress()
        self._archive_experiment()
        self.chart.clear_reference()
        self.stop_code(show_status=False)
        self.canvas.end_drag()
        lesson = self.lesson_by_id[lesson_id]
        self._loading_lesson = True
        try:
            saved = self.progress_store.get_lesson(lesson_id)
            self.lesson_session = LessonSession(lesson, saved)
            if self.lesson_session.finished and not self.lesson_session.completed:
                missing = next(i for i, step in enumerate(lesson.steps)
                               if step.id not in self.lesson_session.completed_step_ids)
                self.lesson_session.go_to(missing)
            self.stage = 1 if int(lesson_id[1:]) <= 2 else 2 if int(lesson_id[1:]) <= 4 else 3
            number = int(lesson_id[1:])
            group = 0 if number <= 2 else 1 if number <= 4 else 2 if number <= 12 else 3 if number <= 22 else 4 if number <= 29 else 5
            for i, button in enumerate(self.nav_buttons):
                button.setChecked(i == group)
            self.title.setText(lesson.title)
            self.lesson_combo.setCurrentIndex(self.lesson_combo.findData(lesson_id))
            self.lesson_panel.bind(self.lesson_session)
            self.parameters.set_lesson(lesson_id)
            self.editor.blockSignals(True)
            self.editor.setPlainText(self._drafts.get(lesson_id, saved.get("draft_code", lesson.read_template())))
            self.editor.blockSignals(False)
            self.code_panel.setVisible(lesson.editor_kind != "none")
            self.editor_tabs.setVisible(lesson.editor_kind != "none")
            self.editor_tabs.setTabVisible(1, 13 <= number <= 22)
            self.editor_tabs.setCurrentIndex(0)
            self.lesson_scroll.setMaximumHeight(270 if lesson.editor_kind != "none" else 16777215)
            self.output_mode.setCurrentIndex(1 if lesson.input_mode == "velocity_mps" else 0)
            self.output_mode.setEnabled(lesson.editor_kind == "controller")
            executable = lesson.editor_kind == "controller"
            self.code_title.setText("我的控制代码" if executable else "本课实验脚本")
            for widget in (self.output_mode, self.output_mode_label, self.mode_description,
                           self.state_help, self.state_help_title):
                widget.setVisible(executable)
            self.run_button.setVisible(executable)
            self.stop_button.setVisible(executable)
            self.external_note.setText("" if executable or lesson.editor_kind == "none" else
                "本课代码是独立实验脚本。保存后在 VS Code 的对应 Python 环境运行；它不通过下方小车控制函数执行。" +
                ("\n需要：" + "、".join({"rl_runtime": "独立强化学习环境", "tita_runtime": "外部 TITA 仿真环境"}.get(item, item)
                                        for item in lesson.requires) if lesson.requires else ""))
            self.external_note.setVisible(bool(self.external_note.text()))
            self.sim.configure(lesson.scenario_id if lesson.scenario_id != "none" else "upright")
            self.scenario_combo.clear()
            captions = {"upright": "竖直静止", "tilt_right": "略向右倾", "tilt_left": "略向左倾",
                        "moving_right": "小车正在向右移动", "offset_right": "小车偏在右侧",
                        "position_right": "小车在右侧 0.3 米", "position_left": "小车在左侧 0.3 米",
                        "angle_fast_right": "向右倾倒且还在加快", "angle_recovering": "向右倾斜但正在回正",
                        "cart_velocity": "恒定目标速度与持续负载", "cart_velocity_windup": "目标切换与推力饱和",
                        "cart_velocity_unloaded": "恒定目标速度 · 无外部负载",
                        "balance_practice": "固定练习初态", "balance_validation": "开发验证初态",
                        "measurement_theta_noise": "角度测量含噪声", "measurement_omega_noise": "角速度测量含噪声",
                        "robustness_delay": "动作延迟两步 · 40 ms",
                        "observation_delay_1": "观测延迟一步 · 20 ms",
                        "observation_delay_2": "观测延迟两步 · 40 ms",
                        "pole_mass_minus10": "仅杆质量 −10% · 0.09 kg",
                        "pole_mass_plus10": "仅杆质量 +10% · 0.11 kg"}
            for scenario in lesson.scenario_options:
                if scenario != "none":
                    self.scenario_combo.addItem(captions.get(scenario, scenario), scenario)
            self.scenario_combo.setCurrentIndex(self.scenario_combo.findData(lesson.scenario_id))
            self.scenario_combo.setVisible(number >= 2 and lesson.scenario_id != "none")
            is_velocity = lesson.scenario_id.startswith("cart_velocity")
            self.canvas.show_pole = not is_velocity
            self.experiment_title.setText("单车速度实验台" if is_velocity else "倒立摆实验台")
            self.reset_button.setText("归零暂停" if is_velocity else "重新扶正")
            chosen_cards = [name for name in lesson.visible_signals if name in self.metrics_by_name][:4]
            for name, card in self.metrics_by_name.items():
                card.setVisible(name in chosen_cards)
            self.channel_combo.blockSignals(True)
            self.channel_combo.clear()
            for name, caption in (("x", "小车位置 · m"), ("v", "小车速度 · m/s"),
                                  ("theta", "摆杆角度 · °"), ("omega", "摆杆角速度 · °/s"), ("force", "推力 · N"),
                                  ("target_v", "目标速度 · m/s"), ("integral", "误差积分"),
                                  ("requested_force", "请求推力 · N"), ("true_theta", "真实角度 · °"),
                                  ("time", "仿真时间 · s"), ("reward", "本步奖励"),
                                  ("p", "比例分量 · N"), ("d", "微分分量 · N"), ("i", "积分分量 · N")):
                if name in lesson.visible_signals:
                    self.channel_combo.addItem(caption, name)
            self.channel_combo.blockSignals(False)
            self.chart.available_channels = set(lesson.visible_signals)
            self.change_channel(self.channel_combo.currentIndex())
        finally:
            self._loading_lesson = False
        self.below_stack.setCurrentIndex(0 if self.stage == 1 else 1)
        self.below_stack.setFixedHeight(max(270, self.below_stack.minimumSizeHint().height()))
        self.below_stack.setVisible(bool(lesson.visible_signals))
        self.experiment_panel.setVisible(lesson.scenario_id != "none")
        self.external_overview.setVisible(lesson.scenario_id == "none")
        self.external_overview.setPlainText(lesson.summary + "\n\n" + "\n".join(lesson.objectives) + "\n\n" + lesson.notes)
        self.canvas.show_observations = "x" in lesson.visible_signals
        self.canvas.show_force = "force" in lesson.visible_signals or self.stage == 3
        self.canvas.setMinimumHeight(230 if self.stage == 1 else 190)
        self.challenge_button.setVisible(number >= 2)
        self.step_button.setVisible(number >= 3)
        self.disturbance_button.setVisible(number >= 2)
        self.export_button.setVisible(number >= 3)
        self.playback_combo.setVisible(number >= 8)
        self.flow_indicator.setVisible(number == 8)
        self.next_episode_button.setVisible(number == 19)
        self.next_episode_button.setEnabled(False)
        self.editor_tabs.setTabVisible(self.signals_tab, number == 20)
        self.pin_button.setVisible(number >= 10)
        self.history_button.setVisible(number >= 10)
        self.evaluation_button.setVisible(number >= 14)
        training = 25 <= number <= 28
        self.training_scroll.setVisible(training)
        self.training_panel.set_lesson(lesson_id)
        self.tita_scroll.setVisible(number >= 30)
        self.external_overview.hide()
        self.experiment_panel.setVisible(not training and number < 30)
        self.below_stack.setVisible(bool(lesson.visible_signals) and not training and number < 30)
        self.mode_changed()
        self.reset_experiment(emit_event=False)

    def _save_progress(self):
        if self.lesson_session is None or self._loading_lesson:
            return True
        lesson_id = self.lesson_session.lesson.id
        code = self.editor.toPlainText()
        self._drafts[lesson_id] = code
        snapshot = self.lesson_session.snapshot()
        snapshot["draft_code"] = code
        try:
            self.progress_store.save_lesson(lesson_id, snapshot)
        except (OSError, ValueError) as exc:
            self.status.setText(f"进度暂未保存：{exc}")
            self.status.show()
            return False
        return True

    def _lesson_event(self, event, payload=None):
        if self.lesson_session is None or self._loading_lesson:
            return
        self.lesson_session.emit(event, **(payload or {}))
        if event == "hint.opened" and self.lesson_session.step:
            step_id = self.lesson_session.step.id
            current = self.lesson_session.hints_opened.get(step_id, 0)
            self.lesson_session.hints_opened[step_id] = max(current, (payload or {}).get("level", 1))
        self.lesson_panel.refresh()
        self.draft_timer.start()

    def _code_edited(self):
        if not self._loading_lesson:
            self._lesson_event("code.edited")

    def _advance_lesson(self, skip=False):
        if self.lesson_session.finished:
            index = self.lessons.index(self.lesson_session.lesson)
            if index + 1 < len(self.lessons):
                self.select_lesson(self.lessons[index + 1].id)
            return
        self.lesson_session.advance(force=skip)
        self.lesson_panel.refresh()
        self._save_progress()

    def _show_solution(self):
        session = self.lesson_session
        if not session.has_attempt:
            self.status.setText("先做一次自己的尝试，再打开参考答案。")
            self.status.show()
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{session.lesson.id} · 教师参考")
        dialog.resize(620, 520)
        layout = QVBoxLayout(dialog)
        answer = QPlainTextEdit()
        answer.setReadOnly(True)
        answer.setPlainText(session.lesson.reference_answer + "\n\n" + session.lesson.read_solution())
        layout.addWidget(answer)
        close = QPushButton("回到我的实验")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        self._lesson_event("solution.viewed")
        dialog.exec()

    def _scenario_changed(self, index):
        if self._loading_lesson or self.lesson_session is None or index < 0:
            return
        scenario = self.scenario_combo.itemData(index)
        self._archive_experiment()
        self.chart.clear_reference()
        self.sim.configure(scenario)
        self.reset_experiment(emit_event=False)
        self.state = self.sim.start_scenario()
        self._lesson_event("scenario.selected", {"id": scenario})
        self.refresh()

    def _apply_controller_code(self, code):
        # A parameter exercise starts from an explicit saved version of the
        # student's current draft, even if it was never saved manually.
        previous = self.progress_store.save_workspace(self.lesson_session.lesson.id, self.editor.toPlainText(), "before_parameters.py")
        self.stop_code(show_status=False)
        self.editor.setPlainText(code)
        self.editor_tabs.setCurrentIndex(0)
        self.status.setText(f"参数代码已载入。上一版保留在 {previous}；点击「运行代码」开始新的实验。")
        self.status.show()

    def open_evaluation(self):
        self.paused = True
        self.pause_button.setText("继续")
        dialog = QDialog(self)
        dialog.setWindowTitle("ControlLab · 对照实验")
        dialog.resize(880, 640)
        layout = QVBoxLayout(dialog)
        panel = EvaluationPanel(self.progress_store.root)
        panel.completed.connect(lambda report: self._lesson_event("comparison.saved", {"controller": report["controller"]}))
        layout.addWidget(panel)
        try:
            dialog.exec()
        finally:
            panel.shutdown()

    def _playback_changed(self):
        if hasattr(self, "timer"):
            self.timer.setInterval(round(20 / self.playback_combo.currentData()))

    def _pin_curve(self):
        if self.chart.pin_reference("上一次实验"):
            self._archive_experiment()
            self.status.setText("曲线已保留。保持相同初始条件，再运行一次进行叠加观察。")
            self.status.show()

    def _open_history(self):
        self.paused = True
        self.pause_button.setText("继续")
        self._archive_experiment()
        dialog = HistoryDialog(self.progress_store.root, self)
        dialog.referenceRequested.connect(self._reference_recording)
        dialog.restoreRequested.connect(self._restore_recording)
        dialog.exec()

    def _reference_recording(self, recording):
        # Convert recorded SI values exactly as for live samples, without
        # executing any saved policy while browsing the library.
        preview = SignalChart()
        for row in recording.rows:
            preview.append(list(row["observed_state"].values()), row["actuator_force_n"],
                           true_state=list(row["true_state"].values()), time_s=row["simulation_time_s"],
                           target_v=row["target_velocity_mps"], requested_force=row["requested_force_n"],
                           reward=row["reward"], diagnostics=row["diagnostics"])
        self.chart.reference_history = tuple(dict(row) for row in preview.history)
        self.chart.reference_label = f"保存实验 · {recording.report['lesson_id']}"
        self.chart.update()
        preview.deleteLater()
        self.status.setText("已载入对照曲线；先在实验记录中核对初态、模式和参数，鼠标移到曲线上读同一时刻。")
        self.status.show()

    def _restore_recording(self, recording):
        if recording.code is None or recording.report["lesson_id"] not in self.lesson_by_id:
            return
        try:
            self.progress_store.save_workspace(self.lesson_session.lesson.id, self.editor.toPlainText(), "before_restore.py")
        except OSError as exc:
            self.status.setText(f"当前草稿暂未备份，未替换代码：{exc}")
            self.status.show()
            return
        self.select_lesson(recording.report["lesson_id"])
        self.sim.configure_spec(recording.spec)
        self.state = list(self.sim.start_scenario())
        self.target_x = self.state[0]
        self.scenario_combo.blockSignals(True)
        self.scenario_combo.setCurrentIndex(-1)
        self.scenario_combo.setPlaceholderText("已恢复保存实验的精确条件；选择其他场景会替换它")
        self.scenario_combo.blockSignals(False)
        self.editor.setPlainText(recording.code)
        self.output_mode.setCurrentIndex(1 if recording.report["input_modes"] == ["velocity_mps"] else 0)
        self.paused = True
        self.refresh()
        self.status.setText("已恢复代码与原实验条件。当前暂停，点击运行代码才会重新计算新实验。")
        self.status.show()

    def _training_started(self, operation):
        if operation == "train":
            self._lesson_event("training.started")

    def _training_completed(self, result):
        if result.get("operation") == "train" and result.get("type") == "completed":
            self._lesson_event("training.completed", {"path": result.get("path", "")})
            self._lesson_event("artifact.saved", {"path": result.get("path", "")})
        elif result.get("type") == "evaluation":
            self._lesson_event("comparison.saved", {"path": result.get("path", "")})
        elif result.get("type") == "comparison":
            self._lesson_event("comparison.saved", {"path": result.get("path", "")})
        elif result.get("type") == "doctor" and result.get("status") == "ready":
            self._lesson_event("external.verified", {"kind": "training_runtime"})
        elif result.get("type") == "replay_completed":
            self._lesson_event("model.loaded", {"kind": "replay"})

    def _signal_analysis_completed(self, result):
        if self.lesson_session.lesson.id == "L20":
            event = "signal.analysis.completed" if result["kind"] == "noise" else "signal.kick.completed"
            self._lesson_event(event, result)

    def _signal_analysis_error(self, message):
        self.status.setText(f"信号实验未完成：{message}")
        self.status.show()

    def _replay_state(self, state, force):
        if self._replay_dialog is None or not self._replay_dialog.isVisible():
            dialog = QDialog(self)
            dialog.setWindowTitle("策略回放 · 固定验证用例")
            dialog.resize(760, 470)
            layout = QVBoxLayout(dialog)
            canvas = SimulationCanvas()
            canvas.allow_drag = False
            canvas.show_observations = True
            canvas.show_force = True
            layout.addWidget(canvas)
            dialog.finished.connect(lambda: self.training_panel.stop() if self.training_panel._operation == "replay" else None)
            self._replay_dialog, self._replay_canvas = dialog, canvas
            dialog.show()
        self._replay_canvas.set_state(state, force, False, False)

    def _tita_finished(self, result):
        if result.get("status") == "completed" and result.get("mode") != "inspect":
            self._lesson_event("external.verified", {"kind": "tita_run", "report": result})

    def _tita_inspected(self, report):
        if report.get("ready_for_smoke"):
            self._lesson_event("external.verified", {"kind": "inspection", "report": report})

    def open_updates(self):
        if self.updates_dialog is None:
            self.updates_dialog = QDialog(self)
            self.updates_dialog.setWindowTitle("ControlLab · 软件更新")
            self.updates_dialog.resize(760, 460)
            layout = QVBoxLayout(self.updates_dialog)
            self.updates_panel = UpdatesPanel(self.progress_store.root)
            self.updates_panel.readyToInstall.connect(self._request_installation)
            layout.addWidget(self.updates_panel)
        self.updates_dialog.show()
        self.updates_dialog.raise_()

    def _request_installation(self, path):
        self._pending_installer = (path, self.updates_panel.cache_dir)
        self.close()

    def clear_notice(self):
        self.status.clear()
        self.status.setToolTip("")
        self.status.hide()

    def reset_experiment(self, checked=False, *, emit_event=True):
        self._archive_experiment()
        self.stop_code(show_status=False)
        self.canvas.end_drag()
        self.state = list(self.sim.reset(seed=42))
        self._experiment_rows = []
        self._experiment_saved = False
        self._experiment_code = None
        self._pending_action = None
        self._step_once = False
        self.fell = False
        self.paused = True
        self.canvas.allow_drag = self.sim.session.spec.scenario.environment == "cartpole"
        self.applied_force = 0.0
        self.last_output = 0.0
        self.canvas.clear_trail()
        self.chart.clear()
        self.flow_indicator.clear()
        self.error_label.hide()
        self.pause_button.setText("开始")
        self.clear_notice()
        self.refresh()
        if emit_event:
            self._lesson_event("simulation.reset")

    def start_challenge(self):
        self.reset_experiment()
        self.state = self.sim.start_scenario(challenge=True)
        self.paused = False
        self.pause_button.setText("暂停")
        self._lesson_event("simulation.started", {"challenge": True})
        self.refresh()

    def single_step(self):
        if self.fell:
            return
        if not self.code_running and self.lesson_session.lesson.editor_kind == "controller":
            self.run_code()
        self.canvas.end_drag()
        self.paused = True
        self._step_once = True
        self.pause_button.setText("继续")
        self.tick()

    def apply_disturbance(self):
        if self.fell:
            return
        self.sim.add_disturbance(1.0, 5)
        self.paused = False
        self.pause_button.setText("暂停")
        self._lesson_event("disturbance.applied", {"force_n": 1.0, "duration_steps": 5})

    def toggle_pause(self):
        if self.fell:
            self.reset_experiment()
            return
        self.paused = not self.paused
        self.pause_button.setText("继续" if self.paused else "暂停")
        self.clear_notice()
        self._lesson_event("simulation.paused" if self.paused else "simulation.started")
        self.refresh()

    def begin_drag(self, target):
        if self.code_running:
            return
        self.target_x = target
        self.has_interacted = True
        self.paused = False
        self.pause_button.setText("暂停")
        self.clear_notice()
        self._lesson_event("simulation.started")

    def move_drag(self, target):
        self.target_x = target

    def end_drag(self):
        if not self.code_running:
            self.clear_notice()
            self._lesson_event("cart.dragged", {"x": self.state[0], "target_x": self.target_x})

    def change_channel(self, index):
        if hasattr(self, "chart"):
            self.chart.channel = self.channel_combo.itemData(index) or "theta"
            self.chart.update()
            self._lesson_event("signal.selected", {"name": self.chart.channel})

    def mode_changed(self, *_):
        if not hasattr(self, "mode_description"):
            return
        if self.code_running:
            self.stop_code()
        if self.output_mode.currentIndex() == 0:
            limit = self.sim.session.spec.force_limit_n
            self.mode_description.setText(f"推力模式：返回值直接表示牛顿（N），本实验限幅 ±{limit:g} N。正数向右，负数向左。")
        else:
            self.mode_description.setText("速度模式：返回目标速度（m/s）。软件用 F = 8 × (目标速度 − 当前速度) 换算推力，并限制到 ±10 N。速度不会瞬间改变。")
        self._lesson_event("mode.changed", {"mode": "velocity_mps" if self.output_mode.currentIndex() else "force_n"})

    def load_example(self):
        self.stop_code(show_status=False)
        cursor = self.editor.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText(self.lesson_session.lesson.read_template() or self.example_code(self.output_mode.currentIndex() == 1))
        cursor.endEditBlock()
        self.error_label.hide()
        self.clear_notice()

    def run_code(self):
        if self.lesson_session.lesson.editor_kind != "controller":
            return
        self.reset_experiment()
        self.state = self.sim.start_scenario()
        self._experiment_code = self.editor.toPlainText()
        try:
            self.controller.start(self.editor.toPlainText())
        except Exception as exc:
            self.show_code_error(str(exc))
            return
        self.code_running = True
        self.has_code_output = False
        self._pending_action = None
        self.paused = False
        self.canvas.allow_drag = False
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.next_episode_button.setEnabled(True)
        self.editor.setReadOnly(True)
        self.example_button.setEnabled(False)
        self.parameters.set_running(True)
        self.pause_button.setText("暂停")
        self.clear_notice()
        self._lesson_event("code.run")
        self._lesson_event("simulation.started")

    def new_controller_episode(self):
        """L19: repeat the same scenario without reimporting the student module."""
        if not self.code_running or not self.controller.reset_episode():
            return
        self._archive_experiment()
        self._experiment_rows = []
        self._experiment_saved = False
        self._pending_action = None
        self._step_once = False
        self.has_code_output = False
        self.last_output = self.applied_force = 0.0
        self.state = self.sim.start_scenario()
        self.fell = False
        self.paused = True
        self._episode_reset_pending = True
        self.canvas.clear_trail()
        self.chart.clear()
        self.pause_button.setText("继续")
        self.refresh()

    def stop_code(self, checked=False, show_status=True):
        was_running = self.code_running
        self.code_running = False
        self.controller.stop()
        self._episode_reset_pending = False
        self._pending_action = None
        self.last_output = 0.0
        if hasattr(self, "canvas"):
            self.canvas.allow_drag = self.sim.session.spec.scenario.environment == "cartpole"
        if hasattr(self, "run_button"):
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.next_episode_button.setEnabled(False)
            self.editor.setReadOnly(False)
            self.example_button.setEnabled(True)
            self.parameters.set_running(False)
        if was_running:
            self.paused = True
            self.pause_button.setText("继续")
            if show_status:
                self.clear_notice()
                self._lesson_event("code.stopped")

    def show_code_error(self, message):
        self.stop_code(show_status=False)
        self.paused = True
        self.pause_button.setText("继续")
        details = str(message)
        lines = [line.strip() for line in details.splitlines() if line.strip()]
        concise = lines[-1] if lines else "请检查 control(state, dt) 的返回值。"
        if len(concise) > 230:
            concise = concise[:227] + "…"
        self.error_label.setText("这次代码还不能运行：\n" + concise)
        self.error_label.setToolTip(details)
        self.error_label.show()
        self.clear_notice()
        self._lesson_event("code.error", {"message": concise})
        self._archive_experiment(status="error", error=details, include_empty=True)
        self.refresh()

    def tick(self):
        if self.code_running:
            try:
                value = self.controller.poll()
                if self.controller.error:
                    self.show_code_error(self.controller.error)
                    return
                if self._episode_reset_pending and self.controller.ready:
                    self._episode_reset_pending = False
                    self._lesson_event("simulation.reset", {"retained_module": True})
                if value is not None:
                    self.last_output = float(value)
                    self.has_code_output = True
                    self._pending_action = float(value)
                    self.parameters.set_diagnostics(self.controller.last_diagnostics)
            except Exception as exc:
                self.show_code_error(str(exc))
                return
        if self.paused and not self._step_once:
            return
        force = 0.0
        if self.code_running:
            try:
                if self._pending_action is None:
                    self.controller.request(self.state, self.sim.dt, self.sim.context)
                    return
            except Exception as exc:
                self.show_code_error(str(exc))
                return
            force = Action(self._pending_action, "force_n" if self.output_mode.currentIndex() == 0 else "velocity_mps")
            self._pending_action = None
        try:
            before = self.sim.session.true_state.as_dict()
            result = self.sim.step_manual(self.target_x) if self.canvas.dragging and not self.code_running else self.sim.step(force)
        except Exception as exc:
            self.show_code_error(f"仿真实验暂时停止：{exc}")
            return
        self.state = list(result["observation"])
        self.applied_force = float(result["applied_force"])
        record = result["record"]
        record["before_state"] = before
        record["diagnostics"] = dict(self.controller.last_diagnostics) if self.code_running else {}
        self._experiment_rows.append(record)
        self._experiment_saved = False
        single = self._step_once
        self._step_once = False
        if single:
            self.paused = True
        if single or (self.lesson_session.step and "simulation.stepped" in str(self.lesson_session.step.completion)):
            self._lesson_event("simulation.stepped", {"step": self.sim.session.step_index, "time_s": result["elapsed"], "single": single})
        if (result["fell"] or result.get("time_limit", False)) and not self.fell:
            self.fell = True
            self.canvas.end_drag()
            if self.lesson_session.lesson.id != "L19":
                self.stop_code(show_status=False)
            self.canvas.allow_drag = False
            self.paused = True
            self.pause_button.setText("重新开始")
            self.clear_notice()
            self._lesson_event("experiment.finished", {"steps": len(self._experiment_rows), "reason": record["end_reason"]})
            self._archive_experiment(status="finished")
        elif self.code_running and not self.paused:
            # Request the next action only after consuming this one. A slow
            # controller slows playback, never the logical dt or call count.
            self.controller.request(self.state, self.sim.dt, self.sim.context)
        self.chart.append(self.state, self.applied_force, true_state=self.sim.session.true_state.as_tuple(),
                          target_v=record["target_velocity_mps"], time_s=record["simulation_time_s"],
                          requested_force=record["requested_force_n"], reward=record["reward"],
                          diagnostics=self.controller.last_diagnostics if self.code_running else {})
        if self.lesson_session.lesson.id == "L08":
            self.flow_indicator.display_step(list(before.values()), record["requested_force_n"], self.sim.dt)
        self.refresh()

    def refresh(self):
        self.canvas.set_state(self.sim.session.true_state.as_tuple(), self.applied_force, self.paused, self.fell)
        import math

        for metric, value in zip(self.metrics, (self.state[0], self.state[1], math.degrees(self.state[2]), math.degrees(self.state[3]))):
            metric.set_value(value)
        extras = {"force": self.applied_force, "time": self.sim.session.step_index * self.sim.dt,
                  "target_v": self.last_output if self.output_mode.currentIndex() else self.sim.context["target_v"],
                  "integral": self.controller.last_diagnostics.get("integral", 0.0)}
        for key, value in extras.items():
            self.metrics_by_name[key].set_value(value)
        if "integral" not in self.controller.last_diagnostics:
            self.metrics_by_name["integral"].value_label.setText("—")

    def save_code(self):
        try:
            target = self.progress_store.save_workspace(self.lesson_session.lesson.id, self.editor.toPlainText())
            self.status.setText(f"练习已保存：{target}")
            self.status.setToolTip(str(target))
            self.status.show()
            self._lesson_event("code.saved", {"path": str(target)})
            self._save_progress()
        except OSError as exc:
            self.error_label.setText(f"暂时无法保存：{exc}")
            self.error_label.show()

    def _archive_experiment(self, status="paused", error=None, include_empty=False):
        if self._experiment_saved or (not self._experiment_rows and not include_empty):
            return None
        from control_lab.storage.records import save_recording
        try:
            folder = save_recording(self.progress_store.root, self.lesson_session.lesson.id,
                                    self.sim.session.spec, self._experiment_rows,
                                    code=self._experiment_code, status=status, error=error)
            self._experiment_saved = True
            self._lesson_event("experiment.saved", {"path": str(folder)})
            return folder
        except (OSError, ValueError) as exc:
            self.status.setText(f"实验记录暂未保存：{exc}")
            self.status.show()
            return None

    def save_experiment(self):
        folder = self._archive_experiment()
        self.status.setText(f"实验已保存：{folder}" if folder else "当前实验已经保存，或还没有运行步骤。")
        self.status.show()

    def closeEvent(self, event: QCloseEvent):
        self.paused = True
        self.stop_code(show_status=False)
        ready = self.training_panel.shutdown()
        ready = self.signals_panel.shutdown() and ready
        self.tita_panel.shutdown()
        if self.updates_dialog is not None:
            ready = self.updates_panel.shutdown() and ready
        if not ready:
            self.status.setText("正在保存并结束后台操作……")
            self.status.show()
            event.ignore()
            QTimer.singleShot(100, self.close)
            return
        self.timer.stop()
        self.draft_timer.stop()
        self.canvas.end_drag()
        self._archive_experiment()
        saved = self._save_progress()
        if self._pending_installer is not None:
            if not saved:
                self._pending_installer = None
                self.timer.start()
                event.ignore()
                return
            from control_lab.updates.installer import launch_installer
            try:
                launch_installer(*self._pending_installer)
            except Exception as exc:
                self._pending_installer = None
                self.status.setText(f"更新安装未开始：{exc}")
                self.status.show()
                self.timer.start()
                event.ignore()
                return
        self.stop_code(show_status=False)
        self.sim.close()
        event.accept()


def main(argv=None):
    parser = argparse.ArgumentParser(description="ControlLab 桌面教学实验室")
    parser.add_argument("--stage", type=int, choices=[1, 2, 3])
    parser.add_argument("--lesson", help="open a course, for example L13")
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--code-file", type=Path, help="load a control(state, dt) Python file into lesson 3")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--smoke-code-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if getattr(sys, "frozen", False):
        from control_lab import __version__
        from control_lab.updates.installer import confirm_installation
        data_root = args.data_dir or user_data_dir()
        confirm_installation(data_root / "updates" / "downloads", Path(sys.executable).parent, __version__)
    initial_code = None
    if args.code_file:
        try:
            initial_code = args.code_file.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            parser.error(f"无法读取练习文件：{exc}")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ControlLab")
    app.setOrganizationName("ControlLab")
    load_system_fonts()
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setWindowIcon(QIcon(str(Path(__file__).resolve().parents[1] / "resources" / "icon.png")))
    window = ControlLabWindow(stage=3 if initial_code is not None else args.stage,
                              lesson_id=args.lesson, data_dir=args.data_dir)
    if initial_code is not None:
        window.editor.setPlainText(initial_code)
        window.status.setText(f"已加载 {args.code_file.name}。点击「运行代码」开始实验。")
        window.status.show()
    window.show()
    result = {"code": 0}

    def capture_and_finish():
        if args.screenshot:
            args.screenshot.parent.mkdir(parents=True, exist_ok=True)
            if not window.grab().save(str(args.screenshot)):
                result["code"] = 1
        if args.smoke_test or args.smoke_code_test:
            window.close()
            app.quit()

    if args.smoke_code_test:
        # Exercise the actual Windows spawned worker, including frozen builds.
        window.select_stage(3)
        window.editor.setPlainText("def control(state, dt):\n    return 1.25\n")
        window.run_code()
        initial_state = list(window.state)
        deadline = time.monotonic() + 12.0
        smoke_timer = QTimer(window)

        def check_code():
            success = (window.has_code_output and window.last_output == 1.25
                       and window.applied_force == 1.25 and window.state != initial_state)
            failed = bool(window.controller.error) or time.monotonic() >= deadline
            if success or failed:
                smoke_timer.stop()
                result["code"] = 0 if success else 1
                if sys.stdout is not None:
                    print("GUI worker smoke: " + ("PASS" if success else "FAIL"), flush=True)
                capture_and_finish()

        smoke_timer.timeout.connect(check_code)
        smoke_timer.start(20)
    elif args.screenshot or args.smoke_test:
        QTimer.singleShot(800, capture_and_finish)
    app.exec()
    return result["code"]


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    raise SystemExit(main())
