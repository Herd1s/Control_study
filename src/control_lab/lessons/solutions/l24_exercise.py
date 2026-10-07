"""同轨迹重计分，并保存可用于L27训练的奖励声明。"""
import argparse
from pathlib import Path

# 练习：只改用力权重，为新定义取新名字；内置版本名不能覆盖。
MY_REWARD = {"schema_version": 1, "reward_id": "balanced-effort-x10-v1", "version": 1,
             "alive": 1.0, "angle": 0.6, "position": 0.2, "effort": 0.2}

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectories", nargs="+", type=Path, help="1–2份trajectory.csv")
    parser.add_argument("--output-dir", required=True, type=Path, help="新的输出目录")
    args = parser.parse_args(argv)
    from control_lab.rl.rewards import resolve_reward_config, normalize_reward_config
    from control_lab.rl.reward_analysis import analyze_rewards
    from control_lab.rl.artifacts import atomic_json
    config = normalize_reward_config(MY_REWARD)
    result = analyze_rewards(args.trajectories, [resolve_reward_config("survival-v1"),
        resolve_reward_config("balanced-v1"), config], args.output_dir)
    config_path = args.output_dir / "my_reward.json"
    atomic_json(config_path, config)
    print("曲线和分量报告：", result["html"])
    print("供L27载入的声明：", config_path)
    print("这里只重新计分；未改变原始轨迹，也未训练策略。")

if __name__ == "__main__":
    main()

# 同一轨迹中，用力项为原来的10倍；总分并非变为10倍。
