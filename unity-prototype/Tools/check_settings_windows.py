"""Exercise unified Unity settings and in-course appearance edits with real OS input.

Uses an isolated v1 checkpoint to check real Unity preference migration. This
driver never injects model/controller calls. --check-github performs an actual
manual update check and reports network validation separately from UI checks.
Run serially with other desktop checks: this process owns the mouse while active.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from check_player_windows import read_snapshot
from check_progress_windows import ProgressSession
from check_studio_windows import user32, write_test_png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--width", type=int, default=1366)
    parser.add_argument("--height", type=int, default=768)
    parser.add_argument("--check-github", action="store_true")
    parser.add_argument("--expect-update-state", default="NoRelease", choices=("NoRelease", "UpToDate", "Available"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "Logs" / "Verification" / f"settings-{args.width}x{args.height}"
    output.mkdir(parents=True, exist_ok=True)
    profile = output / ("profile-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    profile.mkdir()
    legacy = {"version": 1, "rememberProgress": False, "hasProgress": True,
              "page": "Lesson", "concept": 1, "explanationOpen": True}
    progress_path = profile / "learning-progress.json"
    progress_path.write_text(json.dumps(legacy), encoding="utf-8")
    preference_path = profile / "app-preferences.json"
    photo_path = output / "generated-photo.png"
    write_test_png(photo_path)
    player = project / "Builds" / "Windows" / "ControlLab Unity.exe"
    report = {"width": args.width, "height": args.height, "profileDirectory": str(profile),
              "input": "Windows OS mouse and Unicode keyboard; normal app exit",
              "checks": [], "sessions": [], "uiPassed": False, "passed": False,
              "liveUpdate": {"requested": args.check_github, "passed": None,
                             "expectedState": args.expect_update_state}}
    session = None
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))

    def expect(condition, name, details=None):
        report["checks"].append({"name": name, "passed": bool(condition), "details": details})
        if not condition:
            raise AssertionError(name + ": " + str(details))

    def start(label):
        nonlocal session
        session = ProgressSession(player, output, profile, args.width, args.height, label)
        session.start()
        time.sleep(.55)
        return session.current()

    def close():
        nonlocal session
        result = session.close()
        session = None
        report["sessions"].append(result)
        expect(result["playerExitCode"] == 0 and not result["runtimeErrorLines"]
               and not result["cleanup"]["forcedTermination"], result["label"] + " closes cleanly", result)

    def within(name):
        item = session.element(name)
        return (item["x"] >= -1 and item["y"] >= -1 and item["x"] + item["width"] <= args.width + 1
                and item["y"] + item["height"] <= args.height + 1)

    def open_settings():
        session.click("settings-button")
        return session.wait(lambda value: value["settingsOpen"], "Settings did not open")

    def select_page(name):
        session.click("settings-tab-" + name)
        state = session.wait(lambda value: value["settingsPage"] == name, "Settings tab did not change")
        time.sleep(.25)
        return state

    def close_settings():
        session.click("settings-close")
        return session.wait(lambda value: not value["settingsOpen"], "Settings did not close")

    def set_remember(enabled):
        select_page("learning")
        if session.current()["rememberProgress"] != enabled:
            session.click("settings-remember")
        return session.wait(lambda value: value["rememberProgress"] == enabled, "Startup preference did not change")

    def checkpoint():
        value = read_snapshot(progress_path)
        return {key: value[key] for key in ("hasProgress", "page", "concept", "explanationOpen")}

    def preserved(state):
        return state["savedPage"] == "Lesson" and state["savedConcept"] == 1

    def idle(state):
        return (state["x"] == state["v"] == state["theta"] == state["omega"] == state["time"] == 0
                and not state["isRunning"] and not state["isDragging"])

    def edit_from_settings():
        open_settings()
        select_page("cart")
        session.click("settings-edit-cart")
        return session.wait(lambda value: value["flowStage"] == "Studio" and value["customizingCart"],
                            "In-course appearance editor did not open")

    try:
        state = start("migration-disabled")
        expect([state["width"], state["height"]] == [args.width, args.height], "requested client resolution")
        expect(state["flowStage"] == "Studio" and not state["rememberProgress"] and idle(state),
               "legacy opt-out starts in studio without running an experiment")
        expect(preserved(state), "legacy lesson and explanation checkpoint survive opt-out startup")
        expect(preference_path.exists() and not read_snapshot(preference_path)["rememberProgress"],
               "real Unity migration creates an independent disabled preference")
        state = open_settings()
        expect(state["settingsOpen"] and preserved(state), "settings opens without changing the retained checkpoint")
        for name in ("settings-panel", "settings-close", "settings-tab-learning", "settings-tab-cart",
                     "settings-tab-updates", "settings-tab-about"):
            expect(within(name), name + " fits without scrolling")
        select_page("learning")
        expect(within("settings-remember"), "learning preference control fits")
        session.capture("settings-learning.png")
        select_page("cart")
        expect(within("settings-edit-cart"), "cart editor entry fits")
        session.capture("settings-cart.png")
        state = select_page("updates")
        expect(within("settings-update-check"), "update check entry fits")
        expect(state["updateState"] == "Idle", "opening update settings does not automatically access the network")
        session.capture("settings-updates.png")
        select_page("about")
        expect(within("settings-project-link"), "about project link fits")
        session.capture("settings-about.png")

        if args.check_github:
            select_page("updates")
            session.click("settings-update-check", pause=.03)
            try:
                state = session.wait(lambda value: value["updateState"] not in ("Idle", "Checking"),
                                     "GitHub update check did not finish", timeout=50)
                report["liveUpdate"].update(state=state["updateState"], status=state["updateStatus"],
                                            passed=state["updateState"] == args.expect_update_state)
                session.capture("github-result.png")
            except Exception as error:
                report["liveUpdate"].update(passed=False, error=str(error))
            # Network results are deliberately not counted as a local UI assertion.
            # A network failure does not prevent the remaining local checks running.

        before = checkpoint()
        set_remember(True)
        expect(checkpoint() == before and read_snapshot(preference_path)["rememberProgress"],
               "enabling auto continue changes only its independent preference")
        close_settings()
        close()
        expect(checkpoint() == before, "exiting the opt-out studio does not replace the saved lesson with the home page")

        state = start("migration-enabled")
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"],
               "reenabling continue restores the original lesson and explanation")
        expect(idle(state), "restored lesson is upright and idle")
        session.click("nudge-button")
        state = session.wait(lambda value: value["hasFallen"] and value["time"] > 0,
                             "Nudge did not produce a settled nonzero episode", timeout=8)
        physical = {key: state[key] for key in ("x", "v", "theta", "omega", "time", "hasFallen")}
        before = checkpoint()
        open_settings()
        set_remember(False)
        expect(checkpoint() == before, "turning continue off in a lesson preserves its exact checkpoint fields")
        set_remember(True)
        expect(checkpoint() == before, "turning continue back on does not reset lesson progress")
        select_page("cart")
        session.click("settings-edit-cart")
        state = session.wait(lambda value: value["flowStage"] == "Studio" and value["customizingCart"],
                             "Lesson appearance mode did not open")
        expect(not state["settingsOpen"] and preserved(state), "editing a skin retains the original learning location")
        expect({key: state[key] for key in physical} == physical, "entering the appearance editor does not reset physical episode state")
        expect("保存" in session.element("studio-finish")["text"], "in-course edit has a save and return action")
        name = "我的控制实验车"
        session.click("studio-name")
        session.text(name)
        session.key(0x09)
        session.click("studio-body-1")
        session.click("studio-photo-add", pause=0)
        session.choose_file(session.dialog(), photo_path)
        session.wait(lambda value: value["hasPhoto"], "Local generated photo did not import")
        state = session.stroke("studio-paint-canvas", [(0.18, .25), (.5, .7), (.82, .25)])
        color, pixels = state["cartColor"], state["drawingPixelCount"]
        expect(state["cartName"] == name and pixels > 0 and state["hasPhoto"],
               "in-course editor supports name color photo and drawing")
        session.capture("skin-editor.png")
        session.click("studio-finish", pause=0)
        return_states = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            state = session.current()
            return_states.append(state["flowStage"])
            if state["flowStage"] == "Lesson":
                break
            time.sleep(.03)
        expect(state["flowStage"] == "Lesson" and "Arriving" not in return_states and not state["customizingCart"],
               "saving an edited skin returns directly without the onboarding drive", return_states)
        expect(state["activeConcept"] == 1 and state["explanationVisible"] and preserved(state),
               "save and return restores the original explanation")
        expect({key: state[key] for key in physical} == physical,
               "save and return keeps the same physical episode instead of silently restarting it")
        expect(state["cartName"] == name and state["cartColor"] == color and state["drawingPixelCount"] == pixels,
               "returned lesson displays the new cart appearance")
        time.sleep(.4)
        session.capture("lesson-after-skin.png")
        open_settings()
        set_remember(False)
        close_settings()
        close()
        saved_appearance = read_snapshot(profile / "cart-profile.json")
        layer_hashes = {key: hashlib.sha256(saved_appearance[key].encode("ascii")).hexdigest()
                        for key in ("photoPng", "drawingPng")}

        state = start("opted-out-again")
        expect(state["flowStage"] == "Studio" and not state["rememberProgress"] and preserved(state),
               "opting out returns home while keeping the previous chapter checkpoint")
        expect(state["cartName"] == name and state["hasPhoto"] and state["drawingPixelCount"] == pixels,
               "opting out retains the personalized cart and both layers")
        appearance = read_snapshot(profile / "cart-profile.json")
        expect(all(hashlib.sha256(appearance[key].encode("ascii")).hexdigest() == digest for key, digest in layer_hashes.items()),
               "restart preserves the exact saved photo and drawing bytes")
        open_settings()
        set_remember(True)
        close_settings()
        close()
        expect(checkpoint()["page"] == "Lesson" and checkpoint()["concept"] == 1,
               "repeated home-page exits do not erase the retained course")

        state = start("edit-draft")
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and idle(state),
               "a later restart resumes the retained course")
        edit_from_settings()
        name = "继续探索的小车"
        session.click("studio-name")
        session.text(name)
        session.key(0x09)
        session.click("studio-body-4")
        state = session.stroke("studio-paint-canvas", [(.2, .78), (.8, .78)])
        color, pixels = state["cartColor"], state["drawingPixelCount"]
        expect(state["customizingCart"] and preserved(state), "unfinished appearance edit still points to the original lesson")
        close()
        expect(checkpoint()["page"] == "Lesson", "quitting inside the appearance editor keeps the lesson checkpoint")

        state = start("draft-resumed")
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"] and idle(state),
               "restart after an unfinished skin edit resumes the original explanation")
        expect(state["cartName"] == name and state["cartColor"] == color and state["hasPhoto"]
               and state["drawingPixelCount"] == pixels,
               "exit automatically saves unfinished skin edits without a finish click")
        session.capture("draft-skin-restored.png")
        close()
        report["uiPassed"] = True
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
        clean = all(item["playerExitCode"] == 0 and not item["runtimeErrorLines"]
                    and not item["cleanup"]["forcedTermination"] for item in report["sessions"])
        report["uiPassed"] = report["uiPassed"] and clean
        report["passed"] = report["uiPassed"] and (not args.check_github or report["liveUpdate"]["passed"] is True)
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "uiPassed": report["uiPassed"], "checks": len(report["checks"]),
                      "liveUpdate": report["liveUpdate"], "error": report.get("error"),
                      "report": str(output / "result.json")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
