"""给一份真实CSV轨迹重新计分，不会修改或训练策略。"""
import argparse
import csv
import json

def reward_parts(state, force_n, effort_weight=0.02):
    return {
        "survival": 1.0,
        "angle": -0.6 * (state["theta"] / 0.20943951023931956) ** 2,
        "position": -0.2 * (state["x"] / 2.4) ** 2,
        "effort": -effort_weight * (force_n / 10.0) ** 2,
    }

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trajectory", help="已保存的trajectory.csv")
    parser.add_argument("--effort-weight", type=float, default=0.02)
    args = parser.parse_args()
    def read(row, names):
        for name in names:
            if name in row:
                return float(row[name])
        raise ValueError("CSV缺少列: " + "/".join(names))
    totals = dict(survival=0.0, angle=0.0, position=0.0, effort=0.0)
    with open(args.trajectory, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            state = {"theta": read(row, ("true_theta", "true_theta_rad", "theta", "theta_rad")),
                     "x": read(row, ("true_x", "true_x_m", "x", "x_m"))}
            force = read(row, ("actuator_force_n", "applied_force", "force_n", "force"))
            for key, value in reward_parts(state, force, args.effort_weight).items():
                totals[key] += value
    print(json.dumps({"parts": totals, "return": sum(totals.values()),
                      "note": "同一轨迹重计分，未重新训练"}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
