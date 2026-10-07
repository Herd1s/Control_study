"""复用软件保存的 TITA profile，查看或运行固定的小资源仿真入口。"""
import argparse
import os
from pathlib import Path
import subprocess
from control_lab.integrations.tita_profile import build_command, load_profile, inspect_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True, help="软件学习目录，包含 tita/profile.json")
    parser.add_argument("--mode", choices=("inspect", "interface", "registry", "smoke", "export"), default="inspect")
    parser.add_argument("--run", action="store_true", help="明确执行所展示的外部仿真命令；默认只检查或打印")
    args = parser.parse_args()
    profile = load_profile(args.data_dir)
    if args.mode == "inspect":
        import json
        print(json.dumps(inspect_profile(profile), ensure_ascii=False, indent=2))
        return
    command = build_command(profile, args.mode, args.data_dir)
    print(command.powershell())
    if args.run:
        environment = os.environ.copy()
        environment.update(command.environment)
        subprocess.run(command.argv, cwd=command.working_directory, env=environment, check=True, timeout=300)
        print("外部命令完成；短检查不能证明稳定行走，导出不能证明实机可部署。")


if __name__ == "__main__":
    main()
