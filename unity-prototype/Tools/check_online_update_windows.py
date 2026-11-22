"""Exercise the published GitHub update through the real installed Unity UI.

The baseline is a purpose-built 0.1.1 validation client with the current updater,
not the historical 0.1.0 application. No fake feed, transport or install receipt
is used. This driver only installs its fixed OnlineUpdateQA copy and synthetic
profile. It clicks check/download/install, observes the app's own exit/restart,
then verifies the new version reports UpToDate and uninstalls the QA copy.

Default mode checks local inputs without installing, launching or networking.
Pass --execute only after the release is published and other desktop QA ends.
"""
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
import urllib.parse

from check_installer_windows import (
    ASSEMBLY, DATA_FILES, PLAYER_NAME, InstallerSession, ObservedProcess,
    ProcessEntry, default_data_fingerprint, digest, installer_log, kernel32,
    matching_players, normal_close, own_registration, players, process_path,
    profile_fingerprint, registry_entries, same_path, seed_profile,
    split_command_line, wait_process,
)
from check_player_windows import read_snapshot
from check_studio_windows import process_windows, user32


REPOSITORY = "Herd1s/Control_study"
BASELINE_VERSION = "0.1.1"
GITHUB_HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
                "github-releases.githubusercontent.com"}


def validate_target(project, app):
    expected = project / "Builds/OnlineUpdateQA/app"
    if app != expected or not app.resolve().is_relative_to(project.resolve()):
        raise RuntimeError("Installation target is not the fixed OnlineUpdateQA app directory")
    for item in (project, project / "Builds", app.parent, app):
        if item.is_symlink() or item.is_junction():
            raise RuntimeError("Refusing a symlink/junction in the isolated installation path")


def validate_github_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in GITHUB_HOSTS or parsed.port not in (None, 443) or parsed.username or parsed.fragment:
        raise RuntimeError("Published manifest redirected outside supported GitHub HTTPS hosts")


def published_manifest(version):
    url = f"https://github.com/{REPOSITORY}/releases/download/unity-v{version}/unity-update.json"
    # This machine's curl/.NET network path is validated; Python urllib is not.
    # This independent manifest read never supplies an alternate feed to Unity.
    fetched = subprocess.run(["curl.exe", "--location", "--fail", "--silent", "--show-error",
                              "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "5",
                              "--connect-timeout", "15", "--max-time", "60", "--max-filesize", "16384",
                              "--user-agent", "ControlLab-Online-Update-QA/1", "--header", "Accept: application/octet-stream",
                              "--write-out", "\n%{url_effective}", url], capture_output=True, timeout=75,
                             creationflags=subprocess.CREATE_NO_WINDOW)
    if fetched.returncode:
        raise RuntimeError("Real published manifest download failed: " + fetched.stderr.decode("utf-8", errors="replace"))
    data, final_url = fetched.stdout.rsplit(b"\n", 1)
    validate_github_url(final_url.decode("ascii"))
    if len(data) > 16384:
        raise RuntimeError("Published manifest exceeds its size bound")
    value = json.loads(data.decode("utf-8-sig"))
    if (value.get("schema") != 1 or value.get("productId") != "controllab-unity" or value.get("platform") != "windows-x64"
            or value.get("version") != version or value.get("assetName") != f"ControlLab-Unity-Setup-{version}.exe"
            or type(value.get("size")) is not int or not 0 < value["size"] <= 2 * 1024 ** 3
            or not re.fullmatch(r"[0-9a-fA-F]{64}", value.get("sha256", ""))):
        raise RuntimeError("Published manifest does not describe the expected stable Unity release")
    value["sha256"] = value["sha256"].lower()
    return url, data, value


def processes_at(executable):
    """Read only processes whose actual image path is this QA installer."""
    result = []
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        entry = ProcessEntry()
        entry.size = ctypes.sizeof(entry)
        more = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            if entry.exe.casefold() == executable.name.casefold():
                path = process_path(entry.pid)
                if path and same_path(path, executable):
                    result.append({"pid": entry.pid, "path": str(path)})
            more = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result


def process_metadata(pid):
    command = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
               "Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(int(pid)) + "' | "
               "Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine | ConvertTo-Json -Compress")
    return json.loads(subprocess.check_output(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                      encoding="utf-8", errors="strict", timeout=20, creationflags=subprocess.CREATE_NO_WINDOW))


