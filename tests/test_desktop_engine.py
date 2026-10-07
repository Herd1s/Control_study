"""Run directly: .venv/Scripts/python.exe tests/test_desktop_engine.py."""

from __future__ import annotations

import math
import multiprocessing
import time
import unittest

from control_lab.desktop.engine import CodeController, TeachingSimulation


class TeachingSimulationTests(unittest.TestCase):
    def setUp(self):
        self.simulation = TeachingSimulation()
        self.addCleanup(self.simulation.close)

    def test_reset_force_clipping_and_state_is_not_exposed(self):
        initial = self.simulation.reset(42)
        self.assertEqual(initial, [0.0, 0.0, 0.0, 0.0])
        initial[0] = 1000
        self.assertEqual(self.simulation.observation[0], 0.0)
        result = self.simulation.step(100)
        self.assertEqual(result["commanded_force"], 100)
        self.assertEqual(result["applied_force"], 10)
        self.assertEqual(result["elapsed"], 0.02)
        self.assertFalse(result["fell"])
        self.assertTrue(all(math.isfinite(value) for value in result["observation"]))
        again = self.simulation.reset(42)
        self.assertEqual(again, [0.0, 0.0, 0.0, 0.0])
        self.assertEqual(again, self.simulation.observation)
        for _ in range(10):
            self.assertEqual(self.simulation.step(0)["observation"], again)
        self.assertEqual(self.simulation.step(-100)["applied_force"], -10)

    def test_disturbance_reaches_teaching_fall_threshold_then_requires_reset(self):
        self.simulation.step(1.0)
        for _ in range(1000):
            result = self.simulation.step(0)
            if result["fell"]:
                break
        self.assertTrue(result["fell"])
        self.assertGreaterEqual(abs(result["observation"][2]), math.radians(80))
        with self.assertRaises(RuntimeError):
            self.simulation.step(0)
        self.simulation.reset()
        self.assertFalse(self.simulation.step(0)["fell"])

    def test_reject_nonfinite_force(self):
        for force in (float("nan"), float("inf"), -float("inf")):
            with self.assertRaises(ValueError):
                self.simulation.step(force)


class CodeControllerTests(unittest.TestCase):
    def setUp(self):
        self.controller = CodeController()
        self.addCleanup(self.controller.stop)

    def until(self, predicate, timeout=12):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.controller.poll()
            if predicate(result):
                return result
            time.sleep(0.005)
        self.fail(f"Timeout waiting for controller; error={self.controller.error!r}")

    def start_ready(self, code):
        self.controller.start(code)
        self.until(lambda _: self.controller.ready or self.controller.error is not None)
        self.assertIsNone(self.controller.error)
        self.assertTrue(self.controller.ready)

    def test_state_mapping_persistent_code_and_no_pending_queue(self):
        self.start_ready(
            "count = 0\n"
            "def control(state, dt):\n"
            "    global count\n"
            "    count += 1\n"
            "    return state['x'] + state['v'] + state['theta'] + state['omega'] + dt + count\n"
        )
        self.controller.request([1, 2, 3, 4], 0.02)
        self.assertTrue(self.controller.busy)
        self.controller.request([100, 100, 100, 100], 0.02)
        self.assertAlmostEqual(self.until(lambda result: result is not None), 11.02)
        self.assertFalse(self.controller.busy)
        self.controller.request([0, 0, 0, 0], 0.02)
        self.assertAlmostEqual(self.until(lambda result: result is not None), 2.02)

    def test_syntax_error_is_reported_without_raising_to_gui(self):
        self.controller.start("def control(:\n    pass")
        self.until(lambda _: self.controller.error is not None)
        self.assertIn("SyntaxError", self.controller.error)
        self.assertIsNone(self.controller.pid)

    def test_episode_reset_keeps_module_and_drops_old_action(self):
        for has_reset in (False, True):
            source = "import time\ncount = 0\n"
            if has_reset:
                source += "def reset():\n    global count\n    count = 0\n"
            source += "def control(state, dt):\n    global count\n    time.sleep(.04)\n    count += 1\n    return count\n"
            self.start_ready(source)
            pid = self.controller.pid
            self.controller.request([0, 0, 0, 0], .02)
            self.assertEqual(self.until(lambda result: result is not None), 1)
            self.controller.request([0, 0, 0, 0], .02)
            self.assertTrue(self.controller.reset_episode())
            while not self.controller.ready and not self.controller.error:
                self.assertIsNone(self.controller.poll())
                time.sleep(.005)
            self.assertIsNone(self.controller.error)
            self.assertEqual(self.controller.pid, pid)
            self.controller.request([0, 0, 0, 0], .02)
            self.assertEqual(self.until(lambda result: result is not None), 1 if has_reset else 3)

    def test_reset_failure_stops_worker_and_reports_original_error(self):
        self.start_ready("count = 0\ndef reset():\n    global count\n    count += 1\n    if count > 1: raise ValueError('reset failed')\ndef control(state, dt):\n    return 0\n")
        self.assertTrue(self.controller.reset_episode())
        self.until(lambda _: self.controller.error is not None)
        self.assertIn("reset failed", self.controller.error)
        self.assertIsNone(self.controller.pid)

    def test_nonfinite_output_is_reported(self):
        self.start_ready("def control(state, dt):\n    return float('nan')")
        self.controller.request([0, 0, 0, 0], 0.02)
        self.until(lambda _: self.controller.error is not None)
        self.assertIn("NaN", self.controller.error)

    def test_top_level_infinite_loop_times_out(self):
        self.controller.start("while True:\n    pass")
        self.until(lambda _: self.controller.error is not None)
        self.assertIn("初始化", self.controller.error)
        self.assertIsNone(self.controller.pid)

    def test_action_infinite_loop_does_not_block_poll_and_times_out(self):
        self.start_ready("def control(state, dt):\n    while True:\n        pass")
        self.controller.request([0, 0, 0, 0], 0.02)
        durations = []
        deadline = time.monotonic() + 2
        while self.controller.error is None and time.monotonic() < deadline:
            start = time.perf_counter()
            self.controller.poll()
            durations.append(time.perf_counter() - start)
            time.sleep(0.005)
        self.assertIsNotNone(self.controller.error)
        self.assertIn("control()", self.controller.error)
        # OS scheduling can preempt Python; median verifies no blocking wait path.
        self.assertLess(sorted(durations)[len(durations) // 2], 0.02)
        self.assertIsNone(self.controller.pid)

    def test_stop_reaps_worker_and_restart_clears_previous_error(self):
        self.start_ready("def control(state, dt):\n    return 1")
        old_pid = self.controller.pid
        self.controller.stop()
        self.assertIsNone(self.controller.pid)
        self.until(lambda _: old_pid not in {child.pid for child in multiprocessing.active_children()})
        self.controller.start("broken syntax @")
        self.until(lambda _: self.controller.error is not None)
        self.start_ready("def control(state, dt):\n    return 2")
        self.controller.request([0, 0, 0, 0], 0.02)
        self.assertEqual(self.until(lambda result: result is not None), 2)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    unittest.main(verbosity=2)
