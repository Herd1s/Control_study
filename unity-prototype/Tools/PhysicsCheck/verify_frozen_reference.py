"""Check the frozen historical fixture; never generate values from the tested model.

Only Python's standard library is required. Tools/Verify-Physics.ps1 additionally
replays this independent fixture through the actual C# model.
"""
import hashlib
import json
from pathlib import Path
import sys


def main():
    directory = Path(__file__).resolve().parent
    project = directory.parents[1]
    fixture_path = directory / "Fixtures" / "physics-golden.json"
    report_path = project / "Logs" / "Verification" / "frozen-reference-check.json"
    report = {"passed": False, "check": "frozen-reference-integrity", "fixture": str(fixture_path)}
    try:
        manifest = json.loads(fixture_path.with_name("manifest.json").read_text(encoding="utf-8"))
        content = fixture_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if manifest["schema"] != 1 or manifest["file"] != fixture_path.name:
            raise ValueError("Unsupported fixture manifest")
        if digest != manifest["sha256"]:
            raise ValueError("Frozen reference SHA256 does not match its manifest")
        fixture = json.loads(content)
        if fixture["schema"] != 1 or fixture["protocol"] != manifest["referenceProtocol"]:
            raise ValueError("Unexpected frozen reference protocol")
        cases = fixture["cases"]
        operations = sum(len(case["rows"]) for case in cases)
        if len(cases) != manifest["cases"] or operations != manifest["operations"]:
            raise ValueError("Frozen reference case/operation counts changed")
        if fixture["dt"] != 0.02 or not fixture.get("source_hashes"):
            raise ValueError("Frozen reference has incomplete provenance")
        report.update(passed=True, sha256=digest, cases=len(cases), operations=operations)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report["error"] = str(error)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
