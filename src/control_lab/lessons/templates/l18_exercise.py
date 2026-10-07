# 单车速度台：先观察未抗饱和的积分，目标与±1N限制由场景提供。
integral = 0.0
last_error = 0.0

def reset():
    global integral, last_error
    integral = 0.0
    last_error = 0.0

def control(state, dt):
    global integral, last_error
    error = state["target_v"] - state["v"]
    last_error = error
    integral += error * dt
    return 2.0 * error + integral


def diagnostics():
    return {"integral": integral, "p_n": 2.0 * last_error, "i_n": integral, "frozen": False}
