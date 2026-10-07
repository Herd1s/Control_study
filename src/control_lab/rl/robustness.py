"""L29 fixed-policy, one-factor-at-a-time study; separate from balance-v1 scores."""
import csv
from dataclasses import asdict, replace
import html
import math
from pathlib import Path

from control_lab.core.session import EpisodeSession
from control_lab.core.scenario import ForcePulse
from control_lab.evaluation import load_protocol
from control_lab.evaluation.metrics import episode_metrics, aggregate_metrics
from control_lab.evaluation.protocol import canonical_hash
from .artifacts import atomic_json
from .evaluate import load_policy_adapter, StopRequested

FACTOR_DEFINITIONS = {
    "baseline": {"label": "原始条件", "changes": {}},
    "observation_delay_1": {"label": "观测延迟20 ms", "changes": {"observation_delay_steps": 1}},
    "observation_delay_2": {"label": "观测延迟40 ms", "changes": {"observation_delay_steps": 2}},
    "measurement_theta_noise": {"label": "角度噪声0.002 rad", "changes": {"observation_noise_std": (0., 0., .002, 0.), "observation_noise_seed": 2026}},
    "pole_mass_minus10": {"label": "杆质量−10%", "changes": {"pole_mass_kg": .09}},
    "pole_mass_plus10": {"label": "杆质量+10%", "changes": {"pole_mass_kg": .11}},
    "external_force_pulse": {"label": "2秒时外力1 N持续0.1秒", "changes": {"disturbances": (ForcePulse(100, 5, 1.),)}},
}


def factor_definition(factor):
    """JSON-safe declaration while runtime specifications retain typed pulses."""
    definition = FACTOR_DEFINITIONS[factor]
    return {"label": definition["label"], "changes": {
        key: [asdict(item) for item in value] if key == "disturbances" else value
        for key, value in definition["changes"].items()}}


class FrozenPD:
    def __init__(self, gains=(60., 12., 2., 3.)):
        self.gains = tuple(float(value) for value in gains)
        if len(self.gains) != 4 or any(not math.isfinite(value) or abs(value) > 1000 for value in self.gains):
            raise ValueError("PD gains must be four finite values within ±1000")

    def reset(self):
        pass

    def act(self, state, dt):
        x, v, theta, omega = state
        a, b, c, d = self.gains
        return a*theta+b*omega+c*x+d*v

    def evaluation_identity(self):
        return {"kind": "frozen_pd", "formula": "F=a*theta+b*omega+c*x+d*v",
                "gains_order": ["theta", "omega", "x", "v"], "gains": list(self.gains), "output": "N"}


def robustness_spec(protocol, case, factor):
    if factor not in FACTOR_DEFINITIONS:
        raise ValueError("未知鲁棒性因素")
    original = protocol.spec_for(case)
    scenario = replace(original.scenario, scenario_id=f"{factor}-{case.case_id}",
                       **FACTOR_DEFINITIONS[factor]["changes"])
    return replace(original, protocol_id="robustness-practice-v1", scenario=scenario)


def _state_fields(prefix, state):
    return dict(zip((prefix+"x_m", prefix+"v_m_s", prefix+"theta_rad", prefix+"omega_rad_s"), state))


