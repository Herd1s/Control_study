"""Exercise the real cart studio with OS input and an isolated local profile.

Run only when the desktop is available: this tool owns the mouse during its run.
It starts the built Player, never Unity Editor. No model/controller writes are
injected. Telemetry and Unity ScreenCapture are read through the existing QA
contract; native file/color dialogs are restricted to this Player's process.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import time
import zlib

from check_player_windows import CALLBACK, read_snapshot, user32


user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetDlgCtrlID.argtypes = [wintypes.HWND]
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.IsWindow.argtypes = [wintypes.HWND]
user32.EnumChildWindows.argtypes = [wintypes.HWND, CALLBACK, wintypes.LPARAM]


class KeyboardInput(ctypes.Structure):
    _fields_ = [("vk", wintypes.WORD), ("scan", wintypes.WORD),
                ("flags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("extra", ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("data", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("extra", ctypes.c_size_t)]


class InputUnion(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", InputUnion)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def class_name(hwnd):
    value = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, value, len(value))
    return value.value


def process_windows(pid, dialogs=False):
    result = []

    @CALLBACK
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            is_dialog = class_name(hwnd) == "#32770"
            if is_dialog == dialogs:
                result.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return result


def write_test_png(path):
    """Generate a small opaque RGB pattern; no personal or downloaded image."""
    width, height = 96, 48
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            color = (22, 144, 209) if x < width // 2 else (255, 170, 52)
            if (x // 8 + y // 8) % 2:
                color = tuple(min(255, channel + 25) for channel in color)
            rows.extend((*color, 255))

    def chunk(name, payload):
        return struct.pack(">I", len(payload)) + name + payload + struct.pack(">I", zlib.crc32(name + payload) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")
    path.write_bytes(png)


class StudioSession:
    def __init__(self, player, output, profile, width, height, label):
        self.output, self.profile = output, profile
        self.width, self.height, self.label = width, height, label
        self.state_path = output / (label + "-state.json")
        self.log_path = output / (label + "-player.log")
        self.state_path.unlink(missing_ok=True)
        self.hwnd, self.held = None, False
        self.dialog_diagnostics = []
        self.process = subprocess.Popen([
            str(player), "-screen-width", str(width), "-screen-height", str(height),
            "-screen-fullscreen", "0", "-logFile", str(self.log_path),
            "--qa-state-path", str(self.state_path), "--profile-directory", str(profile),
        ], cwd=player.parent)

    def current(self, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = read_snapshot(self.state_path)
                if state.get("ready") and state.get("flowStage") in ("Studio", "Arriving", "Lesson"):
                    return state
            except (OSError, ValueError, KeyError):
                pass
            if self.process.poll() is not None:
                raise RuntimeError("Player exited before studio telemetry became ready")
            time.sleep(0.025)
        raise RuntimeError("No studio snapshot; inspect " + str(self.log_path))

    def wait(self, predicate, description, timeout=6):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            last = self.current()
            if predicate(last):
                return last
            time.sleep(0.04)
        raise AssertionError(description + "; last flow=" + str(last.get("flowStage")))

    def focus(self, window=None):
        target = window or self.hwnd
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(target, ctypes.byref(owner))
        if owner.value != self.process.pid:
            raise RuntimeError("Refusing to focus a window outside the test Player")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            foreground = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground, None)
            this_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            attached = foreground_thread != this_thread and user32.AttachThreadInput(this_thread, foreground_thread, True)
            try:
                user32.ShowWindow(target, 9)
                user32.BringWindowToTop(target)
                user32.SetForegroundWindow(target)
            finally:
                if attached:
                    user32.AttachThreadInput(this_thread, foreground_thread, False)
            time.sleep(0.08)
            if user32.GetForegroundWindow() == target:
                return
        raise RuntimeError("Test Player or its dialog could not obtain focus")

    def start(self):
        deadline = time.monotonic() + 20
        while self.hwnd is None and time.monotonic() < deadline:
            windows = process_windows(self.process.pid)
            self.hwnd = windows[0] if windows else None
            time.sleep(0.1)
        if self.hwnd is None:
            raise RuntimeError("Player window not found")
        self.current(timeout=20)
        self.focus()
        rect, area = wintypes.RECT(), wintypes.RECT()
        user32.GetWindowRect(self.hwnd, ctypes.byref(rect))
        user32.SystemParametersInfoW(48, 0, ctypes.byref(area), 0)
        x = area.left + max(0, (area.right - area.left - rect.right + rect.left) // 2)
        y = area.top + max(0, (area.bottom - area.top - rect.bottom + rect.top) // 2)
        user32.SetWindowPos(self.hwnd, None, x, y, 0, 0, 0x0001 | 0x0004)
        self.move(15, 15)
        time.sleep(0.25)
        return self.current()

    def require_focus(self, target=None):
        if user32.GetForegroundWindow() != (target or self.hwnd):
            raise RuntimeError("Test Player lost focus; stopping OS input")

    def move(self, x, y):
        self.require_focus()
        origin = wintypes.POINT(0, 0)
        user32.ClientToScreen(self.hwnd, ctypes.byref(origin))
        user32.SetCursorPos(round(origin.x + x), round(origin.y + y))

    def down(self):
        self.require_focus()
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        self.held = True

    def up(self):
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        self.held = False

    def key(self, vk, target=None):
        self.require_focus(target)
        user32.keybd_event(vk, 0, 0, 0)
        user32.keybd_event(vk, 0, 2, 0)

    def text(self, value, target=None):
        self.require_focus(target)
        user32.keybd_event(0x11, 0, 0, 0)
        try:
            self.key(0x41, target)
        finally:
            user32.keybd_event(0x11, 0, 2, 0)
        encoded = value.encode("utf-16-le")
        for offset in range(0, len(encoded), 2):
            code = int.from_bytes(encoded[offset:offset + 2], "little")
            events = (Input * 2)()
            for index, flags in enumerate((0x0004, 0x0004 | 0x0002)):
                events[index].type = 1
                events[index].keyboard = KeyboardInput(0, code, flags, 0, 0)
            if user32.SendInput(2, events, ctypes.sizeof(Input)) != 2:
                raise ctypes.WinError(ctypes.get_last_error())
        time.sleep(0.12)

    def element(self, name):
        state = self.current()
        for element in list(state.get("studioElements", [])) + list(state.get("settingsElements", [])):
            if element["name"] == name:
                if not element.get("visible", True) or element["width"] <= 0 or element["height"] <= 0:
                    raise AssertionError("Studio control is not visible: " + name)
                if element.get("enabled") is False:
                    raise AssertionError("Studio control is disabled: " + name)
                return element
        raise AssertionError("Studio control missing from telemetry: " + name)

    def click(self, name, pause=0.13):
        item = self.element(name)
        self.move(item["centerX"], item["centerY"])
        time.sleep(0.025)
        self.down()
        time.sleep(0.04)
        self.up()
        time.sleep(pause)

    def stroke(self, name, fractions):
        area = self.element(name)
        points = [(area["x"] + area["width"] * x, area["y"] + area["height"] * y) for x, y in fractions]
        self.move(*points[0])
        self.down()
        try:
            for start, end in zip(points, points[1:]):
                for index in range(1, 17):
                    self.move(start[0] + (end[0] - start[0]) * index / 16,
                              start[1] + (end[1] - start[1]) * index / 16)
                    time.sleep(0.018)
        finally:
            self.up()
        time.sleep(0.15)
        return self.current()

    def dialog(self, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            windows = process_windows(self.process.pid, dialogs=True)
            if windows:
                self.focus(windows[0])
                return windows[0]
            time.sleep(0.04)
        raise AssertionError("Player-owned native dialog did not appear")

    def dismiss(self, dialog):
        self.focus(dialog)
        self.key(0x1B, dialog)
        self.wait_dialog_closed(dialog)

    def wait_dialog_closed(self, dialog, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not user32.IsWindow(dialog) or not user32.IsWindowVisible(dialog):
                self.focus()
                time.sleep(0.15)
                return
            time.sleep(0.04)
        raise AssertionError("Native dialog did not close")

    def choose_file(self, dialog, path):
        controls, open_buttons = [], []

        @CALLBACK
        def visit(hwnd, _):
            if user32.IsWindowVisible(hwnd):
                bounds = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(bounds))
                own_id = user32.GetDlgCtrlID(hwnd)
                parent_id = user32.GetDlgCtrlID(user32.GetParent(hwnd))
                kind = class_name(hwnd)
                # Enumerate only this Player-owned dialog. Do not read file names,
                # window text, or controls from any other application.
                controls.append({"class": kind, "id": own_id, "parentId": parent_id,
                                 "rect": [bounds.left, bounds.top, bounds.right, bounds.bottom]})
                if kind == "Button" and own_id == 1:
                    open_buttons.append(bounds)
            return True

        user32.EnumChildWindows(dialog, visit, 0)
        self.focus(dialog)
        try:
            # The native Open dialog's Alt+N shortcut focuses File name. Actual
            # Unicode keystrokes update Explorer's internal filename state, unlike
            # WM_SETTEXT, which can change the visible Edit without validation.
            user32.keybd_event(0x12, 0, 0, 0)
            try:
                self.key(0x4E, dialog)
            finally:
                user32.keybd_event(0x12, 0, 2, 0)
            time.sleep(0.1)
            self.text(str(path.resolve()), dialog)
            self.key(0x0D, dialog)
            try:
                self.wait_dialog_closed(dialog, timeout=2)
            except AssertionError:
                # Enter can first accept an autocomplete candidate. Use the real
                # Open button only if this same dialog still owns focus.
                self.require_focus(dialog)
                if not open_buttons:
                    raise
                bounds = open_buttons[0]
                user32.SetCursorPos((bounds.left + bounds.right) // 2, (bounds.top + bounds.bottom) // 2)
                user32.mouse_event(0x0002, 0, 0, 0, 0)
                time.sleep(0.04)
                user32.mouse_event(0x0004, 0, 0, 0, 0)
                self.wait_dialog_closed(dialog)
        except Exception:
            self.dialog_diagnostics.append({"operation": "choose_file", "controls": controls})
            raise

    def capture(self, name):
        self.require_focus()
        target = self.output / name
        target.unlink(missing_ok=True)
        Path(str(self.state_path) + ".capture-request").write_text(name, encoding="utf-8")
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                contents = target.read_bytes()
                if contents.startswith(b"\x89PNG") and contents.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"):
                    return
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError("Unity ScreenCapture did not produce " + name)

    def close(self):
        if self.held:
            self.up()
        cleanup = {"exitObservedBeforeCleanup": self.process.poll() is not None,
                   "hadNativeDialog": False, "dialogsCancelled": True, "forcedTermination": False}
        dialogs = process_windows(self.process.pid, dialogs=True)
        cleanup["hadNativeDialog"] = bool(dialogs)
        baseline_frame = -1
        try:
            baseline_frame = read_snapshot(self.state_path)["frame"]
        except (OSError, ValueError, KeyError):
            pass
        # Never close the Unity window while its native modal call is still on
        # the stack. Cancel one dialog at a time and wait for Unity to resume.
        deadline = time.monotonic() + 8
        while dialogs and self.process.poll() is None and time.monotonic() < deadline:
            foreground = user32.GetForegroundWindow()
            dialog = foreground if foreground in dialogs else dialogs[0]
            try:
                self.focus(dialog)
                self.key(0x1B, dialog)
            except RuntimeError:
                user32.PostMessageW(dialog, 0x0111, 2, 0)  # WM_COMMAND / IDCANCEL
            time.sleep(0.2)
            dialogs = process_windows(self.process.pid, dialogs=True)
        cleanup["dialogsCancelled"] = not dialogs
        resumed = not cleanup["hadNativeDialog"]
        if cleanup["hadNativeDialog"] and not dialogs and self.process.poll() is None:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    if read_snapshot(self.state_path)["frame"] > baseline_frame:
                        resumed = True
                        break
                except (OSError, ValueError, KeyError):
                    pass
                time.sleep(0.05)
        cleanup["playerResumedAfterModal"] = resumed
        if self.process.poll() is None:
            if not dialogs and resumed and self.hwnd:
                user32.PostMessageW(self.hwnd, 0x0010, 0, 0)
            else:
                cleanup["forcedTermination"] = True
                cleanup["reason"] = "Native dialog cancellation or Player resumption timed out; main-window close was not sent."
                self.process.terminate()
        try:
            self.process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            cleanup["forcedTermination"] = True
            cleanup["reason"] = "Player did not exit after orderly cleanup."
            self.process.terminate()
            self.process.wait(timeout=3)
        log = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path.exists() else ""
        markers = ("Exception:", "ICU Data not available", "Unable to find font", "Shader error", "RuntimeProbe write:")
        return {"label": self.label, "playerExitCode": self.process.returncode,
                "runtimeErrorLines": [line for line in log.splitlines() if any(marker in line for marker in markers)],
                "cleanup": cleanup, "nativeDialogDiagnostics": self.dialog_diagnostics,
                "log": str(self.log_path)}


# These IDs are owned by the studio UI, not coordinates copied from a screenshot.
CONTROLS = {
    "name": "studio-name", "color": "studio-body-1", "custom_color": "studio-body-custom",
    "canvas": "studio-paint-canvas", "pen": "studio-tool-brush", "eraser": "studio-tool-eraser",
    "undo": "studio-undo", "clear": "studio-clear", "photo": "studio-photo-add",
    "remove_photo": "studio-photo-remove", "finish": "studio-finish",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "Logs" / "Verification" / f"studio-{args.width}x{args.height}"
    output.mkdir(parents=True, exist_ok=True)
    # Fresh on every invocation; restart within this run deliberately reuses it.
    profile = output / ("profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    profile.mkdir()
    sample = output / "test-photo.png"
    write_test_png(sample)
    player = project / "Builds" / "Windows" / "ControlLab Unity.exe"
    report = {"width": args.width, "height": args.height, "input": "Windows OS mouse and keyboard",
              "profileDirectory": str(profile), "generatedPhoto": str(sample), "checks": [], "sessions": [], "passed": False}
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    session = None

    def expect(condition, name, details=None):
        report["checks"].append({"name": name, "passed": bool(condition), "details": details})
        if not condition:
            raise AssertionError(name + ": " + str(details))

    try:
        session = StudioSession(player, output, profile, args.width, args.height, "first")
        state = session.start()
        expect(state["flowStage"] == "Studio" and not state["isRunning"] and state["time"] == 0,
               "fresh isolated profile opens idle studio")
        expect([state["width"], state["height"]] == [args.width, args.height], "requested client resolution")
        for key in ("name", "color", "custom_color", "canvas", "photo", "finish"):
            item = session.element(CONTROLS[key])
            expect(item["x"] >= 0 and item["y"] >= 0 and item["x"] + item["width"] <= args.width + 1
                   and item["y"] + item["height"] <= args.height + 1, key + " control fully visible", item)
        session.capture("studio-initial.png")

        expected_name = "动量 QA 小车"
        session.click(CONTROLS["name"])
        session.text(expected_name)
        session.key(0x09)  # Commit the TextField by moving focus.
        state = session.wait(lambda value: value["cartName"] == expected_name, "name edit did not commit")
        expect(state["cartName"] == expected_name, "OS keyboard edits cart name", state["cartName"])
        original_color = state["cartColor"]
        session.click(CONTROLS["color"])
        state = session.wait(lambda value: value["cartColor"] != original_color, "preset color did not change")
        expected_color = state["cartColor"]
        expect(expected_color != original_color, "preset changes cart color", expected_color)

        session.click(CONTROLS["custom_color"], pause=0)
        dialog = session.dialog()
        expect(bool(dialog), "custom color opens a Player-owned native dialog")
        session.dismiss(dialog)
        expect(session.current()["cartColor"] == expected_color, "cancel color dialog preserves selected color")

        session.click(CONTROLS["pen"])
        before = session.current()["drawingPixelCount"]
        state = session.stroke(CONTROLS["canvas"], [(0.15, 0.3), (0.65, 0.3)])
        expect(state["drawingPixelCount"] > before and state["undoCount"] > 0,
               "real canvas stroke adds pixels and undo history", state["drawingPixelCount"])
        session.click(CONTROLS["undo"])
        state = session.wait(lambda value: value["drawingPixelCount"] == before, "undo did not restore prior canvas")
        expect(state["drawingPixelCount"] == before, "undo restores canvas before the stroke")
        session.stroke(CONTROLS["canvas"], [(0.15, 0.6), (0.7, 0.6)])
        session.click(CONTROLS["clear"])
        state = session.wait(lambda value: value["drawingPixelCount"] == 0, "clear did not empty drawing layer")
        expect(state["drawingPixelCount"] == 0, "clear removes drawing pixels")
        state = session.stroke(CONTROLS["canvas"], [(0.15, 0.2), (0.45, 0.65), (0.75, 0.2)])
        expected_pixels = state["drawingPixelCount"]
        expect(expected_pixels > 0, "new drawing remains available for persistence test", expected_pixels)

        session.click(CONTROLS["photo"], pause=0)
        session.dismiss(session.dialog())
        expect(not session.current()["hasPhoto"], "cancel local photo selection leaves photo absent")
        session.click(CONTROLS["photo"], pause=0)
        session.choose_file(session.dialog(), sample)
        state = session.wait(lambda value: value["hasPhoto"], "photo import did not update the profile")
        expect(state["hasPhoto"] and state["drawingPixelCount"] == expected_pixels,
               "generated local PNG imports without erasing drawing")
        session.click(CONTROLS["remove_photo"])
        state = session.wait(lambda value: not value["hasPhoto"], "photo removal did not update profile")
        expect(not state["hasPhoto"] and state["drawingPixelCount"] == expected_pixels,
               "photo removal preserves independent drawing layer")
        session.click(CONTROLS["photo"], pause=0)
        session.choose_file(session.dialog(), sample)
        session.wait(lambda value: value["hasPhoto"], "second photo import did not finish")
        session.click(CONTROLS["eraser"])
        state = session.stroke(CONTROLS["canvas"], [(0.15, 0.2), (0.45, 0.65), (0.75, 0.2)])
        expect(state["hasPhoto"] and state["drawingPixelCount"] < expected_pixels,
               "eraser removes drawing while preserving photo", state["drawingPixelCount"])
        session.click(CONTROLS["undo"])
        state = session.wait(lambda value: value["drawingPixelCount"] == expected_pixels, "eraser undo did not restore drawing")
        expect(state["hasPhoto"] and state["drawingPixelCount"] == expected_pixels,
               "undo restores erased drawing independently of photo")
        session.click(CONTROLS["pen"])
        session.click(CONTROLS["photo"], pause=0)
        session.dismiss(session.dialog())
        state = session.current()
        expect(state["hasPhoto"] and state["drawingPixelCount"] == expected_pixels,
               "cancel replacement photo preserves both existing layers")
        expect(state["flowStage"] == "Studio" and not state["isRunning"] and not state["isDragging"] and state["time"] == 0,
               "studio edits never leak into pendulum controls")
        session.capture("studio-customized.png")

        session.click(CONTROLS["finish"], pause=0)
        arrival = []
        deadline = time.monotonic() + 12
        last_frame = -1
        while time.monotonic() < deadline:
            state = session.current()
            if state["frame"] != last_frame:
                last_frame = state["frame"]
                arrival.append({"frame": state["frame"], "stage": state["flowStage"],
                                "x": state["visualCartX"], "scale": state["visualCartScale"],
                                "running": state["isRunning"], "time": state["time"]})
            if state["flowStage"] == "Lesson":
                break
            time.sleep(0.018)
        report["arrivalSamples"] = arrival
        moving = [item for item in arrival if item["stage"] == "Arriving"]
        expect(len(moving) >= 3, "finish enters a sampled arrival stage", len(moving))
        expect(min(item["x"] for item in moving) < -0.1 and len({round(item["x"], 4) for item in moving}) >= 3,
               "cart travels from the left through intermediate positions", moving)
        expect(all(not item["running"] and item["time"] == 0 for item in arrival),
               "arrival animation never starts pendulum physics")
        expect(state["flowStage"] == "Lesson" and abs(state["visualCartX"]) < 0.01,
               "arrival finishes at the lesson centre", state["visualCartX"])
        expect(state["x"] == state["v"] == state["theta"] == state["time"] == 0,
               "lesson begins with physical model upright and idle")
        time.sleep(.55)
        session.capture("lesson-after-arrival.png")
        profile_path = profile / "cart-profile.json"
        saved = json.loads(profile_path.read_text(encoding="utf-8"))
        expect(saved["displayName"] == expected_name and saved["bodyColor"] == expected_color,
               "completed studio saves name and color in isolated profile")
        layers = {}
        for key in ("photoPng", "drawingPng"):
            raw = base64.b64decode(saved[key], validate=True)
            expect(raw.startswith(b"\x89PNG"), key + " persists as a PNG layer")
            layers[key] = hashlib.sha256(raw).hexdigest()
        report["savedLayerSha256"] = layers
        report["sessions"].append(session.close())
        session = None

        session = StudioSession(player, output, profile, args.width, args.height, "restart")
        restored = session.start()
        expect(restored["flowStage"] == "Lesson" and not restored["isRunning"],
               "restart resumes the first chapter without starting physics")
        session.click("customize-cart")
        restored = session.wait(lambda value: value["flowStage"] == "Studio", "Cart customization did not reopen")
        expect(not restored["isRunning"] and restored["time"] == 0,
               "return to studio preserves an idle physical model")
        expect(restored["cartName"] == expected_name, "restart restores cart name", restored["cartName"])
        expect(restored["cartColor"] == expected_color, "restart restores cart color", restored["cartColor"])
        expect(restored["hasPhoto"] and restored["drawingPixelCount"] == expected_pixels,
               "restart restores photo and drawing layers", restored["drawingPixelCount"])
        reloaded = json.loads(profile_path.read_text(encoding="utf-8"))
        expect(all(hashlib.sha256(base64.b64decode(reloaded[key], validate=True)).hexdigest() == digest
                   for key, digest in layers.items()), "restart retains exact saved image layer bytes")
        session.capture("studio-restored.png")
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        if session and session.hwnd:
            try:
                session.capture("failure.png")
            except Exception:
                pass
    finally:
        if session:
            report["sessions"].append(session.close())
        user32.SetCursorPos(original_cursor.x, original_cursor.y)
        if any(item["playerExitCode"] != 0 or item["runtimeErrorLines"] for item in report["sessions"]):
            report["passed"] = False
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "error": report.get("error"), "report": str(output / "result.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
