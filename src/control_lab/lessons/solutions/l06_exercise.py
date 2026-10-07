def control(state, dt):
    position = state["x"]  # m：先读取，不改变物理状态
    force = 0.5  # N
    return force
