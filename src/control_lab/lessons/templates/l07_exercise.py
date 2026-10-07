def control(state, dt):
    position = state["x"]
    if position > 0.2:
        return -1.0
    # 练习：补上左边区域的分支。
    return 0.0