def run_robustness(controller, output_dir, *, identity, factors=None, stop_file=None, progress=None):
    """Trusted controller entry for deterministic tests; student source uses its own worker."""
    factors = tuple(FACTOR_DEFINITIONS if factors is None else factors)
    if not factors or len(factors) != len(set(factors)) or set(factors)-set(FACTOR_DEFINITIONS):
        raise ValueError("请选择不重复的受支持因素")
    protocol = load_protocol("balance-v1", split="practice")
    definition = {"study_id": "robustness-practice-v1", "base_protocol_hash": protocol.protocol_hash,
        "base_cases_hash": protocol.cases_hash, "cases": [case.as_dict() for case in protocol.cases],
        "factors": {key: factor_definition(key) for key in factors},
        "delay_initialization": "initial observation repeated; no invented pre-episode motion",
        "input_mode": "force_n", "controller_identity": identity}
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "kind": "robustness_study", "status": "running",
        "definition": definition, "study_hash": canonical_hash(definition), "groups": [],
        "policy_updated": False, "standard_balance_score": False,
        "interpretation": "冻结同一控制器、相同5个练习初态，每组只改变一个因素。结果为独立鲁棒性研究，不混入标准balance-v1成绩；未重新训练。"}
    atomic_json(destination/"report.json", report)
    completed = 0
    try:
        for factor in factors:
            episodes = []
            group = {"factor": factor, "label": FACTOR_DEFINITIONS[factor]["label"], "episodes": episodes}
            report["groups"].append(group)
            for case in protocol.cases:
                if stop_file and Path(stop_file).exists():
                    raise StopRequested()
                spec = robustness_spec(protocol, case, factor)
                folder = destination / factor / case.case_id
                folder.mkdir(parents=True, exist_ok=False)
                atomic_json(folder/"spec.json", asdict(spec))
                rows, error, end_reason = [], None, None
                try:
                    controller.reset()
                    with EpisodeSession(spec) as session:
                        while not session.finished:
                            if stop_file and Path(stop_file).exists():
                                raise StopRequested()
                            observed = session.observed_state
                            force = float(controller.act(observed, session.dt))
                            if not math.isfinite(force):
                                raise ValueError("控制器返回非有限推力")
                            result = session.step(force)
                            rows.append({"step_id": result.step_id, "time_s": result.simulation_time_s,
                                **_state_fields("true_", result.true_state), **_state_fields("observed_", observed),
                                "requested_force_n": result.requested_force_n, "actuator_force_n": result.actuator_force_n,
                                "reward": result.reward, "terminated": result.terminated, "truncated": result.truncated})
                            end_reason = result.end_reason
                except StopRequested:
                    end_reason = "cancelled"
                    raise
                except Exception as exc:
                    error = {"type": type(exc).__name__, "message": str(exc)}
                    end_reason = "controller_error"
                finally:
                    with (folder/"trajectory.csv").open("x", encoding="utf-8", newline="") as stream:
                        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["step_id", "time_s"])
                        writer.writeheader()
                        writer.writerows(rows)
                    metrics = episode_metrics(rows, initial_state=case.initial_state, max_steps=spec.max_steps,
                        dt_s=spec.dt_s, force_limit_n=spec.force_limit_n, end_reason=end_reason, error=error)
                    episode = {**case.as_dict(), **metrics, "spec_hash": canonical_hash(asdict(spec)),
                               "trajectory": str(Path(factor)/case.case_id/"trajectory.csv")}
                    episodes.append(episode)
                    atomic_json(folder/"metrics.json", episode)
                completed += 1
                group["aggregate"] = aggregate_metrics(episodes)
                atomic_json(destination/"report.json", report)
                if progress:
                    progress({"factor": factor, "case_id": case.case_id, "completed": completed,
                              "label": FACTOR_DEFINITIONS[factor]["label"],
                              "total": len(factors)*len(protocol.cases), "episode": episode})
        report["status"] = "completed"
    except StopRequested:
        report["status"] = "stopped"
    finally:
        for group in report["groups"]:
            if group["episodes"]:
                group["aggregate"] = aggregate_metrics(group["episodes"])
        atomic_json(destination/"report.json", report)
        _write_report_html(report, destination/"report.html")
    return report


def _write_report_html(report, path):
    rows = []
    details = []
    for group in report["groups"]:
        aggregate = group.get("aggregate")
        if not aggregate:
            continue
        episodes = group["episodes"]
        mean = lambda key: sum(float(item[key] or 0) for item in episodes)/len(episodes)
        label = (group.get("method_label", "") + " · " + group['label']).strip(" ·")
        rows.append(f"<tr><td>{html.escape(label)}</td><td>{aggregate['completed_episodes']}/{aggregate['episodes']}</td>"
            f"<td>{aggregate['mean_steps']:.1f}</td><td>{aggregate['worst_steps']}</td><td>{mean('rms_theta_rad'):.4g}</td>"
            f"<td>{max(e['max_abs_x_m'] for e in episodes):.4g}</td><td>{mean('rms_actuator_force_n'):.4g}</td>"
            f"<td>{mean('saturation_fraction'):.1%}</td></tr>")
        for episode in episodes:
            details.append(f"<tr><td>{html.escape(label)}</td><td>{episode['case_id']}</td>"
                f"<td>{episode['episode_steps']}</td><td>{html.escape(episode['end_reason'])}</td>"
                f"<td><a href='{html.escape(episode['trajectory'])}'>逐步CSV</a></td></tr>")
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>固定策略鲁棒性</title>'
        '<style>body{max-width:1120px;margin:30px auto;padding:0 20px;background:#f5f6f1;color:#284137;font:16px "Microsoft YaHei UI",sans-serif}'
        'section{background:white;border-radius:14px;margin:20px 0;padding:20px}table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:9px;border-bottom:1px solid #e0e8e1}p{line-height:1.7}</style>'
        '<h1>同一策略遇到变化后，会发生什么？</h1><p>'+html.escape(report["interpretation"])+
        f'</p><p>本次状态：{html.escape(report["status"])}；中途停止的研究不算完整组。</p><section><table><tr><th>唯一变化</th><th>完成回合</th><th>平均步数</th><th>最短步数</th><th>角度RMS rad</th><th>最大位移 m</th><th>力RMS N</th><th>饱和比例</th></tr>'+
        ''.join(rows)+'</table></section><section><h2>每一次失败也保留</h2><table><tr><th>组</th><th>用例</th><th>步数</th><th>结束原因</th><th>轨迹</th></tr>'+
        ''.join(details)+'</table></section></html>')
    path.write_text(page, encoding="utf-8")


