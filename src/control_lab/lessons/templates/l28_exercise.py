"""比较两份同协议报告；先冻结控制器，再由统一评价器生成报告。"""
import argparse
import json
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path, help="PD与RL的report.json")
    args = parser.parse_args()
    if len(args.reports) < 2:
        parser.error("请提供至少两份评价报告")
    from control_lab.evaluation import compare_reports
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    print(json.dumps(compare_reports(reports), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
