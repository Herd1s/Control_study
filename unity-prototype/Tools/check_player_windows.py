"""Exercise the real Windows Player using OS mouse input and read-only telemetry.

Run with a system Python on Windows; only the standard library is needed.
Screenshots come from Unity's own renderer.
No controller calls or model resets are injected into the application.
"""
import argparse
import ctypes
from datetime import datetime, timezone
from ctypes import wintypes
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))

user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.BringWindowToTop.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE


def read_snapshot(path):
    # Allow the Player to atomically replace the file while this old handle is
    # being read. Python's default Windows file sharing omits FILE_SHARE_DELETE.
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
        return json.load(stream)


def find_window(pid):
    found = []

    @CALLBACK
    def visit(hwnd, _):
        window_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
        if window_pid.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "Logs" / "Verification" / f"player-{args.width}x{args.height}"
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "state.json"
    state_path.unlink(missing_ok=True)
    player = project / "Builds" / "Windows" / "ControlLab Unity.exe"
    report = {"width": args.width, "height": args.height, "input": "Windows OS mouse", "checks": [], "passed": False}
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    process = subprocess.Popen([str(player), "-screen-width", str(args.width), "-screen-height", str(args.height),
        "-screen-fullscreen", "0", "-logFile", str(output / "player.log"), "--qa-state-path", str(state_path),
        "--profile-directory", str(output / ("profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")))], cwd=player.parent)
    hwnd = None
    held = False

    def current(timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                result = read_snapshot(state_path)
                if result["ready"] and (result.get("flowStage") == "Studio" or result["resetButton"]["width"] > 0):
                    return result
            except (OSError, ValueError, KeyError):
                pass
            if process.poll() is not None:
                raise RuntimeError("Player exited before a complete runtime snapshot")
            time.sleep(0.04)
        raise RuntimeError("No ready runtime snapshot; inspect player.log")

    def expect(condition, name, details=None):
        report["checks"].append({"name": name, "passed": bool(condition), "details": details})
        if not condition:
            raise AssertionError(name + ": " + str(details))

    def focus():
        # Wait out the native splash window, then activate only our own Player.
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
            current_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = foreground_thread != current_thread and user32.AttachThreadInput(current_thread, foreground_thread, True)
            try:
                user32.ShowWindow(hwnd, 9)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
            finally:
                if attached:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            time.sleep(0.2)
            if user32.GetForegroundWindow() == hwnd:
                return
        raise RuntimeError("Prototype could not obtain focus; no mouse input was sent")

    def move(x, y):
        if user32.GetForegroundWindow() != hwnd:
            raise RuntimeError("Prototype lost focus; stopping mouse input")
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(hwnd, ctypes.byref(origin))
        user32.SetCursorPos(round(origin.x + x), round(origin.y + y))

    def down():
        nonlocal held
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        held = True

    def up():
        nonlocal held
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        held = False

    def click_button(key):
        button = current()[key]
        move(button["centerX"], button["centerY"])
        time.sleep(0.04)
        down()
        time.sleep(0.06)
        up()
        time.sleep(0.18)
        return current()

    def capture(name):
        if user32.GetForegroundWindow() != hwnd:
            raise RuntimeError("Refusing to capture an obscured Player window")
        image_path = output / name
        image_path.unlink(missing_ok=True)
        request = Path(str(state_path) + ".capture-request")
        request.write_text(name, encoding="utf-8")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                png = image_path.read_bytes()
                if png.startswith(b"\x89PNG") and png.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError("Unity did not complete the requested screenshot")

    try:
        deadline = time.monotonic() + 20
        while hwnd is None and time.monotonic() < deadline:
            hwnd = find_window(process.pid)
            time.sleep(0.1)
        if hwnd is None:
            raise RuntimeError("Player window not found")
        focus()
        current(timeout=20)
        time.sleep(1.0)
        window_rect = wintypes.RECT()
        work_area = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(window_rect))
        user32.SystemParametersInfoW(48, 0, ctypes.byref(work_area), 0)
        outer_width, outer_height = window_rect.right - window_rect.left, window_rect.bottom - window_rect.top
        window_x = work_area.left + max(0, (work_area.right - work_area.left - outer_width) // 2)
        window_y = work_area.top + max(0, (work_area.bottom - work_area.top - outer_height) // 2)
        user32.SetWindowPos(hwnd, None, window_x, window_y, 0, 0, 0x0001 | 0x0004)
        report["desktop"] = {"workArea": [work_area.left, work_area.top, work_area.right, work_area.bottom],
            "windowOuterSize": [outer_width, outer_height], "placedAt": [window_x, window_y]}
        move(60, 60)
        time.sleep(0.5)
        state = current()
        if state.get("flowStage") == "Studio":
            button = next(item for item in state["studioElements"] if item["name"] == "studio-finish")
            move(button["centerX"], button["centerY"])
            down(); time.sleep(0.06); up()
            deadline = time.monotonic() + 7
            while time.monotonic() < deadline:
                state = current()
                if state.get("flowStage") == "Lesson": break
                time.sleep(0.06)
            if state.get("flowStage") != "Lesson": raise RuntimeError("Studio did not enter the first chapter")
            time.sleep(0.6)
            state = current()
        expect(state["width"] == args.width and state["height"] == args.height, "requested client resolution", [state["width"], state["height"]])
        for key in ("resetButton", "nudgeButton", "explainButton"):
            button = state[key]
            expect(button["visible"] and button["width"] > 0 and button["height"] >= 40 and button["x"] >= 0 and button["y"] >= 0
                and button["x"] + button["width"] <= args.width + 1 and button["y"] + button["height"] <= args.height + 1,
                key + " fully visible", button)
        expect(state["fontLoaded"] and state["themeLoaded"] and state["stylesheetLoaded"], "font, theme and style available", state["fontName"])
        expect(state["unsupportedShaderCount"] == 0, "all materials use supported shaders", state["rendererCount"])
        expect(state["x"] == state["theta"] == state["v"] == 0 and not state["isRunning"], "initial upright idle")
        capture("initial.png")
        state = click_button("explainButton")
        expect(state["explanationVisible"] and not state["isDragging"] and state["time"] == 0, "explanation opens without grabbing cart")
        expect(state["heroHidden"] and state["explanationBottom"] < state["poleTipScreenY"],
            "explanation replaces heading without obscuring the upright pole", [state["explanationBottom"], state["poleTipScreenY"]])
        expect(state["activeConcept"] == 0 and not state["momentumVector"]["visible"], "stationary cart has no momentum arrow")
        for key in ("momentumButton", "gravityButton", "controlButton"):
            button = state[key]
            expect(button["visible"] and button["x"] >= 0 and button["y"] >= 0
                and button["x"] + button["width"] <= args.width and button["y"] + button["height"] < state["poleTipScreenY"],
                key + " remains inside explanation area", button)
        capture("explanation.png")
        state = click_button("gravityButton")
        vector = state["gravityVector"]
        expect(state["activeConcept"] == 1 and vector["visible"] and vector["dy"] < 0
            and abs(vector["dx"]) < 1e-6 and abs(vector["dz"]) < 1e-6, "gravity arrow points vertically down", vector)
        capture("gravity.png")
        state = click_button("controlButton")
        expect(state["activeConcept"] == 2 and "转速" in state["explanationText"]
            and not state["gravityVector"]["visible"] and not state["momentumVector"]["visible"] and state["time"] == 0,
            "control topic is optional and does not start the experiment")
        capture("catch.png")
        expect(not click_button("explainButton")["explanationVisible"], "explanation closes")
        expect(not current()["heroHidden"], "closing explanation restores the main heading")
        click_button("explainButton")
        click_button("momentumButton")

        state = current()
        cart = state["cartScreenPosition"]
        grab_x, grab_y = cart["x"] + 25, cart["y"]
        move(grab_x, grab_y)
        time.sleep(0.05)
        down()
        time.sleep(0.16)
        state = current()
        expect(state["isDragging"] and abs(state["x"]) < 0.002, "edge grab preserves pointer offset", state["x"])
        for index in range(1, 9):
            move(grab_x + index * 6, grab_y)
            time.sleep(0.035)
        state = current()
        expect(state["isDragging"] and state["x"] > 0.08, "real mouse drag moves the cart", state["x"])
        vector = state["momentumVector"]
        expect(vector["visible"] and vector["dx"] * state["v"] > 0 and abs(vector["dy"]) < 1e-6,
            "momentum arrow follows cart velocity during a real drag", vector)
        before_release = state["x"]
        up()
        time.sleep(0.12)
        state = current()
        expect(not state["isDragging"] and state["isRunning"] and state["x"] > before_release, "release preserves physical motion", {"before": before_release, "after": state["x"], "v": state["v"]})
        deadline = time.monotonic() + 8
        while not state["hasFallen"] and time.monotonic() < deadline:
            time.sleep(0.1)
            state = current()
        expect(state["hasFallen"] and not state["nudgeButton"]["enabled"], "fall state and nudge disabled")
        state = click_button("gravityButton")
        vector = state["gravityVector"]
        expect(vector["visible"] and vector["dy"] < 0 and abs(vector["dx"]) < 1e-6
            and abs(state["theta"]) > 0.2, "gravity stays vertical while the pole is tilted", vector)
        click_button("explainButton")
        state = current()
        capture("fallen.png")
        fallen_x = state["x"]
        move(state["cartScreenPosition"]["x"], state["cartScreenPosition"]["y"])
        down()
        time.sleep(0.12)
        state = current()
        expect(state["isDragging"] and not state["hasFallen"] and abs(state["theta"]) < 0.002
            and abs(state["x"] - max(-2.3, min(2.3, fallen_x))) < 0.005, "regrab restores upright at bounded current position", state["x"])
        up()

        state = click_button("resetButton")
        expect(state["x"] == state["theta"] == state["v"] == state["time"] == 0 and not state["isRunning"], "reset returns to upright idle centre")
        state = click_button("nudgeButton")
        expect(state["isRunning"] and state["time"] > 0 and abs(state["theta"]) > 0, "nudge button creates a physical disturbance", state["theta"])
        click_button("resetButton")
        state = current()
        move(state["cartScreenPosition"]["x"], state["cartScreenPosition"]["y"])
        down()
        time.sleep(0.13)
        expect(current()["isDragging"], "grab before focus loss")
        user32.ShowWindow(hwnd, 6)
        time.sleep(0.2)
        up()
        focus()
        time.sleep(0.15)
        expect(not current()["isDragging"], "focus loss releases the cart")
        click_button("resetButton")
        capture("final-idle.png")
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        if hwnd:
            try:
                capture("failure.png")
            except Exception:
                pass
    finally:
        if held:
            up()
        if hwnd:
            user32.PostMessageW(hwnd, 0x0010, 0, 0)
        try:
            process.wait(timeout=6)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=3)
        user32.SetCursorPos(original_cursor.x, original_cursor.y)
        report["playerExitCode"] = process.returncode
        log = (output / "player.log").read_text(encoding="utf-8", errors="replace")
        report["runtimeErrorLines"] = [line for line in log.splitlines() if any(marker in line for marker in
            ("Exception:", "ICU Data not available", "Unable to find font", "Shader error", "RuntimeProbe write:"))]
        if report["runtimeErrorLines"] or process.returncode != 0:
            report["passed"] = False
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "error": report.get("error"), "report": str(output / "result.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
