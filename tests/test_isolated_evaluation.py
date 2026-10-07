import csv
import json
import os
import subprocess
import sys
import time

import pytest

from control_lab.core.types import State
from control_lab.evaluation import compare_reports, evaluate, load_protocol
from control_lab.evaluation.batch import controller_identity
from control_lab.inputs.isolated import IsolatedControllerAdapter, ControllerTimeoutError


def test_source_is_not_imported_for_identity_and_reset_runs_once_per_episode(tmp_path):
    marker = tmp_path / "imported.txt"
    code = f"""from pathlib import Path
Path({str(marker)!r}).write_text('loaded')
resets = 0
def reset():
    global resets
    resets += 1
def control(state, dt):
    return resets + state['target_v']
def diagnostics():
    return {{'p_n': resets, 'frozen': False}}
"""
    controller = IsolatedControllerAdapter(code)
    try:
        before = controller_identity(controller)[0]
        assert not marker.exists()
        controller.reset()
        pid = controller.pid
        assert marker.read_text() == "loaded"
        assert controller.act(State(), .02, {"target_v": .3}) == 1.3
        assert controller.diagnostics == {"p_n": 1., "frozen": False}
        controller.reset()
        assert controller.pid == pid
        assert controller.act(State(), .02, {"target_v": .3}) == 2.3
        assert controller_identity(controller)[0] == before
    finally:
        controller.close()


@pytest.mark.parametrize("code,phase", [
    ("while True: pass", "initialize"),
    ("def reset():\n    while True: pass\ndef control(state, dt): return 0", "initialize"),
    ("def control(state, dt):\n    while True: pass", "control"),
    ("def control(state, dt): return 0\ndef diagnostics():\n    while True: pass", "control"),
])
def test_top_reset_action_and_diagnostics_are_bounded(code, phase):
    controller = IsolatedControllerAdapter(code, execution_timeout=.1)
    started = time.monotonic()
    try:
        with pytest.raises(ControllerTimeoutError) as caught:
            controller.reset()
            controller.act(State(), .02)
        assert caught.value.phase == phase
        assert time.monotonic() - started < 8
    finally:
        controller.close()


def test_later_reset_timeout_restarts_worker_for_next_case():
    source = """count = 0
def reset():
    global count
    count += 1
    if count == 2:
        while True: pass
def control(state, dt): return count
"""
    controller = IsolatedControllerAdapter(source, execution_timeout=.1)
    try:
        controller.reset()
        pid = controller.pid
        assert controller.act(State(), .02) == 1
        with pytest.raises(ControllerTimeoutError, match="reset"):
            controller.reset()
        controller.reset()
        assert controller.pid != pid and controller.worker_generation == 2
        assert controller.act(State(), .02) == 1
    finally:
        controller.close()


def test_initialization_failure_keeps_all_cases_and_source(tmp_path):
    report = evaluate(lambda: IsolatedControllerAdapter("while True: pass", execution_timeout=.1),
                      load_protocol(split="practice"), output_dir=tmp_path / "evaluation")
    assert report["is_complete"] and report["status"] == "completed"
    assert report["aggregate"]["controller_errors"] == report["requested_episodes"] == 5
    assert {case["worker_generation"] for case in report["episodes"]} == {1}
    assert all(case["controller_error"]["phase"] == "initialize" for case in report["episodes"])
    assert all(case["episode_steps"] == 0 for case in report["episodes"])
    assert (tmp_path / "evaluation/controller_snapshot.json").is_file()
    assert len(list((tmp_path / "evaluation").glob("*/trajectory.csv"))) == 5


def test_function_diagnostics_saved_and_cancellation_keeps_completed_cases(tmp_path):
    output = tmp_path / "evaluation"
    cancelled = False
    def progress(done, total, episode):
        nonlocal cancelled
        disk = json.loads((output / "report.json").read_text())
        assert len(disk["episodes"]) == done == 1
        assert disk["status"] == "running"
        cancelled = True
    source = "def control(state, dt): return 0\ndef diagnostics(): return {'p_n': 0, 'frozen': True}"
    result = evaluate(lambda: IsolatedControllerAdapter(source), load_protocol(split="practice"),
                      output_dir=output, progress_callback=progress, cancel_requested=lambda: cancelled)
    assert result["status"] == "cancelled" and not result["is_complete"]
    assert result["aggregate"]["episodes"] == 1 and result["requested_episodes"] == 5
    rows = list(csv.DictReader((output / result["episodes"][0]["trajectory_file"]).open()))
    assert rows[0]["controller_p_n"] == "0.0" and rows[0]["controller_frozen"] == "True"
    with pytest.raises(ValueError, match="cancelled"):
        compare_reports([result, result])


def test_action_failure_restarts_worker_and_retains_each_partial_trajectory(tmp_path):
    source = """n = 0
def control(state, dt):
    global n
    n += 1
    if n == 2: raise ValueError('second action fails')
    return 0
"""
    result = evaluate(lambda: IsolatedControllerAdapter(source), load_protocol(split="practice"),
                      output_dir=tmp_path / "out")
    assert [e["worker_generation"] for e in result["episodes"]] == [1, 2, 3, 4, 5]
    assert all(e["episode_steps"] == 1 for e in result["episodes"])
    assert all(e["controller_error"]["phase"] == "control" for e in result["episodes"])


def test_cli_student_top_level_loop_returns_error_report(tmp_path):
    code = tmp_path / "loop.py"
    code.write_text("while True: pass")
    output = tmp_path / "result"
    completed = subprocess.run([sys.executable, "-m", "control_lab", "evaluate", "--controller", "student",
                                "--controller-file", str(code), "--split", "practice", "--output-dir", str(output),
                                "--execution-timeout", ".1"], capture_output=True, timeout=20)
    assert completed.returncode == 1, completed.stderr.decode(errors="replace")
    assert json.loads((output / "report.json").read_text(encoding="utf-8"))["aggregate"]["controller_errors"] == 5


@pytest.mark.skipif(os.name != "nt", reason="Windows QProcess termination contract")
def test_forced_cli_cancellation_does_not_leave_worker_running(tmp_path):
    import ctypes
    from ctypes import wintypes as w
    marker = tmp_path / "worker.txt"
    code = tmp_path / "slow.py"
    code.write_text(f"""import os, time
from pathlib import Path
Path({str(marker)!r}).write_text(str(os.getpid()))
def control(s, dt):
    time.sleep(.005)
    return 60*s['theta'] + 12*s['omega'] + 2*s['x'] + 3*s['v']
""")
    output = tmp_path / "result"
    process = subprocess.Popen([sys.executable, "-m", "control_lab", "evaluate", "--controller", "student",
                                "--controller-file", str(code), "--split", "practice", "--output-dir", str(output)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    worker_handle = None
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            report_path = output / "report.json"
            if marker.exists() and report_path.exists():
                report = json.loads(report_path.read_text())
                if report["episodes"]:
                    break
            time.sleep(.02)
        else:
            pytest.fail("The real CLI did not finish its first case")
        worker_handle = kernel.OpenProcess(0x00100000, False, int(marker.read_text()))
        assert worker_handle
        process.kill()
        process.wait(timeout=5)
        assert kernel.WaitForSingleObject(worker_handle, 5000) == 0
        report = json.loads((output / "report.json").read_text())
        assert report["status"] == "running" and len(report["episodes"]) >= 1
        assert not report["is_complete"]
        assert (output / report["episodes"][0]["trajectory_file"]).is_file()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        if worker_handle:
            kernel.CloseHandle(worker_handle)
