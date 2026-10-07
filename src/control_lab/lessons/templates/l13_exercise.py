# 先保留上一课的条件规则，观察小倾角和大倾角时给出的力。
# 到第3步，再把规则改成 kp * angle，比较 kp=20、40、60。
kp = 20.0  # N/rad；第3步开始使用

def control(state, dt):
    angle = state["theta"]
    if angle > 0.0:
        return 1.0
    return -1.0
