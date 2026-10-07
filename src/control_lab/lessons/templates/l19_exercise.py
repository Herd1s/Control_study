# 先不写 reset()：比较两个回合留下的记忆。
# 第二轮点击“新回合 · 保留代码”，不要停止后重新运行。
integral = 0.0
kp, kd, ki = 60.0, 12.0, 1.0

def control(state, dt):
    global integral
    integral = max(-0.5, min(0.5, integral + state["theta"] * dt))
    return kp*state["theta"] + kd*state["omega"] + ki*integral + 2*state["x"] + 3*state["v"]

def diagnostics():
    return {"integral": integral, "i_n": ki*integral}