def evaluate_robustness(artifact_dir, output_dir, *, factors=None, stop_file=None, progress=None):
    controller = load_policy_adapter(artifact_dir, stop_file=stop_file)
    return run_robustness(controller, output_dir, identity=controller.evaluation_identity(),
                          factors=factors, stop_file=stop_file, progress=progress)


def run_paired_robustness(controllers, output_dir, *, identities, factors=None, stop_file=None, progress=None):
    """Compare frozen methods on identical specs; never infer fairness from a single live run."""
    factors = tuple(FACTOR_DEFINITIONS if factors is None else factors)
    if set(controllers) != set(identities) or not controllers:
        raise ValueError("Each frozen method needs its own identity")
    if any(not key.isidentifier() for key in controllers):
        raise ValueError("Method names must be simple identifiers")
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    protocol = load_protocol(split="practice")
    definition = {"study_id": "paired-robustness-practice-v1", "base_protocol_hash": protocol.protocol_hash,
        "base_cases_hash": protocol.cases_hash, "cases": [case.as_dict() for case in protocol.cases],
        "factors": {key: factor_definition(key) for key in factors}, "methods": identities,
        "input_mode": "force_n", "pairing": "identical explicit EpisodeSpec and observation noise seed for each method"}
    report = {"schema_version": 1, "kind": "robustness_comparison", "status": "running",
        "definition": definition, "study_hash": canonical_hash(definition), "groups": [],
        "policy_updated": False, "standard_balance_score": False,
        "interpretation": "冻结PD参数与PPO模型，在完全相同5个练习初态、噪声seed和场景上运行；每组只改变一个因素。保留全部失败，不训练，不混入标准balance-v1成绩。"}
    count = len(factors)*len(protocol.cases)
    atomic_json(destination/"report.json", report)
    expected_specs = {}
    for method_index, (method, controller) in enumerate(controllers.items()):
        result = run_robustness(controller, destination/method, identity=identities[method], factors=factors,
            stop_file=stop_file, progress=(lambda item, index=method_index, name=method:
                progress({**item, "method": name, "completed": index*count+item["completed"],
                          "total": count*len(controllers)}) if progress else None))
        for group in result["groups"]:
            group = {**group, "method": method, "method_label": method.upper(), "episodes": [
                {**episode, "trajectory": str(Path(method)/episode["trajectory"])} for episode in group["episodes"]]}
            for episode in group["episodes"]:
                key = (group["factor"], episode["case_id"])
                if key in expected_specs and expected_specs[key] != episode["spec_hash"]:
                    raise ValueError("Paired methods did not use identical EpisodeSpecs")
                expected_specs[key] = episode["spec_hash"]
            report["groups"].append(group)
        if result["status"] != "completed":
            report["status"] = "stopped"
            break
        atomic_json(destination/"report.json", report)
    else:
        report["status"] = "completed"
    report["paired_specs_verified"] = report["status"] == "completed"
    atomic_json(destination/"report.json", report)
    _write_report_html(report, destination/"report.html")
    return report


def compare_model_robustness(artifact_dir, output_dir, *, pd_gains=(60., 12., 2., 3.), stop_file=None, progress=None):
    ppo = load_policy_adapter(artifact_dir, stop_file=stop_file)
    pd = FrozenPD(pd_gains)
    report = run_paired_robustness({"pd": pd, "ppo": ppo}, output_dir,
        identities={"pd": pd.evaluation_identity(), "ppo": ppo.evaluation_identity()},
        stop_file=stop_file, progress=progress)
    a, b, c, d = pd.gains
    (Path(output_dir)/"pd_controller.py").write_text(
        f'def control(state, dt):\n    return {a!r}*state["theta"] + {b!r}*state["omega"] + {c!r}*state["x"] + {d!r}*state["v"]\n', encoding="utf-8")
    return report
