# 单车速度台的条件积分；限制必须与本课场景的±1N一致。
integral = 0.0
last_error = 0.0
frozen = False

def reset():
    global integral, last_error, frozen
    integral = 0.0
    last_error = 0.0
    frozen = False

def control(state, dt):
    global integral, last_error, frozen
    error = state["target_v"] - state["v"]
    last_error = error
    candidate = integral + error * dt
    requested = 2.0 * error + candidate
    worsening = (requested > 1.0 and error > 0.0) or (requested < -1.0 and error < 0.0)
    frozen = worsening
    if not worsening:
        integral = candidate
    return 2.0 * error + integral


def diagnostics():
    return {"integral": integral, "p_n": 2.0 * last_error, "i_n": integral, "frozen": frozen}
