"""Frozen explicit nonzero cases. Seeds are provenance, not reset instructions."""
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json


def canonical_hash(value) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    split: str
    seed: int
    initial_state: tuple[float, float, float, float]

    def as_dict(self):
        return dict(case_id=self.case_id, split=self.split, seed=self.seed,
                    initial_state=list(self.initial_state))


@dataclass(frozen=True)
class EvaluationProtocol:
    definition_json: str
    split: str = "validation"

    def __post_init__(self):
        from control_lab.controllers._common import state_values

        definition = self.definition
        if self.split not in ("practice", "validation", "held_out"):
            raise ValueError("split must be practice, validation, or held_out")
        if definition.get("protocol_id") != "balance-v1" or definition.get("schema_version") != 1:
            raise ValueError("Unsupported evaluation protocol")
        cases = definition["cases"]
        if canonical_hash(cases) != definition["case_table_sha256"]:
            raise ValueError("Frozen case table hash mismatch")
        ids, seeds = set(), set()
        expected = {"practice": set(range(42, 47)), "validation": set(range(100, 120)),
                    "held_out": set(range(10042, 10062))}
        actual = {name: set() for name in expected}
        for case in cases:
            if case["case_id"] in ids or case["seed"] in seeds:
                raise ValueError("Case IDs and seeds must be unique across splits")
            ids.add(case["case_id"])
            seeds.add(case["seed"])
            if case["split"] not in actual:
                raise ValueError("Unknown case split")
            actual[case["split"]].add(case["seed"])
            state = state_values(case["initial_state"])
            if abs(state[2]) < 0.01 or any(abs(value) > 0.05 for value in state):
                raise ValueError("balance-v1 requires fixed visible nonzero initial deviations")
        if actual != expected:
            raise ValueError("balance-v1 split membership is frozen")
        expected_physics = dict(gravity_m_s2=9.8, cart_mass_kg=1.0, pole_mass_kg=0.1,
                                pole_half_length_m=0.5, integrator="euler", dt_s=0.02)
        if definition["physics"] != expected_physics:
            raise ValueError("Changing balance-v1 physics requires a new protocol")
        if definition["input_mode"] != "force_n" or definition["force_limit_n"] != 10.0:
            raise ValueError("balance-v1 accepts force_n with a 10 N actuator limit only")
        if definition["max_steps"] != 500 or definition["x_limit_m"] != 2.4:
            raise ValueError("balance-v1 boundaries are frozen")
        if definition["theta_limit_rad"] != 0.20943951023931953:
            raise ValueError("balance-v1 uses the fixed 12 degree threshold")
        if definition["observation"] != dict(fields=["x", "v", "theta", "omega"],
                                              dtype="float32", noise="none", delay_steps=0):
            raise ValueError("Changing observation rights requires a new protocol")
        if definition["reward_id"] != "survival-v1" or definition["disturbances"]:
            raise ValueError("balance-v1 reward and disturbance settings are frozen")

    @property
    def definition(self):
        return json.loads(self.definition_json)

    @property
    def protocol_id(self):
        return self.definition["protocol_id"]

    @property
    def protocol_hash(self):
        return canonical_hash(self.definition)

    @property
    def cases(self):
        return tuple(BenchmarkCase(case["case_id"], case["split"], case["seed"],
                                   tuple(case["initial_state"]))
                     for case in self.definition["cases"] if case["split"] == self.split)

    @property
    def cases_hash(self):
        return canonical_hash([case.as_dict() for case in self.cases])

    def spec_for(self, case):
        from control_lab.core.scenario import ScenarioConfig
        from control_lab.core.types import EpisodeSpec, State

        if case not in self.cases:
            raise ValueError("Case does not belong to this protocol split")
        definition = self.definition
        scenario = ScenarioConfig(scenario_id=case.case_id,
                                  initial_state=State(*case.initial_state),
                                  initial_state_seed=case.seed,
                                  observation_noise_seed=case.seed,
                                  cart_mass_kg=definition["physics"]["cart_mass_kg"],
                                  pole_mass_kg=definition["physics"]["pole_mass_kg"],
                                  half_pole_length_m=definition["physics"]["pole_half_length_m"],
                                  gravity_m_s2=definition["physics"]["gravity_m_s2"])
        return EpisodeSpec(protocol_id=self.protocol_id, scenario=scenario,
                           dt_s=definition["physics"]["dt_s"],
                           force_limit_n=definition["force_limit_n"],
                           max_steps=definition["max_steps"],
                           theta_limit_rad=definition["theta_limit_rad"],
                           x_limit_m=definition["x_limit_m"], require_nonzero_initial=True)


def load_protocol(protocol_id="balance-v1", *, split="validation") -> EvaluationProtocol:
    if protocol_id != "balance-v1":
        raise ValueError("Only the frozen balance-v1 protocol is currently supported")
    data = files("control_lab.evaluation").joinpath("assets", "balance-v1.json").read_text(encoding="utf-8")
    return EvaluationProtocol(data, split)
