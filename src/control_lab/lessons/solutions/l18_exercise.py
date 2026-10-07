# 单车速度台的条件积分；限制必须与本课场景的±1N一致。
integral = 0.0

def reset():
    global integral
    integral = 0.0

def control(state, dt):
    global integral
    error = state["target_v"] - state["v"]
    candidate = integral + error * dt
    requested = 2.0 * error + candidate
    worsening = (requested > 1.0 and error > 0.0) or (requested < -1.0 and error < 0.0)
    if not worsening:
        integral = candidate
    return 2.0 * error + integral
