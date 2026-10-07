"""Complete script templates; training scripts require the optional RL runtime."""
from textwrap import dedent

SCRIPTS = {}
SCRIPTS[24] = dedent('''\
"""给一份真实CSV轨迹重新计分，不会修改或训练策略。"""
import argparse
import csv
import json

def reward_parts(state, force_n, effort_weight=0.02):
    return {
        "survival": 1.0,
        "angle": -0.6 * (state["theta"] / 0.20943951023931956) ** 2,
        "position": -0.2 * (state["x"] / 2.4) ** 2,
        "effort": -effort_weight * (force_n / 10.0) ** 2,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", help="已保存的trajectory.csv")
    parser.add_argument("--effort-weight", type=float, default=0.02)
    args = parser.parse_args()
    def read(row, names):
        for name in names:
            if name in row:
                return float(row[name])
        raise ValueError("CSV缺少列: " + "/".join(names))
    totals = dict(survival=0.0, angle=0.0, position=0.0, effort=0.0)
    with open(args.trajectory, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            state = {"theta": read(row, ("true_theta", "true_theta_rad", "theta", "theta_rad")),
                     "x": read(row, ("true_x", "true_x_m", "x", "x_m"))}
            force = read(row, ("actuator_force_n", "applied_force", "force_n", "force"))
            for key, value in reward_parts(state, force, args.effort_weight).items():
                totals[key] += value
    print(json.dumps({"parts": totals, "return": sum(totals.values()),
                      "note": "同一轨迹重计分，未重新训练"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
''')
SCRIPTS[25] = dedent('''\
"""在课程训练环境检查Gym接口；这是通路验证，不是训练成功。"""
import numpy as np
from gymnasium.utils.env_checker import check_env

def main():
    from control_lab.rl.env_factory import make_training_env
    env = make_training_env(seed=0, reward_id="survival-v1")
    try:
        check_env(env, skip_render_check=True)
        observation, info = env.reset(seed=42)
        assert len(observation) == 4
        assert env.action_space.shape == (1,)
        assert np.allclose(env.action_space.low, -1.0)
        assert np.allclose(env.action_space.high, 1.0)
        for action in (-1.0, 0.0, 1.0):
            env.reset(seed=42)
            observation, reward, terminated, truncated, info = env.step(np.array([action], dtype=np.float32))
            actual_force = float(info.get("actuator_force_n", info.get("applied_force", float("nan"))))
            assert np.isclose(actual_force, 10.0 * action), "实际推力与归一化映射不符"
            print("模型动作", action, "对应期望推力N", 10.0*action,
                  "terminated", terminated, "truncated", truncated)
        print("Gym接口检查结束；请同时核对实际推力，确认缩放只发生一次。")
    finally:
        env.close()

if __name__ == "__main__":
    main()
''')
SCRIPTS[26] = dedent('''\
"""在独立RL环境运行：python l26_exercise.py --output-dir 我的实验目录 --seed 0"""
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--steps", type=int, default=25600)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.steps <= 0 or args.seed < 0:
        parser.error("steps须为正数，seed须非负")
    try:
        from control_lab.rl.train import TrainConfig, train
        config = TrainConfig(output_dir=args.output_dir, total_timesteps=args.steps,
                             seed=args.seed, reward_id="survival-v1")
        artifact = train(config)
    except ModuleNotFoundError as exc:
        raise SystemExit("请使用已配置的独立RL解释器运行。本机缺少：" + str(exc)) from exc
    print("模型包：", artifact)
    print("训练结束不代表已学会平衡；下一步运行独立验证。")

if __name__ == "__main__":
    main()
''')
SCRIPTS[27] = dedent('''\
"""重开进程加载自己的模型包，在验证集评价；需要独立RL环境。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        from control_lab.rl.evaluate import evaluate_model
        report = evaluate_model(args.model_dir, split="validation", output_dir=args.output_dir)
    except ModuleNotFoundError as exc:
        raise SystemExit("请在独立RL环境运行：" + str(exc)) from exc
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
''')
SCRIPTS[28] = dedent('''\
"""比较两份同协议报告；先冻结控制器，再由统一评价器生成报告。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="PD与RL的report.json")
    args = parser.parse_args()
    if len(args.reports) < 2:
        parser.error("请提供至少两份评价报告")
    from control_lab.evaluation import compare_reports
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    print(json.dumps(compare_reports(reports), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
''')
SCRIPTS[30] = dedent('''\
"""只读检查导出的机器人配置JSON，不连接机器人。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path, help="由教师从真实TITA配置导出的JSON")
    args = parser.parse_args()
    data = json.loads(args.configuration.read_text(encoding="utf-8"))
    required = ("environment_id", "observation_names", "action_names", "action_units", "control_dt_s")
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit("请从真实配置补全字段，不能猜测：" + ", ".join(missing))
    print(json.dumps({key: data[key] for key in required}, ensure_ascii=False, indent=2))
    print("CartPole只有4维观测/1维力动作；本检查不授权加载该策略到机器人。")

if __name__ == "__main__":
    main()
''')
SCRIPTS[31] = dedent('''\
"""只读核对外部TITA解释器与仓库，不启动训练或发送硬件指令。"""
import argparse
import json
import subprocess
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--task-id", required=True, help="从官方任务清单中复制，不能猜测")
    args = parser.parse_args()
    if not args.python.is_file() or not args.repository.is_dir():
        parser.error("解释器或仓库路径不存在")
    version = subprocess.run([str(args.python.resolve()), "--version"], capture_output=True,
                             text=True, timeout=15, check=True).stdout.strip()
    commit = subprocess.run(["git", "-C", str(args.repository.resolve()), "rev-parse", "HEAD"],
                            capture_output=True, text=True, timeout=15, check=True).stdout.strip()
    print(json.dumps({"python": str(args.python.resolve()), "version": version,
                      "repository": str(args.repository.resolve()), "commit": commit,
                      "task_id_to_verify": args.task_id, "simulation_launched": False},
                     ensure_ascii=False, indent=2))
    print("接下来由教师按该提交验证过的官方入口启动；本脚本未验证模型或行走能力。")

if __name__ == "__main__":
    main()
''')
SCRIPTS[32] = dedent('''\
"""创建迁移报告工作表，不控制任何硬件，默认所有验证项均未完成。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="新报告JSON路径，已有文件不会覆盖")
    args = parser.parse_args()
    report = {
        "robot_model": "请填写实际设备型号", "software_versions": {},
        "observation_action_mapping": [], "model_reality_differences": [],
        "simulation_stop_verified": False, "timeout_verified": False,
        "action_limit_verified": False, "telemetry_only_plan": "",
        "onsite_supervisor": "", "stop_method": "", "evidence_paths": [],
        "open_questions": [], "ready_for_hardware": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print("工作表已创建：", args.output)
    print("逐项填写真实证据后交教师审查；未满足条件继续仿真。")

if __name__ == "__main__":
    main()
''')
