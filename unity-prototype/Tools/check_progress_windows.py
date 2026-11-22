"""Check resume settings in the real Windows Player using isolated local data.

Uses OS mouse and Unicode keyboard input, normal window-close messages, and the
read-only RuntimeProbe. No controller/model calls are injected. Run serially
with other desktop checks because this tool owns the mouse while running.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from check_studio_windows import StudioSession, user32


class ProgressSession(StudioSession):
    """Resolve settings, studio, and first-chapter controls from telemetry."""

    def element(self, name):
        state = self.current()
        candidates = list(state.get("settingsElements", [])) + list(state.get("studioElements", []))
        candidates += [value for value in state.values() if isinstance(value, dict) and value.get("name")]
        for item in candidates:
            if item.get("name") != name:
                continue
            if not item.get("visible", True) or item["width"] <= 0 or item["height"] <= 0:
                raise AssertionError("Control is not visible: " + name)
            if item.get("enabled") is False:
                raise AssertionError("Control is disabled: " + name)
            return item
        raise AssertionError("Control missing from telemetry: " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "Logs" / "Verification" / f"progress-{args.width}x{args.height}"
    output.mkdir(parents=True, exist_ok=True)
    run_name = "profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    profile = output / run_name
    profile.mkdir()
    player = project / "Builds" / "Windows" / "ControlLab Unity.exe"
    report = {"width": args.width, "height": args.height, "profileDirectory": str(profile),
              "input": "Windows OS mouse and keyboard; normal window close", "checks": [], "sessions": [], "passed": False}
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))
    session = None

    def expect(condition, name, details=None):
        report["checks"].append({"name": name, "passed": bool(condition), "details": details})
        if not condition:
            raise AssertionError(name + ": " + str(details))

    def start(label, directory=profile):
        nonlocal session
        session = ProgressSession(player, output, directory, args.width, args.height, label)
        state = session.start()
        time.sleep(.55)  # Let the chapter entrance text finish its short fade.
        return session.current()

    def close():
        nonlocal session
        result = session.close()
        session = None
        report["sessions"].append(result)
        expect(result["playerExitCode"] == 0 and not result["runtimeErrorLines"]
               and not result["cleanup"]["forcedTermination"], result["label"] + " exits normally without runtime errors", result)

    def within(name):
        item = session.element(name)
        return (item["x"] >= -1 and item["y"] >= -1 and item["x"] + item["width"] <= args.width + 1
                and item["y"] + item["height"] <= args.height + 1)

    def open_settings():
        session.click("settings-button")
        return session.wait(lambda state: state["settingsOpen"], "Settings did not open")

    def close_settings():
        session.click("settings-close")
        return session.wait(lambda state: not state["settingsOpen"], "Settings did not close")

    def toggle(expected):
        session.click("settings-remember")
        return session.wait(lambda state: state["rememberProgress"] == expected, "Remember progress toggle did not change")

    def enter():
        session.click("studio-finish")
        state = session.wait(lambda value: value["flowStage"] == "Lesson", "First chapter did not open", timeout=8)
        time.sleep(.55)
        return state

    def idle(state):
        return (not state["isRunning"] and not state["isDragging"] and state["time"] == 0
                and state["x"] == state["v"] == state["theta"] == state["omega"] == 0)

    try:
        state = start("fresh")
        expect(state["flowStage"] == "Studio" and state["rememberProgress"] and not state["settingsOpen"],
               "new profile starts in studio with remember progress enabled")
        expect([state["width"], state["height"]] == [args.width, args.height], "requested client resolution")
        expect(within("settings-button"), "settings entry fits on studio page")
        state = open_settings()
        expect(state["settingsOpen"] and idle(state), "opening settings does not start the experiment")
        for name in ("settings-panel", "settings-remember", "settings-close"):
            expect(within(name), name + " fits without scrolling")
        session.capture("settings-studio.png")
        toggle(False)
        expect(not close_settings()["rememberProgress"], "switch disables resume immediately")

        expected_name = "进度测试小车"
        session.click("studio-name")
        session.text(expected_name)
        session.key(0x09)
        session.wait(lambda value: value["cartName"] == expected_name, "Draft name did not change")
        session.click("studio-body-2")
        state = session.stroke("studio-paint-canvas", [(0.18, 0.25), (0.5, 0.65), (0.8, 0.25)])
        expected_color, expected_pixels = state["cartColor"], state["drawingPixelCount"]
        expect(expected_pixels > 0, "draft drawing contains real mouse strokes")
        close()
        saved = json.loads((profile / "app-preferences.json").read_text(encoding="utf-8-sig"))
        expect(saved["rememberProgress"] is False, "disabled setting is saved on disk")
        appearance = json.loads((profile / "cart-profile.json").read_text(encoding="utf-8-sig"))
        expect(appearance["displayName"] == expected_name and bool(appearance["drawingPng"]),
               "exit saves unfinished studio appearance without clicking finish")

        state = start("draft-restart")
        expect(state["flowStage"] == "Studio" and not state["rememberProgress"], "disabled setting survives restart")
        expect(state["cartName"] == expected_name and state["cartColor"] == expected_color
               and state["drawingPixelCount"] == expected_pixels, "restart restores unfinished name color and drawing")
        enter()
        expect(within("settings-button"), "settings entry fits on first chapter")
        open_settings()
        toggle(True)
        close_settings()
        session.click("explain-button")
        session.wait(lambda value: value["explanationVisible"] and value["gravityButton"]["width"] > 0,
                     "Explanation controls did not finish layout")
        session.click("concept-gravity")
        state = session.wait(lambda value: value["activeConcept"] == 1 and value["explanationVisible"], "Gravity explanation did not open")
        expect(state["rememberProgress"], "resume can be reenabled from the lesson")
        session.click("nudge-button")
        state = session.wait(lambda value: value["isRunning"] and value["time"] > 0, "Nudge did not start the physical experiment")
        expect(state["time"] > 0, "exit checkpoint is exercised during a running experiment")
        state = open_settings()
        paused_time, paused_x = state["time"], state["x"]
        time.sleep(.3)
        state = session.current()
        expect(state["time"] == paused_time and state["x"] == paused_x,
               "settings pauses an active physical experiment")
        close_settings()
        state = session.wait(lambda value: value["time"] > paused_time, "Closing settings did not resume the experiment")
        expect(state["time"] > paused_time, "closing settings continues the same experiment")
        close()
        saved = json.loads((profile / "learning-progress.json").read_text(encoding="utf-8-sig"))
        expect(saved["page"] == "Lesson" and saved["concept"] == 1 and saved["explanationOpen"],
               "exit records lesson and selected explanation")

        state = start("lesson-restart")
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"],
               "restart resumes first chapter at its last explanation")
        expect(idle(state), "resumed lesson starts upright and idle without stale running or dragging state")
        expect(state["cartName"] == expected_name and state["drawingPixelCount"] == expected_pixels,
               "resumed lesson keeps the personalized cart")
        session.capture("lesson-resumed.png")
        nudge = session.element("nudge-button")
        state = open_settings()
        session.move(nudge["centerX"], nudge["centerY"])
        session.down(); time.sleep(.06); session.up(); time.sleep(.2)
        state = session.current()
        expect(state["settingsOpen"] and idle(state), "settings mask blocks the underlying nudge button")
        session.capture("settings-lesson.png")
        toggle(False)
        close_settings()
        close()

        state = start("disabled-restart")
        expect(state["flowStage"] == "Studio" and not state["rememberProgress"],
               "disabled resume returns to studio even after exiting a lesson")
        expect(state["cartName"] == expected_name and state["drawingPixelCount"] == expected_pixels,
               "disabling resume does not clear appearance")
        open_settings()
        toggle(True)
        close_settings()
        expected_name = "继续我的小车"
        session.click("studio-name")
        session.text(expected_name)
        # Deliberately keep the TextField focused while closing the app.
        session.wait(lambda value: value["cartName"] == expected_name, "Focused draft name did not change")
        close()

        state = start("studio-restart")
        expect(state["flowStage"] == "Lesson" and state["rememberProgress"] and state["activeConcept"] == 1,
               "reenabling resume recovers the preserved lesson checkpoint")
        expect(state["cartName"] == expected_name, "focused name edit survives normal app exit")
        session.capture("studio-resumed.png")
        close()
        arrival_profile = output / (run_name + "-arrival")
        arrival_profile.mkdir()
        start("arrival-begin", arrival_profile)
        session.click("studio-finish", pause=0)
        state = session.wait(lambda value: value["flowStage"] == "Arriving", "Arrival did not start")
        expect(state["flowStage"] == "Arriving" and not state["isRunning"], "exit can occur midway through automatic arrival")
        close()

        state = start("arrival-restart", arrival_profile)
        expect(state["flowStage"] == "Lesson" and idle(state), "relaunch after arrival exit opens a ready first chapter")
        expect(state["cartName"] == "我的小车", "arrival interruption retains the completed cart")
        close()

        damaged = output / (run_name + "-damaged")
        damaged.mkdir()
        broken_bytes = b'{"version": 1, "page": '
        (damaged / "learning-progress.json").write_bytes(broken_bytes)
        state = start("damaged-default", damaged)
        expect(state["flowStage"] == "Studio" and state["rememberProgress"] and idle(state),
               "damaged progress without backup falls back to a usable fresh studio")
        close()
        preserved = list(damaged.glob("learning-progress.json.corrupt-*"))
        expect(any(path.read_bytes() == broken_bytes for path in preserved), "damaged progress bytes are retained when repaired")

        backup = output / (run_name + "-backup")
        backup.mkdir()
        (backup / "learning-progress.json").write_bytes(broken_bytes)
        (backup / "learning-progress.json.bak").write_text(json.dumps({"version": 1, "rememberProgress": True,
            "hasProgress": True, "page": "Lesson", "concept": 2, "explanationOpen": True}), encoding="utf-8")
        state = start("damaged-backup", backup)
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 2 and state["explanationVisible"] and idle(state),
               "damaged primary progress restores a valid backup")
        close()
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
        if any(item["playerExitCode"] != 0 or item["runtimeErrorLines"]
               or item["cleanup"]["forcedTermination"] for item in report["sessions"]):
            report["passed"] = False
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]),
                      "error": report.get("error"), "report": str(output / "result.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
