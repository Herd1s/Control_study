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
