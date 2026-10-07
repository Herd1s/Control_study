# 本课重点是同协议、多回合记录；控制代码先冻结不改。
def control(state, dt):
    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]
