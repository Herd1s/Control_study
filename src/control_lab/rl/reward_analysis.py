"""Versioned reward comparison on immutable saved trajectories, without training."""
import csv
import hashlib
import html
import json
import math
from pathlib import Path

from control_lab.evaluation.protocol import canonical_hash
from .rewards import normalize_reward_config, components_for_config


def read_reward_trajectory(path):
    path = Path(path).resolve()
    if path.stat().st_size > 32_000_000:
        raise ValueError("轨迹超过32 MB，请选一轮实验")
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = set(reader.fieldnames or ())
        if {"simulation_time_s", "true_theta", "true_x", "actuator_force_n"} <= fields:
            schema, time_key, theta_key, x_key = "interactive-post-v1", "simulation_time_s", "true_theta", "true_x"
        elif {"time_s", "true_theta_rad", "true_x_m", "actuator_force_n"} <= fields:
            schema, time_key, theta_key, x_key = "evaluation-post-v1", "time_s", "true_theta_rad", "true_x_m"
        else:
            raise ValueError("请选择包含真实状态和实际执行器推力的课堂或评价轨迹CSV")
        rows, episodes = [], set()
        for index, source in enumerate(reader):
            if index >= 20_000:
                raise ValueError("每次最多分析20,000步")
            values = [float(source[key]) for key in (time_key, theta_key, x_key, "actuator_force_n")]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("轨迹含无效数值")
            step = int(source.get("step_id", index))
            if rows and step != rows[-1]["step_id"]+1:
                raise ValueError("轨迹步序不连续，不能混入多回合")
            if source.get("episode_id"):
                episodes.add(source["episode_id"])
            rows.append(dict(step_id=step, time_s=values[0], theta=values[1], x=values[2], force_n=values[3]))
    if not rows or len(episodes) > 1:
        raise ValueError("请选择单一非空回合")
    dt = rows[1]["time_s"]-rows[0]["time_s"] if len(rows) > 1 else None
    if dt is not None and (dt <= 0 or any(not math.isclose(b["time_s"]-a["time_s"], dt, abs_tol=1e-8)
                                         for a, b in zip(rows, rows[1:]))):
        raise ValueError("时间戳必须连续、递增且固定步长")
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "schema": schema, "samples": len(rows), "dt_s": dt,
            "state_timing": "true post-action state and actual actuator force", "rows": rows}


def rescore_rows(rows, config):
    config = normalize_reward_config(config)
    totals = dict(survival=0.0, angle=0.0, position=0.0, effort=0.0)
    values = []
    for row in rows:
        parts = components_for_config(config, row, row["force_n"])
        for key, value in parts.items():
            totals[key] += value
        values.append({"step_id": row["step_id"], "time_s": row["time_s"], **parts,
                       "reward": math.fsum(parts.values()), "cumulative_return": math.fsum(totals.values())})
    return {"reward_config": config, "reward_hash": canonical_hash(config), "parts": totals,
            "return": math.fsum(totals.values()), "samples": len(values), "rows": values}


def _plot(series, *, value_key="cumulative_return", label="按实际时间绘制的累计回报"):
    palette = ("#56887d", "#e3a158", "#5886b4", "#ac75a3", "#768952", "#be6c59")
    width, height, pad = 840, 280, 48
    xmax = max(item["rows"][-1]["time_s"] for item in series)
    ymin = min(0, min(row[value_key] for item in series for row in item["rows"]))
    ymax = max(1, max(row[value_key] for item in series for row in item["rows"]))
    elements = [f'<svg viewBox="0 0 840 280" role="img" aria-label="{html.escape(label)}">']
    for k in range(5):
        y = pad+(height-2*pad)*k/4
        value = ymax-(ymax-ymin)*k/4
        elements.append(f'<line x1="{pad}" y1="{y}" x2="{width-pad}" y2="{y}" stroke="#e3e9e4"/>')
        elements.append(f'<text x="3" y="{y+4}" fill="#586c65" font-size="12">{value:.3g}</text>')
    legend = []
    for index, item in enumerate(series):
        color = palette[index % len(palette)]
        points = " ".join(f'{pad+row["time_s"]/max(xmax,1e-6)*(width-2*pad):.2f},'
                          f'{pad+(ymax-row[value_key])/(ymax-ymin)*(height-2*pad):.2f}' for row in item["rows"])
        label = html.escape(item["label"])
        elements.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{points}"><title>{label}</title></polyline>')
        legend.append(f'<span style="color:{color}">● {label}</span>')
    elements.append(f'<text x="{pad}" y="{height-12}" font-size="12">0 s</text>'
                    f'<text x="{width-pad-38}" y="{height-12}" font-size="12">{xmax:.2f} s</text></svg>')
    return "".join(elements)+'<div class="legend">'+"".join(legend)+"</div>"


