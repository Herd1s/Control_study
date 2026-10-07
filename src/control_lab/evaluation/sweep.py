"""Evaluate every parameter combination on the same practice/validation cases."""
from itertools import product
import json
from pathlib import Path

from .batch import evaluate
from .compare import compare_reports
from .protocol import load_protocol


def sweep(controller_factory, parameter_grid, protocol=None, *, output_dir=None):
    protocol = protocol or load_protocol()
    if protocol.split == "held_out":
        raise ValueError("Parameter tuning must not use the held-out split")
    if not parameter_grid:
        raise ValueError("Provide at least one parameter and its candidate values")
    names = list(parameter_grid)
    choices = [list(parameter_grid[name]) for name in names]
    if any(not values for values in choices):
        raise ValueError("Every parameter needs at least one candidate")
    count = 1
    for values in choices:
        count *= len(values)
    if count > 1000:
        raise ValueError("A classroom sweep is limited to 1000 explicit combinations")
    destination = Path(output_dir) if output_dir is not None else None
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        if any(destination.iterdir()):
            raise FileExistsError("Sweep output must be empty")
    results, reports = [], []
    for index, values in enumerate(product(*choices)):
        parameters = dict(zip(names, values))
        report = evaluate(lambda: controller_factory(**parameters), protocol,
                          controller_name=f"candidate-{index:03d} {parameters}",
                          output_dir=destination / f"candidate-{index:03d}" if destination else None)
        results.append(dict(parameters=parameters, report=report))
        reports.append(report)
    comparison = compare_reports(reports) if len(reports) > 1 else None
    # No scalar score conceals failures. Return all results in requested order.
    result = dict(schema_version=1, protocol_hash=protocol.protocol_hash,
                  cases_hash=protocol.cases_hash, split=protocol.split,
                  candidates=results, comparison=comparison)
    if destination:
        (destination / "sweep.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
