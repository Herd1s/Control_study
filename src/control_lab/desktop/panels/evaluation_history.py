"""Read-only formal case playback: recorded truth, never a running controller."""
import json

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSlider, QTabWidget, QVBoxLayout, QWidget)

from control_lab.desktop.ui_widgets import SignalChart, SimulationCanvas
from control_lab.evaluation.report_io import load_evaluation
from ._dialogs import scrolling_body


class EvaluationReportDialog(QDialog):
    caseViewed = Signal(dict)
    def __init__(self, report_path, parent=None):
        super().__init__(parent)
        self.record = load_evaluation(report_path)
        self.rows = ()
        self.comparison = None
        self.comparison_rows = ()
        self.setWindowTitle("评价报告 · 逐回合回放")
        layout = scrolling_body(self, parent)
        self.notice = QLabel("画布与曲线使用动作后的真实状态；推力作用于刚结束的一步。动作前的观测在下方单独标注。回放不执行代码。")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.case_box = QComboBox()
        for case in self.record.report["episodes"]:
            self.case_box.addItem(f"{case['case_id']} · {'通过' if case['completed'] else case['end_reason']} · {case['episode_steps']} 步", case["case_id"])
        layout.addWidget(self.case_box)
        self.tabs = QTabWidget()
        page = QWidget()
        visual = QVBoxLayout(page)
        self.canvas = SimulationCanvas()
        self.canvas.allow_drag = False
        self.canvas.setMinimumHeight(150)
        canvases = QHBoxLayout()
        canvases.addWidget(self.canvas, 1)
        self.comparison_canvas = SimulationCanvas()
        self.comparison_canvas.allow_drag = False
        self.comparison_canvas.setMinimumHeight(150)
        self.comparison_canvas.hide()
        canvases.addWidget(self.comparison_canvas, 1)
        visual.addLayout(canvases, 1)
        self.channels = QComboBox()
        for title, key in (("真实摆角 / °", "theta"), ("位置 / m", "x"), ("速度 / m/s", "v"),
                           ("执行与请求推力 / N", "force"), ("P / N", "p"), ("D / N", "d"), ("I / N", "i")):
            self.channels.addItem(title, key)
        self.channels.currentIndexChanged.connect(self._channel)
        visual.addWidget(self.channels)
        self.chart = SignalChart()
        self.chart.LABELS = {**self.chart.LABELS, "theta": ("真实角度", "°")}
        self.chart.available_channels = {"requested_force"}
        self.chart.setMinimumHeight(140)
        visual.addWidget(self.chart)
        self.observation_label = QLabel()
        self.observation_label.setWordWrap(True)
        visual.addWidget(self.observation_label)
        self.comparison_label = QLabel()
        self.comparison_label.setWordWrap(True)
        visual.addWidget(self.comparison_label)
        self.tabs.addTab(page, "状态与推力")
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.tabs.addTab(self.details, "详细指标 · 协议 · 代码")
        layout.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.play_pause)
        controls.addWidget(self.play_button)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self.show_frame)
        controls.addWidget(self.slider, 1)
        self.time_label = QLabel("0.00 s")
        controls.addWidget(self.time_label)
        layout.addLayout(controls)
        self.compare_button = QPushButton("添加同条件对照报告")
        self.compare_button.clicked.connect(self.choose_comparison)
        layout.addWidget(self.compare_button)
        self.timer = QTimer(self)
        self.timer.setInterval(round(self.record.protocol.definition["physics"]["dt_s"]*1000))
        self.timer.timeout.connect(self.next_frame)
        self.case_box.currentIndexChanged.connect(self.select_case)
        self.select_case()

    def select_case(self, *_):
        self.timer.stop()
        self.play_button.setText("播放")
        self.chart.clear()
        self.chart.clear_reference()
        self.rows = ()
        self.comparison_rows = ()
        case_id = self.case_box.currentData()
        if not case_id:
            self.play_button.setEnabled(False)
            self.notice.setText("评价尚未保存任何回合。")
            return
        try:
            self.rows = self.record.case_rows(case_id)
            episode = next(entry for entry in self.record.report["episodes"] if entry["case_id"] == case_id)
            if self.comparison is not None:
                self.comparison_rows = self.comparison.case_rows(case_id)
                for row in self.comparison_rows:
                    true = [row["true_"+key] for key in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")]
                    self.chart.append(true, row["actuator_force_n"], true_state=true, time_s=row["time_s"],
                                      requested_force=row["requested_force_n"], reward=row["reward"], diagnostics=row["diagnostics"])
                self.chart.pin_reference(self.comparison.report["controller"])
                self.chart.clear()
            for row in self.rows:
                true = [row["true_"+key] for key in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")]
                self.chart.append(true, row["actuator_force_n"], true_state=true, time_s=row["time_s"],
                                  requested_force=row["requested_force_n"], reward=row["reward"], diagnostics=row["diagnostics"])
            details = {"回合完整指标": episode, "总体指标": self.record.report["aggregate"],
                       "报告状态": self.record.report.get("status", "completed"),
                       "协议": self.record.protocol.definition, "控制器快照": self.record.snapshot}
            if self.comparison is not None:
                details["对照回合"] = next(entry for entry in self.comparison.report["episodes"] if entry["case_id"] == case_id)
                details["对照控制器快照"] = self.comparison.snapshot
            self.details.setPlainText(json.dumps(details, ensure_ascii=False, indent=2))
            self.slider.setRange(0, max(0, max(len(self.rows), len(self.comparison_rows))-1))
            self.slider.setValue(0)
            self.play_button.setEnabled(bool(self.rows or self.comparison_rows))
            if self.rows or self.comparison_rows:
                self.show_frame(0)
            else:
                self.canvas.set_state(episode["initial_state"], 0, True, False)
                self.observation_label.setText("此回合在首个物理步之前发生错误，没有可回放的动作；详细指标保留错误。")
                self.time_label.setText("0.00 s")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.notice.setText(f"轨迹无法读取：{exc}")
            self.play_button.setEnabled(False)

    def _channel(self, *_):
        self.chart.channel = self.channels.currentData()
        self.chart.update()

    def show_frame(self, index):
        if not self.rows and not self.comparison_rows:
            return
        dt = self.record.protocol.definition["physics"]["dt_s"]
        time_s = (index+1)*dt
        def render(record, rows, canvas):
            if index < len(rows):
                row = rows[index]
                canvas.set_state([row["true_"+key] for key in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")],
                                 row["actuator_force_n"], True, row["terminated"])
                return (f"{record.report['controller']}：动作前 {time_s-dt:.2f}s 观测 θ={row['observed_theta_rad']:.4f} rad、"
                        f"ω={row['observed_omega_rad_s']:.4f} rad/s；动作后 x={row['true_x_m']:.4f} m，"
                        f"请求/实际力={row['requested_force_n']:.3f}/{row['actuator_force_n']:.3f} N")
            if rows:
                row = rows[-1]
                canvas.set_state([row["true_"+key] for key in ("x_m", "v_m_s", "theta_rad", "omega_rad_s")],
                                 0., True, row["terminated"])
            else:
                episode = next(entry for entry in record.report["episodes"] if entry["case_id"] == self.case_box.currentData())
                canvas.set_state(episode["initial_state"], 0., True, False)
            return f"{record.report['controller']} 已在 {len(rows)*dt:.2f} s 结束；此时无后续样本，画布仅停留在最后记录。"
        self.observation_label.setText(render(self.record, self.rows, self.canvas))
        if self.comparison is not None:
            self.comparison_label.setText(render(self.comparison, self.comparison_rows, self.comparison_canvas))
        self.chart.cursor_time = time_s
        self.chart.update()
        self.time_label.setText(f"{time_s:.2f} s")
        if self.isVisible():
            self._emit_viewed()

    def _emit_viewed(self):
        case_id = self.case_box.currentData()
        if case_id is not None and self.rows:
            case = next(entry for entry in self.record.report["episodes"] if entry["case_id"] == case_id)
            self.caseViewed.emit({"case_id": case_id, "completed": case["completed"],
                                 "steps": len(self.rows), "report": str(self.record.folder / "report.json"),
                                 "time_s": (self.slider.value()+1)*self.record.protocol.definition["physics"]["dt_s"],
                                 "compared": self.comparison is not None,
                                 "comparison_report": str(self.comparison.folder / "report.json") if self.comparison else None})

    def showEvent(self, event):
        super().showEvent(event)
        self._emit_viewed()

    def choose_comparison(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择同协议对照报告", str(self.record.folder.parent), "评价报告 (report.json)")
        if path:
            try:
                self.set_comparison(path)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.notice.setText(f"无法对照：{exc}")

    def set_comparison(self, path):
        from control_lab.evaluation.compare import compare_reports
        comparison = load_evaluation(path, require_complete=True)
        compare_reports([self.record.report, comparison.report])
        self.comparison = comparison
        self.comparison_canvas.show()
        self.notice.setText("左右画布对应两份同条件报告；曲线使用同一时间轴。提前结束的方案只停留最后状态，后续不补造样本。")
        self.select_case()

    def play_pause(self):
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        elif self.rows or self.comparison_rows:
            if self.slider.value() == self.slider.maximum():
                self.slider.setValue(0)
            self.timer.start()
            self.play_button.setText("暂停")

    def next_frame(self):
        if self.slider.value() == self.slider.maximum():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            self.slider.setValue(self.slider.value()+1)

    def done(self, result):
        self.timer.stop()
        super().done(result)
