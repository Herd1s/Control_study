"""检查接口、真实终止与截断；可选256步通路实验。"""
import argparse
import json
from pathlib import Path

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-output", type=Path, help="指定新目录后再运行256步训练")
    args = parser.parse_args(argv)
    from gymnasium.utils.env_checker import check_env
    from control_lab.rl.env_factory import make_training_env, demonstrate_contract
    env = make_training_env(seed=42)
    try:
        check_env(env, skip_render_check=True)
    finally:
        env.close()
    examples = demonstrate_contract()
    assert [row["actuator_force_n"] for row in examples["mappings"]] == [-10, 0, 10]
    assert examples["examples"]["zero_force"]["terminated"]
    assert examples["examples"]["reference_feedback"]["truncated"]
    print(json.dumps(examples, ensure_ascii=False, indent=2))
    if args.smoke_output:
        from control_lab.rl.train import TrainConfig, train
        result = train(TrainConfig(args.smoke_output, total_timesteps=256, seed=0))
        print("模型已保存：", result)
        print("256步只检查通路；Ctrl+C或STOP文件会正常保存并停止。")

if __name__ == "__main__":
    main()
