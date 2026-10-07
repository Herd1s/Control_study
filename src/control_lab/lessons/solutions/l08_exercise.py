def control(state, dt):
    velocity = state["v"]
    return -2.0 * velocity
