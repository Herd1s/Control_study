elapsed = 0.0

def reset():
    global elapsed
    elapsed = 0.0

def control(state, dt):
    global elapsed
    force = 0.0
    if elapsed < 0.5:
        force = 1.0
    elapsed += dt
    return force
