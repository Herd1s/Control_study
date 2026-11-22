"""Validate the real Windows installer, upgrade handoff and isolated user data.

Without --execute this only checks inputs and prints the proposed QA paths.
Run --execute serially with desktop checks. It installs 0.1.0 into the fixed
Builds/InstallerQA/app directory, upgrades to the current candidate, observes
the actual automatic restart, then uninstalls that QA copy. It never publishes,
changes default learning data, injects controller calls or kills a Player.
The isolated profile, screenshots, installer logs and JSON report are retained.
"""
import argparse
import base64
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import winreg
import zlib

from check_player_windows import read_snapshot
from check_progress_windows import ProgressSession
from check_studio_windows import process_windows, user32


APP_ID = "{B6B2A45A-E5B3-49E9-8DB5-974C40B75963}_is1"
REGISTRY_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_ID
PLAYER_NAME = "ControlLab Unity.exe"
ASSEMBLY = Path("ControlLab Unity_Data/Managed/Assembly-CSharp.dll")
DATA_FILES = ("learning-progress.json", "cart-profile.json", "app-preferences.json")
ERROR_MARKERS = ("Exception:", "ICU Data not available", "Unable to find font", "Shader error", "RuntimeProbe write:")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)


class ProcessEntry(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]


kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.LocalFree.argtypes = [ctypes.c_void_p]
shell32.CommandLineToArgvW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                     wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                     ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = wintypes.LPARAM


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def installer_log(path):
    value = path.read_bytes()
    encoding = "utf-16" if value.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return value.decode(encoding, errors="replace")


def registry_entries():
    result = []
    for hive_name, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
        for view, flag in (("64", winreg.KEY_WOW64_64KEY), ("32", winreg.KEY_WOW64_32KEY)):
            try:
                with winreg.OpenKey(hive, REGISTRY_KEY, 0, winreg.KEY_READ | flag) as key:
                    item = {"hive": hive_name, "view": view}
                    for field in ("DisplayName", "DisplayVersion", "InstallLocation", "UninstallString"):
                        try:
                            item[field] = winreg.QueryValueEx(key, field)[0]
                        except FileNotFoundError:
                            pass
                    result.append(item)
            except FileNotFoundError:
                pass
    return result


def same_path(left, right):
    return os.path.normcase(str(Path(left).resolve())) == os.path.normcase(str(Path(right).resolve()))


def validate_target(project, app):
    """Resolve both endpoints and reject reparse points before any installation."""
    expected = project / "Builds" / "InstallerQA" / "app"
    if app != expected or not same_path(app.parent, expected.parent):
        raise RuntimeError("QA installation target is not the fixed workspace app directory")
    for item in (project, project / "Builds", app.parent, app):
        if item.is_symlink() or item.is_junction():
            raise RuntimeError("Refusing a symlink/junction in the QA installation path: " + str(item))
    if not app.resolve().is_relative_to(project.resolve()):
        raise RuntimeError("Resolved QA installation target leaves the project")


