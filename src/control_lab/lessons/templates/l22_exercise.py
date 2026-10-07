# 结业作品起点：替换为你自己已冻结、保存过的控制规则。
def control(state, dt):
    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]
