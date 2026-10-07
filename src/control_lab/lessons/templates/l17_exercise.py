# 仅用于单车速度实验台；不要在倒立摆场景运行。
integral = 0.0
last_error = 0.0
kp, ki = 2.0, 0.0  # 先P，之后把ki改成1.0

def reset():
    global integral, last_error
    integral = 0.0
    last_error = 0.0

def control(state, dt):
    global integral, last_error
    error = state["target_v"] - state["v"]
    last_error = error
    integral += error * dt
    return kp * error + ki * integral


# 供界面显示已经算出的分项；不参与下一次控制计算。
def diagnostics():
    return {"integral": integral, "p_n": kp * last_error, "i_n": ki * integral}
