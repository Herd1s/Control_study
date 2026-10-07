"""L20 experiments on recorded/synthetic signals, never a second physics rollout.

noise compares every method on exactly the same input record. kick is an
explicit target signal demonstration with a stationary measured angle; it does
not claim to simulate a controlled cart/pole or apply actuator saturation.
"""
import argparse
import csv
import hashlib
import html
import json
import math
from pathlib import Path

from control_lab.controllers.filters import FirstOrderLowPass, FilteredDerivative

MAX_SAMPLES = 20_000


def _finite(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _positive(value, name):
    value = _finite(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _tau(value):
    value = _finite(value, "tau_s")
    if value < 0:
        raise ValueError("tau_s cannot be negative")
    return value


def _rms(values):
    values = [float(v) for v in values if v is not None]
    return None if not values else math.sqrt(math.fsum(v*v for v in values)/len(values))


def _read_record(path, dt_s=None):
    path = Path(path).resolve()
    if path.stat().st_size > 32*1024*1024:
        raise ValueError("请选择一个回合的CSV，文件不能超过32 MB。")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if {"simulation_time_s", "observed_theta", "observed_omega", "true_theta", "true_omega"} <= fields:
            schema = "interactive-post-state-v1"
            time_key, theta_key, omega_key = "simulation_time_s", "observed_theta", "observed_omega"
            true_theta_key, true_omega_key = "true_theta", "true_omega"
        elif {"time_s", "observed_theta_rad", "observed_omega_rad_s", "true_theta_rad", "true_omega_rad_s"} <= fields:
            schema = "evaluation-pre-observation-v1"
            time_key, theta_key, omega_key = "time_s", "observed_theta_rad", "observed_omega_rad_s"
            true_theta_key, true_omega_key = "true_theta_rad", "true_omega_rad_s"
        else:
            raise ValueError("CSV不是受支持的课堂/评价轨迹；需要时间、真实角度/角速度与观测角度/角速度。")
        source = []
        for row in reader:
            if len(source) >= MAX_SAMPLES:
                raise ValueError(f"请选择一个不超过{MAX_SAMPLES}步的回合。")
            source.append(row)
    if len(source) < 2:
        raise ValueError("至少需要两个连续样本才能比较差分。")
    episode_ids = {row.get("episode_id") for row in source if row.get("episode_id")}
    if len(episode_ids) > 1:
        raise ValueError("不能跨回合差分；请选择单一回合的CSV。")
    times = [_finite(row[time_key], time_key) for row in source]
    inferred = times[1]-times[0]
    dt = _positive(inferred if dt_s is None else dt_s, "dt_s")
    tolerance = max(1e-9, dt*1e-6)
    if any(abs((right-left)-dt) > tolerance for left, right in zip(times, times[1:])):
        raise ValueError("记录不是连续固定步长，或输入的dt与记录不符；不能用错误时间做差分。")
    steps = []
    for index, row in enumerate(source):
        if row.get("step_id"):
            value = _finite(row["step_id"], "step_id")
            if value != int(value):
                raise ValueError("step_id必须为整数")
            steps.append(int(value))
        else:
            steps.append(index)
    if any(right-left != 1 for left, right in zip(steps, steps[1:])):
        raise ValueError("记录步序不连续，可能混入多回合或丢失样本。")
    rows = []
    for i, row in enumerate(source):
        # Interactive records use post-state observations. Formal evaluation
        # stores pre-action observations beside post-action true state. Align
        # evaluation truth to the previous row, never compare one step apart.
        reference = source[i-1] if schema == "evaluation-pre-observation-v1" and i else (
            row if schema == "interactive-post-state-v1" else None)
        rows.append({"sample_index": i, "time_s": times[i]-(dt if schema.startswith("evaluation") else 0),
            "measured_theta_rad": _finite(row[theta_key], theta_key),
            "measured_omega_rad_s": _finite(row[omega_key], omega_key),
            "true_theta_rad": _finite(reference[true_theta_key], true_theta_key) if reference else None,
            "true_omega_rad_s": _finite(reference[true_omega_key], true_omega_key) if reference else None})
    return path, schema, dt, rows


def compare_recorded_signals(trajectory, *, tau_s=0.05, dt_s=None):
    """Return JSON-ready analysis without writing files or changing the rollout."""
    tau_s = _tau(tau_s)
    path, schema, dt, rows = _read_record(trajectory, dt_s)
    raw_difference = FilteredDerivative(0.0)
    smoothed_difference = FirstOrderLowPass(tau_s)
    smoothed_sensor = FirstOrderLowPass(tau_s)
    smoothed_difference_noise = FirstOrderLowPass(tau_s)
    for index, row in enumerate(rows):
        calculated = raw_difference.update(row["measured_theta_rad"], dt)
        # The first derivative is unknown, not an artificial zero datapoint.
        difference = calculated if index else None
        previous_true = rows[index-1]["true_theta_rad"] if index else None
        clean_difference = None
        if previous_true is not None and row["true_theta_rad"] is not None:
            clean_difference = (row["true_theta_rad"]-previous_true)/dt
        row["difference_omega_rad_s"] = difference
        row["filtered_difference_omega_rad_s"] = (
            smoothed_difference.update(difference, dt) if difference is not None else None)
        row["filtered_sensor_omega_rad_s"] = smoothed_sensor.update(row["measured_omega_rad_s"], dt)
        row["true_theta_difference_rad_s"] = clean_difference
        row["theta_noise_rad"] = (row["measured_theta_rad"]-row["true_theta_rad"]
                                  if row["true_theta_rad"] is not None else None)
        row["sensor_omega_error_rad_s"] = (row["measured_omega_rad_s"]-row["true_omega_rad_s"]
                                            if row["true_omega_rad_s"] is not None else None)
        row["difference_noise_rad_s"] = difference-clean_difference if clean_difference is not None else None
        row["difference_total_error_rad_s"] = (difference-row["true_omega_rad_s"]
            if difference is not None and row["true_omega_rad_s"] is not None else None)
        row["filtered_difference_noise_rad_s"] = (
            smoothed_difference_noise.update(row["difference_noise_rad_s"], dt)
            if row["difference_noise_rad_s"] is not None else None)
    metrics = {"theta_noise_rms_rad": _rms(row["theta_noise_rad"] for row in rows),
               "direct_omega_error_rms_rad_s": _rms(row["sensor_omega_error_rad_s"] for row in rows),
               "difference_noise_rms_rad_s": _rms(row["difference_noise_rad_s"] for row in rows),
               "difference_total_error_rms_rad_s": _rms(row["difference_total_error_rad_s"] for row in rows),
               "filtered_difference_noise_rms_rad_s": _rms(row["filtered_difference_noise_rad_s"] for row in rows)}
    return {"schema_version": 1, "experiment": "same-record-signal-comparison", "source_schema": schema,
            "source_file": str(path), "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dt_s": dt, "tau_s": tau_s, "samples": len(rows), "rollout_unchanged": True,
            "filter": "causal exact-ZOH alpha=1-exp(-dt/tau); tau=0 bypass",
            "first_difference_sample": "unavailable, excluded from metrics",
            "alignment": ("observed time equals recorded time" if schema.startswith("interactive") else
                          "observed time=time_s-dt; true reference from previous row; first true reference unavailable"),
            "metrics": metrics, "rows": rows,
            "interpretation": "同一份记录，未重跑闭环。差分噪声项减去了同一真实角度记录的差分，避免把数值差分近似误差也说成测量噪声；该噪声项单独做因果滤波，从第一个可对齐样本开始。滤波减小抖动也引入滞后；本报告不是控制器评分。"}


def derivative_kick_signal(*, dt_s=0.02, target_jump_rad=0.02, jump_time_s=1.0,
                           duration_s=2.0, kd=12.0, tau_s=0.05):
    """Compare D(error) with D(measurement) on one identical independent signal."""
    dt, jump_time, duration = _positive(dt_s, "dt_s"), _positive(jump_time_s, "jump_time_s"), _positive(duration_s, "duration_s")
    jump, kd, tau = _finite(target_jump_rad, "target_jump_rad"), _finite(kd, "kd"), _tau(tau_s)
    count, jump_index = round(duration/dt)+1, round(jump_time/dt)
    if not math.isclose(jump_time/dt, jump_index, abs_tol=1e-8) or not math.isclose(duration/dt, count-1, abs_tol=1e-8):
        raise ValueError("目标跳变时间和总时长必须落在固定dt格点上。")
    if not 1 <= jump_index < count or count > MAX_SAMPLES:
        raise ValueError("跳变需位于采样范围内，样本总数不能超过限制。")
    de, dm = FilteredDerivative(0), FilteredDerivative(0)
    filtered_de, filtered_dm = FirstOrderLowPass(tau), FirstOrderLowPass(tau)
    rows = []
    for index in range(count):
        target, measured = (jump if index >= jump_index else 0.0), 0.0
        error = measured-target  # Match this course's theta - target convention.
        de_value, dm_value = de.update(error, dt), dm.update(measured, dt)
        error_d, measurement_d = kd*de_value, kd*dm_value
        rows.append({"sample_index": index, "time_s": index*dt,
            "target_theta_rad": target, "measured_theta_rad": measured, "error_rad": error,
            "error_d_n": error_d if index else None, "measurement_d_n": measurement_d if index else None,
            "filtered_error_d_n": filtered_de.update(error_d, dt),
            "filtered_measurement_d_n": filtered_dm.update(measurement_d, dt)})
    return {"schema_version": 1, "experiment": "independent-target-step", "dt_s": dt, "tau_s": tau,
            "target_jump_rad": jump, "jump_time_s": jump_time, "duration_s": duration, "kd_n_s_rad": kd,
            "samples": count, "plant_simulated": False, "actuator_saturation_applied": False,
            "error_convention": "measured_theta-target_theta", "rows": rows,
            "metrics": {"error_d_at_jump_n": rows[jump_index]["error_d_n"],
                        "expected_error_d_at_jump_n": -kd*jump/dt,
                        "measurement_d_peak_abs_n": max(abs(row["measurement_d_n"] or 0) for row in rows),
                        "filtered_error_d_peak_abs_n": max(abs(row["filtered_error_d_n"]) for row in rows)},
            "interpretation": "这是独立的目标/测量信号实验，测量角度保持0。目标阶跃进入误差差分，因此出现负尖峰；仅测量量求导不直接对目标求导。本实验不模拟小车，也不宣称任何PID参数已稳定。"}


def _write_html(report, path):
    if report["experiment"] == "same-record-signal-comparison":
        title = "同一条轨迹：测量、差分与滤波"
        charts = [("角度（rad）", [("measured_theta_rad", "测量角度"), ("true_theta_rad", "真实角度")]),
                  ("角速度（rad/s）", [("measured_omega_rad_s", "直接测量ω"), ("difference_omega_rad_s", "角度差分")]),
                  ("因果滤波（rad/s）", [("difference_omega_rad_s", "原始差分"), ("filtered_difference_omega_rad_s", "差分后滤波"), ("filtered_sensor_omega_rad_s", "直接ω滤波")])]
    else:
        title = "目标跳变：为什么会出现微分冲击"
        charts = [("目标与测量（rad）", [("target_theta_rad", "目标角度"), ("measured_theta_rad", "测量角度")]),
                  ("D项请求力（N）", [("error_d_n", "对误差求导"), ("measurement_d_n", "只对测量求导")]),
                  ("滤波后的D项（N）", [("filtered_error_d_n", "误差求导后滤波"), ("filtered_measurement_d_n", "测量求导后滤波")])]
    payload = json.dumps({"rows": report["rows"], "charts": charts}, ensure_ascii=False, allow_nan=False).replace("<", "\\u003c")
    metric_labels = {"theta_noise_rms_rad": "角度测量噪声 RMS（rad）",
        "direct_omega_error_rms_rad_s": "直接角速度测量误差 RMS（rad/s）",
        "difference_noise_rms_rad_s": "差分引入的噪声 RMS（rad/s）",
        "difference_total_error_rms_rad_s": "差分对真实角速度的总误差 RMS（rad/s，包含差分近似误差）",
        "filtered_difference_noise_rms_rad_s": "因果滤波后差分噪声 RMS（rad/s）",
        "error_d_at_jump_n": "目标跳变时误差 D 项（N）",
        "expected_error_d_at_jump_n": "公式预测的误差 D 项（N）",
        "measurement_d_peak_abs_n": "仅测量求导的 D 项最大绝对值（N）",
        "filtered_error_d_peak_abs_n": "滤波后误差 D 项最大绝对值（N）"}
    metrics = "".join(f"<li>{html.escape(metric_labels.get(key, key))}：<strong>{value:.6g}</strong></li>" for key, value in report["metrics"].items() if value is not None)
    page = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title><style>body{margin:0;background:#f5f6f1;color:#23373d;font:16px 'Microsoft YaHei UI',system-ui,sans-serif}main{max-width:1000px;margin:32px auto;padding:0 20px}h1{font-size:28px}p{line-height:1.7}section,.summary{background:white;border:1px solid #e1e7de;border-radius:14px;padding:20px;margin:18px 0}h2{font-size:18px;margin:0 0 10px}canvas{width:100%;height:250px;display:block}.legend{display:flex;gap:20px;flex-wrap:wrap}.legend span{padding:4px 0}button{border:1px solid #c8d8cf;background:white;border-radius:6px;padding:6px 12px;cursor:pointer}li{line-height:1.8;overflow-wrap:anywhere}.readout{min-height:24px;font-variant-numeric:tabular-nums;color:#58736a}</style>
<main><h1>__TITLE__</h1><p>__INTERPRETATION__</p><p>采样周期 __DT__ s；滤波时间常数 __TAU__ s。移动鼠标可查看同一时刻的各条曲线。</p><div id="charts"></div><details class="summary"><summary>查看本次计算指标</summary><ul>__METRICS__</ul></details></main>
<script>const data=__PAYLOAD__;const colors=['#df8b41','#2d8375','#4b80ac'];for(const [title,series] of data.charts){const section=document.createElement('section');section.innerHTML='<h2></h2><div class="legend"></div><canvas></canvas><div class="readout"></div>';section.querySelector('h2').textContent=title;document.getElementById('charts').appendChild(section);const legend=section.querySelector('.legend');series.forEach(([key,label],i)=>{let s=document.createElement('span');s.style.color=colors[i];s.textContent='● '+label;legend.appendChild(s)});const c=section.querySelector('canvas'),r=section.querySelector('.readout');let selected=null;function draw(){const ratio=window.devicePixelRatio||1,w=c.clientWidth,h=250;c.width=w*ratio;c.height=h*ratio;const ctx=c.getContext('2d');ctx.scale(ratio,ratio);const pad=54,top=15,bottom=h-32,x0=data.rows[0].time_s,x1=data.rows.at(-1).time_s;let lo=0,hi=0;for(const row of data.rows)for(const [key]of series){if(row[key]!==null&&Number.isFinite(row[key])){lo=Math.min(lo,row[key]);hi=Math.max(hi,row[key])}}if(hi===lo){hi+=1;lo-=1}const gap=(hi-lo)*.08;hi+=gap;lo-=gap;const X=t=>pad+(t-x0)/(x1-x0)*(w-pad-15),Y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);ctx.font='12px system-ui';ctx.strokeStyle='#e5ece6';ctx.fillStyle='#687f74';for(let k=0;k<=4;k++){const v=lo+k*(hi-lo)/4,y=Y(v);ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(w-15,y);ctx.stroke();ctx.fillText(v.toPrecision(3),2,y+4);const t=x0+k*(x1-x0)/4;ctx.fillText(t.toFixed(2)+'s',X(t)-12,h-8)}series.forEach(([key],i)=>{ctx.strokeStyle=colors[i];ctx.lineWidth=1.8;ctx.beginPath();let started=false;for(const row of data.rows){const v=row[key];if(v===null||!Number.isFinite(v)){started=false;continue}if(!started){ctx.moveTo(X(row.time_s),Y(v));started=true}else ctx.lineTo(X(row.time_s),Y(v))}ctx.stroke()});if(selected!==null){const row=data.rows[selected];ctx.strokeStyle='#23373d';ctx.setLineDash([3,4]);ctx.beginPath();ctx.moveTo(X(row.time_s),top);ctx.lineTo(X(row.time_s),bottom);ctx.stroke();ctx.setLineDash([]);r.textContent='t='+row.time_s.toFixed(3)+' s  '+series.map(([key,label])=>label+': '+(row[key]===null?'首样本未定义':row[key].toPrecision(5))).join('　')}}c.addEventListener('mousemove',event=>{const f=Math.max(0,Math.min(1,(event.offsetX-54)/(c.clientWidth-69)));selected=Math.round(f*(data.rows.length-1));draw()});window.addEventListener('resize',draw);draw()}</script></html>'''
    page = page.replace("__TITLE__", html.escape(title)).replace("__INTERPRETATION__", html.escape(report["interpretation"]))
    page = page.replace("__DT__", str(report["dt_s"])).replace("__TAU__", str(report["tau_s"]))
    page = page.replace("__METRICS__", metrics).replace("__PAYLOAD__", payload)
    path.write_text(page, encoding="utf-8")


def _save(report, output_dir):
    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    rows = report["rows"]
    with (output / "signals.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {key:value for key,value in report.items() if key != "rows"}
    summary["data_file"], summary["html_file"] = "signals.csv", "report.html"
    (output / "report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    _write_html(report, output / "report.html")
    return output


def analyze_trajectory(trajectory, output_dir, *, tau_s=0.05, dt_s=None) -> Path:
    return _save(compare_recorded_signals(trajectory, tau_s=tau_s, dt_s=dt_s), output_dir)


def run_derivative_kick(output_dir, *, dt_s=0.02, target_jump_rad=0.02,
                        jump_time_s=1.0, duration_s=2.0, kd=12.0, tau_s=0.05) -> Path:
    return _save(derivative_kick_signal(dt_s=dt_s, target_jump_rad=target_jump_rad,
                 jump_time_s=jump_time_s, duration_s=duration_s, kd=kd, tau_s=tau_s), output_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description="L20：同记录离线差分与独立目标跳变实验")
    sub = parser.add_subparsers(dest="experiment", required=True)
    noise = sub.add_parser("noise", help="对同一份真实记录比较直接omega、差分与滤波")
    noise.add_argument("--trajectory", type=Path, required=True)
    noise.add_argument("--output-dir", type=Path, required=True)
    noise.add_argument("--tau", type=float, default=.05)
    noise.add_argument("--dt", type=float, default=None, help="省略时从记录推断；指定时必须与记录一致")
    kick = sub.add_parser("kick", help="独立信号实验，不运行物理小车")
    kick.add_argument("--output-dir", type=Path, required=True)
    kick.add_argument("--tau", type=float, default=.05)
    kick.add_argument("--dt", type=float, default=.02)
    kick.add_argument("--target-jump", type=float, default=.02)
    kick.add_argument("--kd", type=float, default=12.0)
    args = parser.parse_args(argv)
    if args.experiment == "noise":
        output = analyze_trajectory(args.trajectory, args.output_dir, tau_s=args.tau, dt_s=args.dt)
    else:
        output = run_derivative_kick(args.output_dir, dt_s=args.dt, tau_s=args.tau,
                                     target_jump_rad=args.target_jump, kd=args.kd)
    print(json.dumps({"experiment":args.experiment, "output_dir":str(output),
                      "report":str(output/"report.json"), "html":str(output/"report.html")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
