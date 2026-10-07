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
