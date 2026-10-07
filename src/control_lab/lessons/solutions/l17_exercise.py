# 仅用于单车速度实验台；不要在倒立摆场景运行。
integral = 0.0
kp, ki = 2.0, 1.0  # 先P，之后把ki改成1.0

def reset():
    global integral
    integral = 0.0

def control(state, dt):
    global integral
    error = state["target_v"] - state["v"]
    integral += error * dt
    return kp * error + ki * integral
