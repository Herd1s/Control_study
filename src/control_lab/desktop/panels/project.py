"""Select explicit reports and export the L22 reproducible project bundle."""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from control_lab.evaluation.project import export_project


class ProjectPanel(QWidget):
    exported = Signal(dict)
    error = Signal(str)

    def __init__(self, data_dir, parent=None):
        super().__init__(parent)
        self.data_dir = Path(data_dir)
        layout = QVBoxLayout(self)
        note = QLabel("选择至少三个不同控制方案的完整练习/验证报告。项目将保存 README、参数、协议、源码和轨迹；只包含你选择的文件。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.title_edit = QLineEdit("我的倒立摆控制项目")
        layout.addWidget(self.title_edit)
        self.reports = QListWidget()
        layout.addWidget(self.reports, 1)
        actions = QHBoxLayout()
        self.add_button = QPushButton("添加报告")
        self.add_button.clicked.connect(self.browse_reports)
        self.export_button = QPushButton("导出项目 ZIP")
        self.export_button.clicked.connect(self.choose_destination)
        actions.addWidget(self.add_button)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)
        self.reflection = QPlainTextEdit()
        self.reflection.setPlaceholderText("写下预测、结果、参数选择与失败原因，将一起进入 README。")
        self.reflection.setMaximumHeight(130)
        layout.addWidget(self.reflection)
        self.status = QLabel("勾选同一组用例的报告；不同协议或不完整记录会被拒绝。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        for path in sorted((self.data_dir / "evaluations").glob("*/report.json"), reverse=True):
            self.add_report(path, checked=False)

    def add_report(self, path, *, checked=True):
        path = Path(path).resolve()
        if any(self.reports.item(index).data(Qt.ItemDataRole.UserRole) == str(path) for index in range(self.reports.count())):
            return
        item = QListWidgetItem(path.parent.name)
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        item.setToolTip(str(path))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.reports.addItem(item)

    def browse_reports(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "添加完整评价报告", str(self.data_dir), "评价报告 (report.json)")
        for path in paths:
            self.add_report(path)

    def choose_destination(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出课程项目", str(self.data_dir / "exports" / "control-project.zip"), "ZIP (*.zip)")
        if path:
            self.export_to(path)

    def export_to(self, path):
        selected = [self.reports.item(index).data(Qt.ItemDataRole.UserRole) for index in range(self.reports.count())
                    if self.reports.item(index).checkState() == Qt.CheckState.Checked]
        try:
            result = export_project(selected, path, title=self.title_edit.text(), reflection=self.reflection.toPlainText())
            self.status.setText(f"已导出 {result['method_count']} 种方法、{result['file_count']} 个文件：{result['path']}")
            self.exported.emit(result)
            return result
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.status.setText(f"项目尚未导出：{exc}")
            self.error.emit(str(exc))
            return None
