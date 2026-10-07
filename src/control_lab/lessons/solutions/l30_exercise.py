"""读取软件“生成真实接口表”保存的 JSON，比较观测与动作的关节顺序。"""
import argparse
import json
from pathlib import Path
from control_lab.integrations.tita_interface import check_policy_compatibility, interface_summary, load_interface


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuration", type=Path, help="在 TITA 面板生成接口表后，复制 interface.json 路径")
    parser.add_argument("--model-metadata", type=Path, help="可选：自己的 CartPole 模型包 metadata.json")
    args = parser.parse_args()
    data = load_interface(args.configuration)
    print(interface_summary(data))
    # 参考：joint_pos 使用机器人实际关节索引，actions 使用动作管理器声明顺序。
    # 当前已验配置的前者左右交替，后者先左腿四关节再右腿四关节，不能互换。
    # 六个位置动作 raw*0.25+默认角度 -> rad；两个轮速 raw*5 -> rad/s。
    # 准确值以此次 JSON 为准；原始零动作仍包含位置偏置，不等于急停。
    if args.model_metadata:
        metadata = json.loads(args.model_metadata.read_text(encoding="utf-8"))
        result = check_policy_compatibility(data, metadata)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if not result["compatible"]:
            print("模型已拒绝；未加载任何策略文件。")


if __name__ == "__main__":
    main()
