# 扫描时每次只改kp；列表并不会自动运行仿真。
gains_to_try = [0.0, 20.0, 40.0, 60.0, 100.0]
kp = gains_to_try[1]

def control(state, dt):
    return kp * state["theta"]
