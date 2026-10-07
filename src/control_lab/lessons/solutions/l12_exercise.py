def control(state, dt):
    angle = state["theta"]  # rad
    gain = 30.0  # N/rad；一次只改这个数
    return gain * angle
