"""你主要修改这个文件；保存后重新运行 ControlLab 即可。

reset() 在每回合开始调用；act(observation, dt) 返回推力，单位 N。
先做直立附近的平衡实验，不包含从下垂位置起摆。
"""


class Controller:
    def __init__(self):
        self.kp = 60.0
        self.ki = 0.0
        self.kd = 12.0
        self.reset()

    def reset(self):
        self.integral = 0.0

    def act(self, observation, dt):
        x, x_dot, theta, theta_dot = map(float, observation)
        # x: m；x_dot: m/s；theta: rad；theta_dot: rad/s；dt: s。
        # theta=0 是直立。正推力朝右，能纠正正 theta。
        error = theta

        # TODO 1：计算 P 项，让 force = self.kp * error。
        # TODO 2：加入 D 项，可直接使用实测角速度 theta_dot。
        # TODO 3：加入积分 error * dt，并处理输出饱和时的积分累积。
        # TODO 4：观察小车是否漂移，再研究位置/速度反馈。
        # 模板故意输出零，因此杆会倒下；这就是练习入口。
        force = 0.0
        return force
