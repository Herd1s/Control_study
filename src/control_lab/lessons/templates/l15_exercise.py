kp = 60.0
kd = 0.0  # 先记录P基线，再试4、8、12

def control(state, dt):
    return kp * state["theta"] + kd * state["omega"]
