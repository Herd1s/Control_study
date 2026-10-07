# 逻辑练习：目标是小车在右边时往左拉；下面方向有意留待修正。
def control(state, dt):
    if state["x"] > 0.2:
        return 1.0
    return 0.0
