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
