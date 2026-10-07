# 延迟/噪声在场景层实现；控制器仍只读取本次观测。
def control(state, dt):
    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]
