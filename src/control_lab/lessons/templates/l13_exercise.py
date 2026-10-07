kp = 20.0  # N/rad；依次比较20、40、60

def control(state, dt):
    return kp * state["theta"]
