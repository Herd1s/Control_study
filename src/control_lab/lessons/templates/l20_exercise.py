# 先离线对比同一记录，再改变闭环；一次只改 omega_source 或 tau。
import math

omega_source = "sensor"  # "sensor"读omega；"difference"用角度差分
tau = 0.05  # s；依次试0、0.02、0.05、0.1，0表示不滤波
filtered_omega = None
last_theta = None

def reset():
    global filtered_omega, last_theta
    filtered_omega = None
    last_theta = None

def control(state, dt):
    global filtered_omega, last_theta
    if tau < 0:
        raise ValueError("tau不能为负数")
    measured = state["omega"]
    if omega_source == "difference":
        # 第一步没有上一读数；控制器暂用0，离线报告则标为未定义。
        measured = 0.0 if last_theta is None else (state["theta"]-last_theta)/dt
    elif omega_source != "sensor":
        raise ValueError("omega_source只能为sensor或difference")
    last_theta = state["theta"]
    if filtered_omega is None:
        filtered_omega = measured
    # 已提供的因果一阶滤波公式，与软件filters模块一致，无未来样本。
    alpha = 1.0 if tau == 0 else -math.expm1(-dt/tau)
    filtered_omega += alpha * (measured-filtered_omega)
    return 60*state["theta"] + 12*filtered_omega + 2*state["x"] + 3*state["v"]

def main(argv=None):
    # VS Code终端也能运行独立信号实验；--tau参数不读取上面的控制器变量。
    from control_lab.lessons.signal_experiments import main as run_experiment
    return run_experiment(argv)

if __name__ == "__main__":
    raise SystemExit(main())
