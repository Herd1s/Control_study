"""Reject unlike experiments before presenting per-method results."""
from .metrics import METRICS_VERSION
from .protocol import canonical_hash

COMPARABILITY_FIELDS = ("protocol_id", "protocol_hash", "cases_hash", "split", "input_mode",
                        "observation_contract", "reward_id", "metrics_version")


def compare_reports(reports):
    reports = list(reports)
    if len(reports) < 2:
        raise ValueError("At least two reports are needed for comparison")
    baseline = reports[0]
    for key in COMPARABILITY_FIELDS:
        if key not in baseline:
            raise ValueError(f"Report lacks comparison contract: {key}")
    expected_ids = [e["case_id"] for e in baseline["episodes"]]
    if not expected_ids or len(expected_ids) != len(set(expected_ids)):
        raise ValueError("Case list must be nonempty and unique")
    for report in reports:
        for key in COMPARABILITY_FIELDS:
            if report.get(key) != baseline[key]:
                raise ValueError(f"Cannot compare different {key}: {report.get(key)!r} vs {baseline[key]!r}")
        if [e["case_id"] for e in report["episodes"]] != expected_ids:
            raise ValueError("Every report must include every case in the same order, including failures")
        if [e["initial_state"] for e in report["episodes"]] != [e["initial_state"] for e in baseline["episodes"]]:
            raise ValueError("Explicit initial states differ")
        recorded_cases = [{key: episode[key] for key in ("case_id", "split", "seed", "initial_state")}
                          for episode in report["episodes"]]
        if canonical_hash(recorded_cases) != report["cases_hash"]:
            raise ValueError("Recorded episodes do not match the frozen case hash; cases may be missing")
    return dict(schema_version=1, comparison_contract={key: baseline[key] for key in COMPARABILITY_FIELDS},
                methods=[dict(controller=report["controller"], controller_sha256=report.get("controller_sha256"),
                              aggregate=report["aggregate"], episodes=report["episodes"]) for report in reports],
                interpretation="Compare completion and failures before angle/force metrics; no universal winner is inferred.")