def split_command_line(command):
    count = ctypes.c_int()
    values = shell32.CommandLineToArgvW(command, ctypes.byref(count))
    if not values:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [values[i] for i in range(count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(values, ctypes.c_void_p))


def own_registration(app, version=None):
    entries = registry_entries()
    if not entries:
        raise RuntimeError("QA installer did not create its uninstall registration")
    for entry in entries:
        if entry["hive"] != "HKCU" or not entry.get("InstallLocation") or not same_path(entry["InstallLocation"], app):
            raise RuntimeError("Registration does not belong to this isolated QA directory: " + str(entry))
        command = split_command_line(entry.get("UninstallString", ""))
        if not command or not same_path(command[0], app / "unins000.exe"):
            raise RuntimeError("Registered uninstaller is not the isolated QA uninstaller")
        if version is not None and entry.get("DisplayVersion") != version:
            raise AssertionError("Installed registry version differs from the candidate")
    return entries


def process_path(pid):
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        length = wintypes.DWORD(32768)
        value = ctypes.create_unicode_buffer(length.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, value, ctypes.byref(length)):
            return None
        return Path(value.value)
    finally:
        kernel32.CloseHandle(handle)


def players():
    result = []
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.exe.casefold() == PLAYER_NAME.casefold():
                path = process_path(entry.pid)
                result.append({"pid": entry.pid, "parentPid": entry.parent, "path": str(path) if path else None})
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def matching_players(player):
    return [item for item in players() if item["path"] and same_path(item["path"], player)]


class ObservedProcess:
    """Keep a handle to the actual restarted process; never terminate it."""
    def __init__(self, pid, player):
        if not same_path(process_path(pid) or "", player):
            raise RuntimeError("Restarted process path is not the QA Player")
        self.pid = pid
        self.handle = kernel32.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def poll(self):
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        return None if code.value == 259 else code.value

    def release(self):
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None


def normal_close(process, player, timeout=20):
    if process.poll() is None:
        if not same_path(process_path(process.pid) or "", player):
            raise RuntimeError("Refusing to close a process outside the isolated QA path")
        windows = process_windows(process.pid)
        if not windows:
            raise RuntimeError("No Player window available for a normal close; process was not killed")
        for window in windows:
            user32.PostMessageW(window, 0x0010, 0, 0)
        deadline = time.monotonic() + timeout
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(.1)
    if process.poll() is None:
        raise RuntimeError("Player did not exit normally; automatic uninstall has been stopped")
    return process.poll()


class InstallerSession(ProgressSession):
    def __init__(self, player, *args):
        self.player_path = player
        super().__init__(player, *args)

    def close(self):
        # The general UI driver has a forced-cleanup fallback. Installer QA must
        # instead fail and preserve evidence if orderly application exit fails.
        if self.held:
            self.up()
        code = normal_close(self.process, self.player_path)
        log = self.log_path.read_text(encoding="utf-8", errors="replace") if self.log_path.exists() else ""
        return {"label": self.label, "playerExitCode": code, "forcedTermination": False,
                "runtimeErrorLines": [line for line in log.splitlines() if any(value in line for value in ERROR_MARKERS)],
                "log": str(self.log_path)}


def generated_layer(drawing):
    """A synthetic 512x192 image layer, never a student's personal photo."""
    width, height = 512, 192
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            if drawing:
                color = (255, 120, 38, 255) if 48 < x < 464 and abs(y - (x // 4 + 20)) < 7 else (0, 0, 0, 0)
            else:
                color = (34, 151, 211, 255) if (x // 32 + y // 32) % 2 else (250, 196, 91, 255)
            rows.extend(color)
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b""))


def seed_profile(profile):
    profile.mkdir(parents=True)
    data = {
        "learning-progress.json": {"version": 1, "rememberProgress": True, "hasProgress": True,
                                   "page": "Lesson", "concept": 1, "explanationOpen": True},
        "app-preferences.json": {"version": 1, "rememberProgress": True},
        "cart-profile.json": {"version": 1, "displayName": "升级验证小车", "bodyColor": "#2A94A0",
                              "photoPng": base64.b64encode(generated_layer(False)).decode("ascii"),
                              "drawingPng": base64.b64encode(generated_layer(True)).decode("ascii")}}
    for name, value in data.items():
        (profile / name).write_text(json.dumps(value, ensure_ascii=False, indent=4), encoding="utf-8")


def profile_fingerprint(profile):
    appearance = read_snapshot(profile / "cart-profile.json")
    return {"files": {name: digest(profile / name) for name in DATA_FILES},
            "layers": {name: hashlib.sha256(base64.b64decode(appearance[name], validate=True)).hexdigest()
                       for name in ("photoPng", "drawingPng")},
            "checkpoint": read_snapshot(profile / "learning-progress.json"),
            "preferences": read_snapshot(profile / "app-preferences.json")}


def default_data_fingerprint():
    root = Path(os.environ["USERPROFILE"]) / "AppData/LocalLow/ControlLab/ControlLab Unity/garage"
    # Hash only learning/profile data, never inspect or copy its personal text.
    # Unity's standard Player.log lives outside this garage data directory.
    return {"exists": root.exists(), "files": {str(path.relative_to(root)): digest(path)
            for path in sorted(root.rglob("*")) if path.is_file() and "updates" not in path.relative_to(root).parts}}


def wait_process(process, timeout, name):
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(.2)
    if process.poll() is None:
        raise RuntimeError(name + " timed out; no process was killed")
    if process.returncode != 0:
        raise RuntimeError(name + " exited with code " + str(process.returncode))
    return process.returncode


def main():
    project = Path(__file__).resolve().parents[1]
    source = (project / "Assets/ControlLab/Scripts/AppVersion.cs").read_text(encoding="utf-8-sig")
    version = re.search(r'const\s+string\s+Current\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"', source).group(1)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform the real serial installation and uninstall test")
    parser.add_argument("--baseline-installer", type=Path, default=project / "Builds/InstallerQA/baseline-installer/ControlLab-Unity-Setup-0.1.0.exe")
    parser.add_argument("--new-installer", type=Path, default=project / f"Builds/Releases/{version}/ControlLab-Unity-Setup-{version}.exe")
    args = parser.parse_args()
    app = project / "Builds/InstallerQA/app"
    player = app / PLAYER_NAME
    old_source = project / "Builds/Baseline-0.1.0" / ASSEMBLY
    new_source = project / "Builds/Windows" / ASSEMBLY
    validate_target(project, app)
    initial_registry = registry_entries()
    if initial_registry:
        raise RuntimeError("Stable AppId already exists; QA refuses to alter any existing installation: " + str(initial_registry))
    if app.exists():
        raise RuntimeError("QA app directory already exists; inspect the previous run before continuing: " + str(app))
    for path in (args.baseline_installer, args.new_installer, old_source, new_source):
        if not path.is_file():
            raise FileNotFoundError(path)
    old_hash, new_hash = digest(old_source), digest(new_source)
    if old_hash == new_hash:
        raise RuntimeError("Baseline and candidate assemblies must differ to prove replacement")
    manifest = json.loads(args.new_installer.with_name("unity-update.json").read_text(encoding="utf-8-sig"))
    if (manifest.get("productId") != "controllab-unity" or manifest.get("platform") != "windows-x64"
            or manifest.get("version") != version or manifest.get("assetName") != args.new_installer.name
            or manifest.get("size") != args.new_installer.stat().st_size or manifest.get("sha256") != digest(args.new_installer)):
        raise RuntimeError("Candidate installer does not match its actual Unity release manifest")
    if not args.execute:
        print(json.dumps({"prepared": True, "willExecute": False, "registryAbsent": True, "app": str(app),
                          "baselineInstaller": str(args.baseline_installer), "newInstaller": str(args.new_installer),
                          "baselineAssemblySha256": old_hash, "candidateAssemblySha256": new_hash}, ensure_ascii=False))
        return
    if players():
        raise RuntimeError("A ControlLab Player is already running. Run installer QA after other desktop checks finish.")

    output = project / "Logs/Verification" / ("installer-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True)
    profile = output / "profile-资料 space"
    seed_profile(profile)
    report = {"passed": False, "checks": [], "sessions": [], "version": version,
              "app": str(app), "profile": str(profile), "registryBefore": initial_registry,
              "baselineInstaller": str(args.baseline_installer), "newInstaller": str(args.new_installer),
              "baselineAssemblySha256": old_hash, "candidateAssemblySha256": new_hash,
              "input": "synthetic isolated data; real Windows mouse and WM_CLOSE; real Inno Setup executables"}
    session, restarted, installer = None, None, None
    installation_attempted = False
    main_passed = False
    cleanup_errors = []
    default_before = default_data_fingerprint()
    original_cursor = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(original_cursor))

    def expect(condition, name, detail=None):
        report["checks"].append({"name": name, "passed": bool(condition), "details": detail})
        print(("PASS " if condition else "FAIL ") + name, flush=True)
        if not condition:
            raise AssertionError(name + ": " + str(detail))

    def close_session():
        nonlocal session
        result = session.close()
        session = None
        report["sessions"].append(result)
        expect(result["playerExitCode"] == 0 and not result["runtimeErrorLines"], result["label"] + " exits normally without runtime errors", result)

    def marker_is(expected):
        value = read_snapshot(app / "installation.json")
        return value.get("productId") == "controllab-unity" and value.get("version") == expected and value.get("status") == "installed"

    try:
        baseline_log = output / "baseline-install.log"
        installation_attempted = True
        installer = subprocess.Popen([str(args.baseline_installer), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES",
                                      "/NORESTART", "/DIR=" + str(app), "/LOG=" + str(baseline_log)])
        wait_process(installer, 180, "Baseline installer")
        installer = None
        expect(digest(app / ASSEMBLY) == old_hash and marker_is("0.1.0"), "real 0.1.0 installer deployed the baseline DLL and marker")
        report["baselineRegistry"] = own_registration(app, "0.1.0")
        session = InstallerSession(player, output, profile, 1366, 768, "baseline-ready")
        state = session.start()
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"], "installed baseline restores the lesson fixture")
        expect(state["cartName"] == "升级验证小车" and state["hasPhoto"] and state["drawingPixelCount"] > 0, "installed baseline loads photo and drawn skin")
        expected_pixels = state["drawingPixelCount"]
        expected_color = state["cartColor"]
        session.capture("baseline-lesson.png")
        close_session()
        expected_data = profile_fingerprint(profile)
        report["dataBeforeUpgrade"] = expected_data

        session = InstallerSession(player, output, profile, 1366, 768, "baseline-waiting")
        session.start()
        old_pid = session.process.pid
        upgrade_log = output / "upgrade-install.log"
        installer = subprocess.Popen([str(args.new_installer), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                      "/DIR=" + str(app), "/WAITFORPID=" + str(old_pid), "/RESTARTAPP=1",
                                      "/PROFILEDIR=" + str(profile), "/LOG=" + str(upgrade_log)])
        waiting_text = "Waiting for player " + str(old_pid) + " to save and exit."
        deadline = time.monotonic() + 30
        wait_observed = False
        while time.monotonic() < deadline and installer.poll() is None:
            try:
                if upgrade_log.exists() and waiting_text in installer_log(upgrade_log):
                    wait_observed = True
                    break
            except PermissionError:
                pass  # The installer may briefly hold its log while flushing.
            time.sleep(.1)
        expect(wait_observed, "actual installer log confirms WAITFORPID is waiting for this old Player", {"oldPid": old_pid, "log": str(upgrade_log)})
        time.sleep(1.2)
        expect(session.process.poll() is None and installer.poll() is None and digest(app / ASSEMBLY) == old_hash
               and marker_is("0.1.0"), "installer leaves baseline files unchanged while the old Player is alive")
        close_session()
        report["oldPlayerExitUtc"] = datetime.now(timezone.utc).isoformat()
        expect(profile_fingerprint(profile) == expected_data, "old Player normal exit preserves all checkpoint, appearance and preference bytes")
        wait_process(installer, 180, "Upgrade installer")
        report["installerExitCode"] = installer.returncode
        installer = None
        expect(digest(app / ASSEMBLY) == new_hash and marker_is(version), "real upgrade replaces DLL with the candidate and writes its actual version marker")
        report["upgradedRegistry"] = own_registration(app, version)

        deadline = time.monotonic() + 30
        observed = []
        while time.monotonic() < deadline:
            observed = [item for item in matching_players(player) if item["pid"] != old_pid]
            if len(observed) == 1 and process_windows(observed[0]["pid"]):
                break
            time.sleep(.1)
        expect(len(observed) == 1, "installer actually starts a new process at the installed QA path", observed)
        restarted = ObservedProcess(observed[0]["pid"], player)
        # CIM reads OS process metadata; it neither creates a replacement Player
        # nor supplies a fabricated runtime snapshot for the automatic restart.
        command = "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(restarted.pid) + "' | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress"
        metadata = json.loads(subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                             encoding="utf-8", errors="replace", timeout=20, creationflags=subprocess.CREATE_NO_WINDOW))
        argv = split_command_line(metadata["CommandLine"])
        positions = [i for i, arg in enumerate(argv) if arg == "--profile-directory"]
        expect(len(positions) == 1 and positions[0] + 1 < len(argv) and same_path(argv[positions[0] + 1], profile),
               "automatic restart receives the exact isolated PROFILEDIR", metadata)
        report["automaticRestart"] = metadata
        time.sleep(3)
        window = process_windows(restarted.pid)[0]
        response = ctypes.c_size_t()
        responsive = bool(user32.SendMessageTimeoutW(window, 0, 0, 0, 2, 2000, ctypes.byref(response)))
        expect(restarted.poll() is None and responsive, "automatically restarted Player stays alive with a responsive real window")
        expect(normal_close(restarted, player) == 0, "automatically restarted Player closes normally")
        restarted.release()
        restarted = None
        expect(profile_fingerprint(profile) == expected_data, "automatic new-version launch preserves checkpoint, photo, drawing and preference bytes")

        session = InstallerSession(player, output, profile, 1366, 768, "upgraded-ready")
        state = session.start()
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"]
               and state["rememberProgress"], "installed new Player restores the same lesson and startup preference")
        expect(state["cartName"] == "升级验证小车" and state["cartColor"] == expected_color and state["hasPhoto"]
               and state["drawingPixelCount"] == expected_pixels, "installed new Player renders the same name, color, photo and drawing")
        session.capture("upgraded-lesson.png")
        session.click("settings-button")
        session.wait(lambda value: value["settingsOpen"], "New settings did not open")
        session.click("settings-tab-about")
        session.wait(lambda value: value["settingsPage"] == "about", "About page did not open")
        time.sleep(.3)
        expect(version in session.element("settings-about-version")["text"], "installed runtime about page reports the candidate version")
        session.capture("upgraded-about.png")
        session.click("settings-close")
        session.wait(lambda value: not value["settingsOpen"], "Settings did not close")
        session.click("nudge-button")
        session.wait(lambda value: value["time"] > 0, "Installed new Player does not run its physical experiment")
        session.click("reset-button")
        session.wait(lambda value: value["time"] == 0 and value["theta"] == 0, "Installed new Player does not reset upright")
        close_session()
        report["dataAfterUpgrade"] = profile_fingerprint(profile)
        expect(report["dataAfterUpgrade"] == expected_data, "all saved learning and appearance bytes survive actual installation and normal app use")
        main_passed = True
    except Exception as error:
        report["error"] = str(error)
        if session and session.hwnd:
            try:
                session.capture("failure.png")
            except Exception:
                pass
    finally:
        if session:
            try:
                report["sessions"].append(session.close())
            except Exception as error:
                cleanup_errors.append("Normal Player close: " + str(error))
        if restarted:
            try:
                normal_close(restarted, player)
            except Exception as error:
                cleanup_errors.append("Normal restarted Player close: " + str(error))
            finally:
                restarted.release()
        try:
            # Never run the uninstaller concurrently with a timed-out installer.
            if installer and installer.poll() is None:
                raise RuntimeError("Installer is still active; QA installation retained for inspection")
            if installation_attempted and registry_entries():
                validate_target(project, app)
                report["registryBeforeUninstall"] = own_registration(app)
                if matching_players(player):
                    raise RuntimeError("QA Player still running; native uninstall skipped")
                uninstaller = app / "unins000.exe"
                if not uninstaller.is_file() or uninstaller.is_symlink():
                    raise RuntimeError("Expected native QA uninstaller missing")
                removal = subprocess.Popen([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                            "/LOG=" + str(output / "uninstall.log")], cwd=app.parent)
                wait_process(removal, 90, "QA native uninstaller")
                report["uninstallExitCode"] = removal.returncode
            # Inno may finish its bootstrap process before the temporary child
            # removes the uninstaller itself and the last empty app directory.
            deadline = time.monotonic() + 10
            while (registry_entries() or app.exists()) and time.monotonic() < deadline:
                time.sleep(.1)
            report["registryAfter"] = registry_entries()
            expect(not report["registryAfter"] and not app.exists(), "native uninstall removes only the QA app and clears its stable AppId registration")
            expect(profile.exists() and all((profile / name).is_file() for name in DATA_FILES), "native uninstall retains the isolated learning profile for review")
        except Exception as error:
            cleanup_errors.append("QA uninstall: " + str(error))
        try:
            unchanged = default_data_fingerprint() == default_before
            expect(unchanged, "default student learning/profile files were not changed")
        except Exception as error:
            cleanup_errors.append("Default data verification: " + str(error))
        user32.SetCursorPos(original_cursor.x, original_cursor.y)
        report["cleanupErrors"] = cleanup_errors
        report["passed"] = main_passed and not cleanup_errors
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": len(report["checks"]), "report": str(output / "result.json")}, ensure_ascii=False))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
