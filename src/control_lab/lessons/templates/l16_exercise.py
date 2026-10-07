def control(state, dt):
    balance = 60.0 * state["theta"] + 12.0 * state["omega"]
    centering = 0.0  # 练习：加入2*x+3*v，再比较同场景
    return balance + centering
