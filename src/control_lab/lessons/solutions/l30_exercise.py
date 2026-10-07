"""只读检查导出的机器人配置JSON，不连接机器人。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path, help="由教师从真实TITA配置导出的JSON")
    args = parser.parse_args()
    data = json.loads(args.configuration.read_text(encoding="utf-8"))
    required = ("environment_id", "observation_names", "action_names", "action_units", "control_dt_s")
    missing = [key for key in required if key not in data]
    if missing:
        raise SystemExit("请从真实配置补全字段，不能猜测：" + ", ".join(missing))
    print(json.dumps({key: data[key] for key in required}, ensure_ascii=False, indent=2))
    print("CartPole只有4维观测/1维力动作；本检查不授权加载该策略到机器人。")

if __name__ == "__main__":
    main()
