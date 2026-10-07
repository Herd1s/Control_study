"""模型重载、继续训练和新奖励对照；使用独立RL解释器。"""
import argparse
import json
from pathlib import Path

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["evaluate", "continue", "new-reward"], default="evaluate")
    parser.add_argument("--reward-config", type=Path, help="L24的reward.json")
    parser.add_argument("--steps", type=int, default=25600)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    if args.mode == "evaluate":
        from control_lab.rl.evaluate import evaluate_model
        print(json.dumps(evaluate_model(args.model_dir, output_dir=args.output_dir), ensure_ascii=False, indent=2))
        return
    from control_lab.rl.train import TrainConfig, train
    from control_lab.rl.rewards import load_reward_config, reward_config_from_contract
    from control_lab.rl.artifacts import validate_artifact
    if args.mode == "continue":
        config = reward_config_from_contract(validate_artifact(args.model_dir)["environment"])
        parent = args.model_dir
    else:
        if args.reward_config is None:
            parser.error("new-reward需要--reward-config；新奖励从零训练")
        config = load_reward_config(args.reward_config)
        parent = None
    print(train(TrainConfig(args.output_dir, total_timesteps=args.steps, seed=args.seed,
        reward_id=config["reward_id"], reward_config=config, resume_from=parent)))

if __name__ == "__main__":
    main()
