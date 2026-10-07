"""Cross-layer checks: real Qt events, child Python and saved course artifacts."""

import json
import math
import multiprocessing
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from control_lab.desktop.app import ControlLabWindow


class CourseDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.folder = TemporaryDirectory()
        self.window = ControlLabWindow(data_dir=self.folder.name)
        self.window.show()
        QTest.qWait(20)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.folder.cleanup()

    def wait_for(self, predicate, timeout=12):
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            if predicate():
                return
            QTest.qWait(10)
        self.fail(self.window.error_label.text() or "Timed out")

    def test_every_lesson_loads_with_its_real_model_and_editor_contract(self):
        window = self.window
        for lesson in window.lessons:
            with self.subTest(lesson=lesson.id):
                window.select_lesson(lesson.id)
                self.assertEqual(window.lesson_session.lesson.id, lesson.id)
                self.assertEqual(window.editor.toPlainText(), lesson.read_template())
                self.assertEqual(window.run_button.isVisible(), lesson.editor_kind == "controller")
                self.assertTrue(window.paused)
                self.assertFalse(window.code_running)
                if lesson.id in ("L17", "L18"):
                    self.assertFalse(window.canvas.show_pole)
                    self.assertEqual(window.sim.session.spec.scenario.environment, "cart_velocity")
                if lesson.id in ("L30", "L31", "L32"):
                    self.assertFalse(window.experiment_panel.isVisible())

    def test_grabbing_the_cart_edge_does_not_move_its_center(self):
        window = self.window
        pos = window.canvas.cart_rect().center().toPoint() + QPoint(26, 0)
        QTest.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=pos)
        QTest.qWait(100)
        self.assertEqual(window.target_x, 0)
        self.assertEqual(window.state, [0, 0, 0, 0])
        QTest.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=pos)

    def test_slow_controller_has_one_reset_and_one_action_per_step_even_across_pause(self):
        window = self.window
        window.select_lesson("L09")
        window.editor.setPlainText(
            "import time\ncount = 999\n"
            "def reset():\n    global count\n    count = 0\n"
            "def control(state, dt):\n    global count\n    time.sleep(0.055)\n"
            "    count += 1\n    return count * 0.001\n")
        window.run_code()
        self.wait_for(lambda: len(window._experiment_rows) >= 4)
        window.toggle_pause()
        frozen_count = len(window._experiment_rows)
        QTest.qWait(120)
        self.assertEqual(len(window._experiment_rows), frozen_count)
        window.toggle_pause()
        self.wait_for(lambda: len(window._experiment_rows) >= 8)
        window.stop_code()
        for number, row in enumerate(window._experiment_rows, 1):
            self.assertAlmostEqual(row["requested_force_n"], number * .001)
            self.assertAlmostEqual(row["simulation_time_s"], number * .02)
        self.assertEqual(window.sim.session.step_index, len(window._experiment_rows))

    def test_navigation_saves_the_original_experiment_and_keeps_each_draft(self):
        window = self.window
        window.select_lesson("L05")
        source = "def control(state, dt):\n    return 1.234\n"
        window.editor.setPlainText(source)
        window.run_code()
        self.wait_for(lambda: len(window._experiment_rows) >= 3)
        window.select_lesson("L13")
        reports = list((Path(self.folder.name) / "runs").glob("*/report.json"))
        self.assertEqual(len(reports), 1)
        report = json.loads(reports[0].read_text(encoding="utf-8"))
        self.assertEqual(report["lesson_id"], "L05")
        self.assertEqual(report["spec"]["scenario"]["scenario_id"], "upright")
        self.assertEqual(reports[0].with_name("controller_snapshot.py").read_text(encoding="utf-8"), source)
        window.select_lesson("L05")
        self.assertEqual(window.editor.toPlainText(), source)

    def test_l19_new_episode_calls_reset_in_same_module_and_preserves_pause(self):
        window = self.window
        window.select_lesson("L19")
        for has_reset in (False, True):
            source = "count = 0\n"
            if has_reset:
                source += "def reset():\n    global count\n    count = 0\n"
            source += "def control(state, dt):\n    global count\n    count += 1\n    return count * .001\n"
            window.editor.setPlainText(source)
            window.run_code()
            self.wait_for(lambda: len(window._experiment_rows) >= 4)
            old_count, pid = len(window._experiment_rows), window.controller.pid
            window.next_episode_button.click()
            self.wait_for(lambda: window.controller.ready)
            QTest.qWait(60)
            self.assertEqual(window.sim.session.step_index, 0)
            self.assertEqual(window.controller.pid, pid)
            self.assertTrue(window.paused)
            window.single_step()
            self.wait_for(lambda: window.sim.session.step_index == 1)
            force = window._experiment_rows[0]["requested_force_n"]
            if has_reset:
                self.assertAlmostEqual(force, .001)
            else:
                self.assertGreater(force, old_count * .001)
            window.stop_code()

    def test_course_step_and_source_survive_reopening(self):
        window = self.window
        window.lesson_panel.acknowledge.click()
        self.assertTrue(window.lesson_session.can_advance)
        window.lesson_panel.next_button.click()
        self.assertEqual(window.lesson_session.step_index, 1)
        window.close()
        window.deleteLater()
        self.app.processEvents()
        self.window = ControlLabWindow(data_dir=self.folder.name)
        self.window.show()
        self.assertEqual(self.window.lesson_session.step_index, 1)
        self.assertEqual(self.window.lesson_session.completed_step_ids, ["step_01"])

    def test_canvas_uses_true_physics_while_observations_include_noise(self):
        window = self.window
        window.select_lesson("L20")
        index = window.scenario_combo.findData("measurement_theta_noise")
        self.assertGreaterEqual(index, 0)
        window.scenario_combo.setCurrentIndex(index)
        window.start_challenge()
        QTest.qWait(80)
        window.toggle_pause()
        true = list(window.sim.session.true_state)
        self.assertEqual(window.canvas.state, true)
        self.assertNotEqual(window.state[2], true[2])
        self.assertTrue(all(math.isfinite(x) for x in window.state))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main()
