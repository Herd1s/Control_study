"""复现模拟执行器的限幅、超时、停止与急停锁存；不连接机器人。"""
import argparse
import json
from pathlib import Path
from control_lab.integrations.tita_safety import run_safety_experiment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path, help="TITA 面板生成的 interface.json")
    parser.add_argument("--output-dir", type=Path, required=True, help="新的结果目录；不覆盖旧记录")
    args = parser.parse_args()
    path, report = run_safety_experiment(args.configuration, args.output_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("报告：", path, "轨迹：", path.with_name("trace.csv"))
    # 练习：在 trace.csv 找出超时开始步、急停期间收到的新命令、重新使能步骤。
    # 练习：解释为什么这个模拟器通过仍不能证明真实电机的停止能力。
    if not report["passed"]:
        raise SystemExit("实验存在失败项，不能记为完成")
    print("四项模拟实验通过；ready_for_hardware 始终为 False，实机需要独立现场验证。")


if __name__ == "__main__":
    main()
