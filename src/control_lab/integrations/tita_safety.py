"""Deterministic L32 experiments against a simulated command gate, never hardware.

The gate sits in front of a mock actuator accepting normalized policy commands.
It does not stand in for Isaac's joint drives or a robot's certified stop circuit.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path

from .tita_interface import load_interface


class MockCommandGate:
    def __init__(self, dimensions, *, limit=1.0, timeout_s=0.06):
        if not isinstance(dimensions, int) or dimensions < 1:
            raise ValueError("dimensions must be a positive integer")
        if not all(math.isfinite(x) and x > 0 for x in (limit, timeout_s)):
            raise ValueError("limit and timeout must be finite and positive")
        self.dimensions, self.limit, self.timeout_s = dimensions, float(limit), float(timeout_s)
        self._command = (0.0,) * dimensions
        self._received_at = None
        self._clock = 0.0
        self.emergency_latched = False

    def _time(self, now_s):
        if not math.isfinite(now_s) or now_s < self._clock:
            raise ValueError("time must be finite and monotonic")
        self._clock = now_s

    def receive(self, command, now_s):
        self._time(now_s)
        try:
            command = tuple(float(v) for v in command)
        except (TypeError, ValueError, OverflowError) as exc:
            self.stop(now_s)
            raise ValueError("command must contain numeric values") from exc
        if len(command) != self.dimensions or not all(math.isfinite(v) for v in command):
            self.stop(now_s)
            raise ValueError("command must have the configured dimension and finite values")
        if self.emergency_latched:
            return False
        self._command = tuple(max(-self.limit, min(self.limit, v)) for v in command)
        self._received_at = now_s
        return True

    def stop(self, now_s):
        self._time(now_s)
        self._command = (0.0,) * self.dimensions
        self._received_at = None

    def emergency_stop(self, now_s):
        self.stop(now_s)
        self.emergency_latched = True

    def rearm(self, now_s, *, explicit=False):
        self._time(now_s)
        if explicit is not True:
            raise ValueError("rearm requires an explicit operator action")
        self.stop(now_s)
        self.emergency_latched = False

    def sample(self, now_s):
        self._time(now_s)
        if self.emergency_latched:
            return (0.0,) * self.dimensions, False, "emergency_stop"
        if self._received_at is None:
            return (0.0,) * self.dimensions, False, "stopped"
        if now_s - self._received_at >= self.timeout_s - 1e-12:
            self.stop(now_s)
            return (0.0,) * self.dimensions, False, "timeout"
        return self._command, True, "active"


def run_safety_experiment(interface_path, output_dir, *, gate_factory=MockCommandGate):
    interface_path = Path(interface_path).resolve()
    interface = load_interface(interface_path)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=False)
    dimensions = len(interface["actions"])
    dt = interface["control_dt_s"]
    limit, timeout = 1.0, 3 * dt
    traces, cases = [], []

    def run(name, events, expectations):
        gate = gate_factory(dimensions, limit=limit, timeout_s=timeout)
        rows = []
        for step, (operation, command) in enumerate(events):
            now = step * dt
            accepted = None
            if operation == "command": accepted = gate.receive(command, now)
            elif operation == "stop": gate.stop(now)
            elif operation == "emergency_stop": gate.emergency_stop(now)
            elif operation == "rearm": gate.rearm(now, explicit=True)
            elif operation != "silence": raise ValueError(operation)
            values, enabled, reason = gate.sample(now)
            row = dict(case=name, step=step, time_s=now, operation=operation, requested=command,
                       accepted=accepted, output=list(values), actuator_enabled=enabled, reason=reason)
            rows.append(row)
            traces.append(row)
        failures = []
        for step, expected_values, expected_enabled in expectations:
            row = rows[step]
            if row["output"] != expected_values or row["actuator_enabled"] != expected_enabled:
                failures.append(dict(step=step, expected_output=expected_values, expected_enabled=expected_enabled,
                                     actual_output=row["output"], actual_enabled=row["actuator_enabled"]))
        cases.append(dict(case_id=name, passed=not failures, checked_steps=[e[0] for e in expectations],
                          failures=failures, recorded_steps=len(rows)))

    zero = [0.0] * dimensions
    positive = [0.5] * dimensions
    excessive = [3.0 if i % 2 == 0 else -3.0 for i in range(dimensions)]
    bounded = [1.0 if i % 2 == 0 else -1.0 for i in range(dimensions)]
    run("action_limit", [("command", excessive), ("command", positive)], [(0, bounded, True), (1, positive, True)])
    run("timeout_zero", [("command", positive)] + [("silence", None)] * 6,
        [(0, positive, True), (2, positive, True), (3, zero, False), (6, zero, False)])
    run("stop_zero", [("command", positive), ("stop", None), ("silence", None)],
        [(0, positive, True), (1, zero, False), (2, zero, False)])
    run("emergency_latch", [("command", positive), ("emergency_stop", None), ("command", excessive),
                             ("silence", None), ("rearm", None), ("command", positive)],
        [(0, positive, True), (1, zero, False), (2, zero, False), (3, zero, False), (4, zero, False), (5, positive, True)])
    trace_path = output / "trace.csv"
    with trace_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(traces[0]))
        writer.writeheader()
        for row in traces:
            writer.writerow({**row, "requested": json.dumps(row["requested"]), "output": json.dumps(row["output"])})
    report = dict(schema_version=1, kind="tita_mock_safety_experiment", experiment_id="tita-command-gate-v1",
        passed=all(case["passed"] for case in cases), cases=cases, trace_rows=len(traces),
        configuration=dict(action_dim=dimensions, raw_action_limit=limit, raw_action_unit="dimensionless",
                           control_dt_s=dt, timeout_s=timeout, timeout_steps=3, clock="deterministic simulated time"),
        interface_path=str(interface_path), interface_sha256=interface["interface_sha256"],
        trace_file="trace.csv", trace_sha256=hashlib.sha256(trace_path.read_bytes()).hexdigest(),
        hardware_control=False, ready_for_hardware=False, simulation="mock command gate and mock enabled/disabled actuator only",
        boundary="No Isaac joint dynamics, ROS transport, motor firmware or hardware stop was tested. Raw zero alone is not motor disable; this mock separately disables its actuator.",
        zero_action_note=interface["zero_action_note"])
    path = output / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path, report
