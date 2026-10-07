"""Real widget interactions: .venv/Scripts/python.exe tests/test_desktop_ui.py.

Qt runs offscreen, but mouse/button handlers, physics, GUI timers and student
worker processes all run normally. No simulation or worker is replaced by a mock.
"""

from __future__ import annotations

import math
import multiprocessing
import os
import time
import unittest
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from control_lab.desktop.app import ControlLabWindow


class DesktopInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.data = TemporaryDirectory()
        self.addCleanup(self.data.cleanup)
        self.window = ControlLabWindow(data_dir=self.data.name)
        self.window.show()
        QTest.qWait(30)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()

    def wait_until(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            QTest.qWait(10)
        self.fail(f"UI wait timed out: {self.window.status.text()} / {self.window.error_label.text()}")

    def click(self, widget):
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def enter_code(self, source):
        if self.window.stage != 3:
            self.click(self.window.nav_buttons[2])
        self.window.editor.setPlainText(source)
        self.click(self.window.run_button)

    def test_drag_is_physically_coupled_assistance_and_release_removes_force(self):
        window = self.window
        canvas = window.canvas
        initial_x = window.state[0]
        cart_center = canvas.cart_rect().center().toPoint()
        target = cart_center + QPoint(80, 0)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=cart_center)
        QTest.mouseMove(canvas, target)
        self.assertTrue(canvas.dragging)
        self.assertFalse(window.paused)
        self.assertGreater(window.target_x, initial_x)
        QTest.qWait(100)
        self.assertTrue(math.isfinite(window.applied_force))
        self.assertGreater(window.applied_force, 0)
        self.assertGreater(window.state[0], initial_x)
        self.assertGreaterEqual(window.target_x - window.state[0], 0)
        self.assertLessEqual(abs(window.state[1]), 4)
        self.assertNotEqual(window.state[2], 0)
        self.assertTrue(all(row["input_mode"] == "manual_position_assist" for row in window._experiment_rows))

        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=target)
        self.wait_until(lambda: window.applied_force == 0, timeout=1)
        self.assertFalse(canvas.dragging)
        # Releasing removes input, while the physical cart retains momentum.
        self.assertGreater(window.state[1], 0)
        self.click(window.reset_button)
        self.assertTrue(window.paused)
        self.assertEqual(window.state, [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(canvas.state, window.state)
        self.assertEqual(window.applied_force, 0)
        QTest.qWait(60)
        self.assertEqual(window.state, [0.0, 0.0, 0.0, 0.0])

    def test_navigation_pause_and_reset_restore_a_fresh_experiment(self):
        window = self.window
        initial = window.state.copy()
        self.assertTrue(window.paused)
        self.assertFalse(window.canvas.show_observations)
        self.click(window.nav_buttons[1])
        self.assertEqual(window.stage, 2)
        self.assertTrue(window.nav_buttons[1].isChecked())
        self.assertTrue(window.canvas.show_observations)
        self.assertEqual(window.below_stack.currentIndex(), 1)

        self.click(window.pause_button)
        self.wait_until(lambda: len(window.chart.history) >= 3)
        self.click(window.pause_button)
        paused_state = window.state.copy()
        QTest.qWait(60)
        self.assertEqual(window.state, paused_state)
        self.click(window.reset_button)
        self.assertEqual(window.state, initial)
        self.assertEqual(len(window.chart.history), 0)
        self.assertTrue(window.paused)
        self.assertEqual(window.applied_force, 0)
        self.click(window.nav_buttons[2])
        self.assertEqual(window.stage, 3)
        self.assertTrue(window.editor.isVisible())
        self.assertTrue(window.canvas.show_force)

    def test_force_code_moves_cart_and_stop_restores_editing(self):
        window = self.window
        self.enter_code("def control(state, dt):\n    return 2.0\n")
        initial_x = window.state[0]
        self.assertTrue(window.editor.isReadOnly())
        self.wait_until(lambda: len(window.chart.history) >= 3)
        self.assertEqual(window.last_output, 2)
        self.assertEqual(window.applied_force, 2)
        self.assertGreater(window.state[0], initial_x)
        self.click(window.stop_button)
        self.assertFalse(window.code_running)
        self.assertTrue(window.paused)
        self.assertFalse(window.editor.isReadOnly())
        self.assertIsNone(window.controller.pid)

    def test_velocity_code_accelerates_toward_target_instead_of_setting_velocity(self):
        window = self.window
        self.click(window.nav_buttons[2])
        # Change the real combo box using its keyboard interaction.
        window.output_mode.setFocus()
        QTest.keyClick(window.output_mode, Qt.Key.Key_Down)
        self.assertEqual(window.output_mode.currentIndex(), 1)
        initial_velocity = window.state[1]
        self.enter_code("def control(state, dt):\n    return 0.2\n")
        self.wait_until(lambda: len(window.chart.history) >= 2)
        self.assertAlmostEqual(window.last_output, 0.2)
        self.assertGreater(window.applied_force, 0.2)
        self.assertLess(window.applied_force, 10)
        self.assertGreater(window.state[1], initial_velocity)
        self.assertLess(window.state[1], 0.2)
        self.assertNotAlmostEqual(window.applied_force, window.last_output)

    def test_bad_or_nonterminating_code_reports_error_while_ui_timers_keep_running(self):
        window = self.window
        pulses = []
        heartbeat = QTimer(window)
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: pulses.append(time.monotonic()))
        heartbeat.start()
        for source, message in (
            ("def control(:\n    return 1", "SyntaxError"),
            ("def control(state, dt):\n    while True:\n        pass", "超过"),
        ):
            with self.subTest(message=message):
                pulses.clear()
                self.enter_code(source)
                self.wait_until(lambda: window.error_label.isVisible())
                self.assertIn(message, window.error_label.text())
                self.assertFalse(window.code_running)
                self.assertTrue(window.paused)
                self.assertFalse(window.editor.isReadOnly())
                self.assertIsNone(window.controller.pid)
                self.assertGreater(len(pulses), 5)
                self.assertLess(max(b - a for a, b in zip(pulses, pulses[1:])), 0.25)
                self.click(window.reset_button)
                self.assertFalse(window.error_label.isVisible())
        heartbeat.stop()

    def test_changing_lesson_stops_a_live_busy_worker(self):
        window = self.window
        self.enter_code("def control(state, dt):\n    while True:\n        pass")
        self.wait_until(lambda: window.controller.ready and window.controller.busy)
        worker_pid = window.controller.pid
        self.assertIsNotNone(worker_pid)
        self.click(window.nav_buttons[1])
        self.assertEqual(window.stage, 2)
        self.assertFalse(window.code_running)
        self.assertTrue(window.paused)
        self.assertTrue(window.canvas.allow_drag)
        self.assertIsNone(window.controller.pid)
        self.wait_until(
            lambda: worker_pid not in {process.pid for process in multiprocessing.active_children()},
            timeout=2,
        )


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main(verbosity=2)
