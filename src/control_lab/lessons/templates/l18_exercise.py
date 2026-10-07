# 单车速度台：先观察未抗饱和的积分，目标与±1N限制由场景提供。
integral = 0.0

def reset():
    global integral
    integral = 0.0

def control(state, dt):
    global integral
    error = state["target_v"] - state["v"]
    integral += error * dt
    return 2.0 * error + integral
