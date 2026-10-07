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