def wait_installer_idle(package, timeout=180):
    # The external bootstrap must finish before another installer/uninstaller
    # touches {app}. Require a quiet period for its final child cleanup.
    deadline, quiet_since = time.monotonic() + timeout, None
    while time.monotonic() < deadline:
        if processes_at(package):
            quiet_since = None
        elif quiet_since is None:
            quiet_since = time.monotonic()
        elif time.monotonic() - quiet_since > 2:
            return
        time.sleep(.1)
    raise RuntimeError("Update installer is still running; QA copy retained without killing it")


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--release-version", default="0.2.0")
    parser.add_argument("--baseline-installer", type=Path, default=project / "Builds/OnlineUpdateQA/baseline-installer/ControlLab-Unity-Setup-0.1.1.exe")
    parser.add_argument("--baseline-player-dir", type=Path, default=project / "Builds/OnlineUpdateQA/client-project/Builds/Windows")
    parser.add_argument("--released-player-dir", type=Path, default=project / "Builds/Windows")
    parser.add_argument("--network-timeout", type=int, default=180)
    parser.add_argument("--download-timeout", type=int, default=960)
    args = parser.parse_args()
    version = args.release_version
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version) or tuple(map(int, version.split("."))) <= (0, 1, 1):
        raise ValueError("The published target must be a stable version newer than the dedicated 0.1.1 validation client")
    app = project / "Builds/OnlineUpdateQA/app"
    player = app / PLAYER_NAME
    validate_target(project, app)
    initial_registry = registry_entries()
    if initial_registry:
        raise RuntimeError("Stable AppId is already registered; refusing to alter an existing installation: " + str(initial_registry))
    if app.exists():
        raise RuntimeError("QA app directory already exists; inspect the preceding run first")
    old_source, new_source = args.baseline_player_dir / ASSEMBLY, args.released_player_dir / ASSEMBLY
    for path in (args.baseline_installer, old_source, new_source):
        if not path.is_file():
            raise FileNotFoundError(path)
    old_hash, new_hash = digest(old_source), digest(new_source)
    if old_hash == new_hash:
        raise RuntimeError("Dedicated lower-version validation client and released assembly must differ")
    if not args.execute:
        print(json.dumps({"prepared": True, "willExecute": False, "willAccessNetwork": False,
                          "baselineKind": "purpose-built current-updater validation client, not historical 0.1.0",
                          "baselineVersion": BASELINE_VERSION, "targetVersion": version, "app": str(app),
                          "baselineInstaller": str(args.baseline_installer), "registryAbsent": True}, ensure_ascii=False))
        return
    if players():
        raise RuntimeError("Another ControlLab Player is running; online update QA must run serially")

    output = project / "Logs/Verification" / ("online-update-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    output.mkdir(parents=True)
    profile = output / "profile-资料 space"
    report = {"passed": False, "checks": [], "sessions": [], "updateStateHistory": [],
              "baselineKind": "purpose-built 0.1.1 client with the release updater; not a historical 0.1.0 upgrade",
              "baselineVersion": BASELINE_VERSION, "targetVersion": version,
              "app": str(app), "profile": str(profile), "registryBefore": initial_registry,
              "baselineAssemblySha256": old_hash, "releasedAssemblySha256": new_hash,
              "input": "real Windows UI clicks and real public GitHub; synthetic isolated learning data"}
    session, restarted, baseline_install = None, None, None
    installation_attempted = False
    install_clicked = False
    main_passed = False
    package = profile / "updates" / f"ControlLab-Unity-Setup-{version}.exe"
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

    def page(name):
        session.click("settings-tab-" + name)
        session.wait(lambda value: value["settingsPage"] == name, "Settings category did not change")
        time.sleep(.25)

    def open_settings():
        session.click("settings-button")
        session.wait(lambda value: value["settingsOpen"], "Settings did not open")

    def update_state(expected, timeout):
        deadline = time.monotonic() + timeout
        previous = None
        last_print = 0
        while time.monotonic() < deadline:
            state = session.current()
            value = state["updateState"]
            changed = value != previous
            if changed:
                report["updateStateHistory"].append({"utc": datetime.now(timezone.utc).isoformat(), "state": value, "status": state["updateStatus"]})
                previous = value
            if changed or time.monotonic() - last_print > 15:
                print("UPDATE " + value + " " + state["updateStatus"], flush=True)
                last_print = time.monotonic()
            if value == expected:
                return state
            if value in ("Error", "NoRelease", "Cancelled") or (value in ("UpToDate", "Available", "Ready")
                    and not (value == "Available" and expected == "Ready")):
                raise AssertionError("Expected " + expected + "; actual " + value + ": " + state["updateStatus"])
            time.sleep(.1)
        raise RuntimeError("Timed out waiting for actual update state " + expected)

    def marker_is(expected):
        value = read_snapshot(app / "installation.json")
        return value.get("productId") == "controllab-unity" and value.get("version") == expected and value.get("status") == "installed"

    try:
        url, manifest_bytes, manifest = published_manifest(version)
        (output / "published-unity-update.json").write_bytes(manifest_bytes)
        report["manifestUrl"] = url
        report["publishedManifest"] = manifest
        expect(True, "read the real published GitHub Unity manifest", {"url": url, "sha256": manifest["sha256"], "size": manifest["size"]})
        seed_profile(profile)
        installation_attempted = True
        baseline_install = subprocess.Popen([str(args.baseline_installer), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                             "/DIR=" + str(app), "/LOG=" + str(output / "baseline-install.log")])
        wait_process(baseline_install, 180, "Dedicated validation-client installer")
        baseline_install = None
        report["baselineRegistry"] = own_registration(app, BASELINE_VERSION)
        expect(digest(app / ASSEMBLY) == old_hash and marker_is(BASELINE_VERSION), "installed the actual dedicated 0.1.1 validation client")
        session = InstallerSession(player, output, profile, 1366, 768, "validation-client-prepare")
        state = session.start()
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"]
               and state["hasPhoto"] and state["drawingPixelCount"] > 0, "validation client loads the isolated lesson and skin")
        expected_pixels, expected_color = state["drawingPixelCount"], state["cartColor"]
        close_session()
        expected_data = profile_fingerprint(profile)
        report["dataBeforeUpdate"] = expected_data

        session = InstallerSession(player, output, profile, 1366, 768, "online-update-client")
        session.start()
        open_settings()
        page("about")
        expect(BASELINE_VERSION in session.element("settings-about-version")["text"], "runtime identifies itself as the dedicated 0.1.1 client")
        page("updates")
        expect(session.current()["updateState"] == "Idle", "opening settings does not manufacture an available update")
        session.click("settings-update-check")
        state = update_state("Available", args.network_timeout)
        expect(version in state["updateStatus"], "real GitHub check offers the published target version", state["updateStatus"])
        session.capture("available-from-github.png")
        session.click("settings-update-download")
        update_state("Ready", args.download_timeout)
        expect(package.is_file() and package.stat().st_size == manifest["size"] and digest(package) == manifest["sha256"],
               "package downloaded by the actual client matches published GitHub SHA256 and byte count")
        expect(not list((profile / "updates").glob("*.part")), "actual successful download leaves no partial package")
        session.capture("download-verified-ready.png")
        expect(profile_fingerprint(profile) == expected_data, "checking and downloading do not change saved course or appearance bytes")

        old_pid = session.process.pid
        old_process = session.process
        pending_path = profile / "updates/pending-update.json"
        confirmed_path = profile / "updates/last-update.json"
        install_clicked = True
        session.click("settings-update-install", pause=0)
        deadline = time.monotonic() + 30
        pending = None
        while time.monotonic() < deadline:
            if pending is None and pending_path.exists():
                try:
                    pending = read_snapshot(pending_path)
                    report["pendingObserved"] = pending
                except (OSError, ValueError):
                    pass
            if "installerProcessObserved" not in report:
                installers = processes_at(package)
                if installers:
                    report["installerProcessObserved"] = installers
            if old_process.poll() is not None:
                break
            time.sleep(.025)
        expect(old_process.poll() == 0, "clicking Install makes the app save and exit itself normally; QA sent no close message",
               {"oldPid": old_pid, "exitCode": old_process.poll(), "exitUtc": datetime.now(timezone.utc).isoformat()})
        # close() sees an exited process here and only gathers its existing log.
        close_session()
        expect(pending is not None and pending.get("status") == "launching" and pending.get("version") == version
               and pending.get("sha256") == manifest["sha256"], "actual updater records its pending handoff before restart", pending)
        expect(profile_fingerprint(profile) == expected_data, "the install action saves the complete original lesson and skin before process exit")

        deadline = time.monotonic() + 180
        observed = []
        receipt = None
        while time.monotonic() < deadline:
            observed = [item for item in matching_players(player) if item["pid"] != old_pid]
            if confirmed_path.exists():
                try:
                    receipt = read_snapshot(confirmed_path)
                except (OSError, ValueError):
                    pass
            if len(observed) == 1 and process_windows(observed[0]["pid"]) and receipt:
                break
            time.sleep(.1)
        expect(len(observed) == 1, "the real downloaded installer starts a new Player at the same isolated installed path", observed)
        restarted = ObservedProcess(observed[0]["pid"], player)
        metadata = process_metadata(restarted.pid)
        argv = split_command_line(metadata["CommandLine"])
        positions = [i for i, arg in enumerate(argv) if arg == "--profile-directory"]
        expect(len(positions) == 1 and positions[0] + 1 < len(argv) and same_path(argv[positions[0] + 1], profile),
               "actual app-to-installer-to-app handoff preserves the exact isolated PROFILEDIR", metadata)
        report["automaticRestart"] = metadata
        expect(receipt is not None and receipt.get("schema") == 1 and receipt.get("productId") == "controllab-unity"
               and receipt.get("version") == version and receipt.get("sha256") == manifest["sha256"]
               and receipt.get("status") == "confirmed-on-restart" and not pending_path.exists(),
               "newly restarted app creates a real confirmed installation receipt and consumes pending state", receipt)
        report["confirmedReceipt"] = receipt
        expect(digest(app / ASSEMBLY) == new_hash and marker_is(version), "actual GitHub installation deploys the released DLL and matching installed marker")
        report["upgradedRegistry"] = own_registration(app, version)
        logs = sorted((profile / "updates").glob("install-" + version + "-*.log"))
        expect(bool(logs), "actual updater generated an installer log inside its isolated update cache")
        report["updateInstallerLog"] = str(logs[-1])
        content = installer_log(logs[-1])
        expect(("Waiting for player " + str(old_pid) + " to save and exit.") in content or "The original player already exited." in content,
               "real installer verified old process exit before replacement")
        wait_installer_idle(package)
        expect(normal_close(restarted, player) == 0, "automatically restarted released app closes normally")
        restarted.release()
        restarted = None
        expect(profile_fingerprint(profile) == expected_data, "confirmed automatic restart preserves every saved learning and skin byte")

        session = InstallerSession(player, output, profile, 1366, 768, "released-client")
        state = session.start()
        expect(state["flowStage"] == "Lesson" and state["activeConcept"] == 1 and state["explanationVisible"] and state["rememberProgress"],
               "released app restores the same learning position and startup preference")
        expect(state["cartName"] == "升级验证小车" and state["cartColor"] == expected_color and state["hasPhoto"]
               and state["drawingPixelCount"] == expected_pixels, "released app restores the same named cart, photo and drawing")
        session.capture("released-lesson-preserved.png")
        open_settings()
        page("about")
        expect(version in session.element("settings-about-version")["text"], "installed runtime About page reports the released version")
        session.capture("released-about.png")
        page("updates")
        session.click("settings-update-check")
        state = update_state("UpToDate", args.network_timeout)
        expect(state["updateState"] == "UpToDate", "a second real GitHub check from the released app reports UpToDate", state["updateStatus"])
        session.capture("github-up-to-date.png")
        close_session()
        report["dataAfterUpdate"] = profile_fingerprint(profile)
        expect(report["dataAfterUpdate"] == expected_data, "entire online update and repeat check preserve checkpoint, preferences, photo and drawing bytes")
        main_passed = True
    except Exception as error:
        report["error"] = str(error)
        if session and session.hwnd and session.process.poll() is None:
            try:
                session.capture("failure.png")
            except Exception:
                pass
    finally:
        if session:
            try:
                report["sessions"].append(session.close())
            except Exception as error:
                cleanup_errors.append("Normal old/new Player close: " + str(error))
        try:
            if baseline_install and baseline_install.poll() is None:
                raise RuntimeError("Baseline installer is still active; QA copy retained")
            if install_clicked:
                wait_installer_idle(package)
            if restarted:
                normal_close(restarted, player)
            # A failure can happen after the installer restarts the app but
            # before the main flow captures its PID. Close only our exact path.
            for item in matching_players(player):
                owned = ObservedProcess(item["pid"], player)
                try:
                    normal_close(owned, player)
                finally:
                    owned.release()
            if installation_attempted and registry_entries():
                validate_target(project, app)
                report["registryBeforeUninstall"] = own_registration(app)
                if matching_players(player):
                    raise RuntimeError("QA Player still running; uninstaller was not launched")
                uninstaller = app / "unins000.exe"
                if not uninstaller.is_file() or uninstaller.is_symlink():
                    raise RuntimeError("QA native uninstaller is missing")
                removal = subprocess.Popen([str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                            "/LOG=" + str(output / "uninstall.log")], cwd=app.parent)
                wait_process(removal, 90, "Online-update QA native uninstaller")
                report["uninstallExitCode"] = removal.returncode
            deadline = time.monotonic() + 10
            while (registry_entries() or app.exists()) and time.monotonic() < deadline:
                time.sleep(.1)
            report["registryAfter"] = registry_entries()
            expect(not report["registryAfter"] and not app.exists(), "native uninstall clears only the online QA copy and its stable AppId registration")
            if installation_attempted:
                expect(profile.exists() and all((profile / name).is_file() for name in DATA_FILES), "native uninstall leaves the isolated learning profile and receipts available for review")
        except Exception as error:
            cleanup_errors.append("Isolated uninstall: " + str(error))
        finally:
            if restarted:
                restarted.release()
        try:
            expect(default_data_fingerprint() == default_before, "default student learning/profile data remains unchanged")
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
