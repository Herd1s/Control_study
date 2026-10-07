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
    # 参考：timeout_zero 用例 step3 起输出归零并禁用模拟执行器，step6仍为零。
    # emergency_latch step2 的新命令被拒绝；step4显式解除锁存仍不恢复旧动作，
    # step5收到新命令才重新使能。真实电机/固件/通信/关节PD均未包含在本模型中。
    if not report["passed"]:
        raise SystemExit("实验存在失败项，不能记为完成")
    print("四项模拟实验通过；ready_for_hardware 始终为 False，实机需要独立现场验证。")


if __name__ == "__main__":
    main()
