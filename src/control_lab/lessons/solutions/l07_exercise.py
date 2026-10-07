def control(state, dt):
    if state["x"] > 0.2:
        return -1.0
    elif state["x"] < -0.2:
        return 1.0
    return 0.0