def analyze_rewards(trajectories, configurations, output_dir):
    paths, configs = list(trajectories), [normalize_reward_config(c) for c in configurations]
    if not 1 <= len(paths) <= 2 or not 1 <= len(configs) <= 3:
        raise ValueError("请选择1–2份轨迹和1–3种奖励配置")
    if len({config["reward_id"] for config in configs}) != len(configs):
        raise ValueError("每种奖励声明需要不同的版本名")
    records = [read_reward_trajectory(path) for path in paths]
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    results, plotted = [], []
    for index, record in enumerate(records, 1):
        for config in configs:
            result = rescore_rows(record["rows"], config)
            filename = f"trajectory-{index}-{config['reward_id']}.csv"
            with (destination/filename).open("x", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(result["rows"][0]))
                writer.writeheader()
                writer.writerows(result["rows"])
            plotted.append({"label": f"轨迹{index} / {config['reward_id']}", "rows": result.pop("rows")})
            results.append({"trajectory_index": index, "source_sha256": record["sha256"], **result, "csv": filename})
    report = {"schema_version": 1, "kind": "reward_analysis", "rollout_unchanged": True,
              "policy_updated": False, "trajectories": [{k:v for k,v in item.items() if k != "rows"} for item in records],
              "results": results,
              "interpretation": "只给相同已保存状态与实际推力重新计分，未重新运行或训练策略。累计回报也受回合长度影响；不同奖励版本的回报不能作为同一尺度直接横比。"}
    (destination/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    table = "".join('<tr><td>'+str(result["trajectory_index"])+"</td><td>"+html.escape(result["reward_config"]["reward_id"])+"</td>"+
        "".join(f'<td>{result["parts"][key]:.5g}</td>' for key in ("survival", "angle", "position", "effort"))+
        f'<td>{result["return"]:.5g}</td></tr>' for result in results)
    components = []
    for item in plotted:
        traces = [{"label": name, "rows": [{"time_s": row["time_s"], "value": row[key]} for row in item["rows"]]}
                  for key, name in (("survival", "存活"), ("angle", "角度"), ("position", "位置"), ("effort", "用力"))]
        components.append('<details><summary>'+html.escape(item["label"])+
                          '</summary>'+_plot(traces, value_key="value", label="每一步的四项奖励分量")+'</details>')
    page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>同轨迹奖励对照</title>'
        '<style>body{background:#f5f6f1;color:#263f38;font:16px "Microsoft YaHei UI",sans-serif;margin:28px auto;max-width:1040px;padding:0 20px}'
        'section{background:white;border-radius:14px;padding:22px;margin:20px 0}p{line-height:1.7}table{width:100%;border-collapse:collapse}td,th{padding:10px;border-bottom:1px solid #e1e9e4;text-align:left}svg{width:100%;height:auto}.legend{display:flex;flex-wrap:wrap;gap:16px}</style>'
        '<h1>同一条轨迹，为什么分数变了？</h1><p>'+html.escape(report["interpretation"])+
        '</p><section><h2>奖励分量与总分</h2><table><tr><th>轨迹</th><th>奖励版本</th><th>存活</th><th>角度</th><th>位置</th><th>用力</th><th>累计回报</th></tr>'+
        table+'</table></section><section><h2>累计回报随时间变化</h2>'+_plot(plotted)+
        '</section><section><h2>每一步的奖励分量</h2><p>展开同一轨迹的不同版本：动作和状态不变，用力惩罚的幅度随权重变化。</p>'+''.join(components)+'</section></html>')
    (destination/"report.html").write_text(page, encoding="utf-8")
    return {"type": "reward_analysis", "status": "completed", "path": str(destination/"report.json"),
            "html": str(destination/"report.html"), "trajectories": len(records),
            "config_ids": [config["reward_id"] for config in configs], "report": report}
