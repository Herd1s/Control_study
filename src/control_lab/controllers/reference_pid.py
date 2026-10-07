"""角度 PID 加可选的小车位置/速度反馈，仅用于直立附近的平衡。

默认 Ki=0，所以参考控制实际上为 PD 加位置反馈，不包含起摆。
"""

from dataclasses import dataclass


@dataclass
class Gains:
    kp: float = 60.0
    ki: float = 0.0
    kd: float = 12.0
    cart_kp: float = 2.0
    cart_kd: float = 3.0


class Controller:
    def __init__(self, center_cart: bool = True):
        self.gains = Gains()
        self.center_cart = center_cart
        self.force_limit = 10.0
        self.integral_limit = 0.5
        self.reset()

    def reset(self):
        self.integral = 0.0

    def act(self, observation, dt):
        x, x_dot, theta, theta_dot = map(float, observation)
        # 正推力可纠正正角度偏差，故使用测量值减目标值。
        error = theta
        gains = self.gains
        p = gains.kp * error
        d = gains.kd * theta_dot
        cart_feedback = gains.cart_kp * x + gains.cart_kd * x_dot if self.center_cart else 0.0
        candidate_integral = max(
            -self.integral_limit,
            min(self.integral_limit, self.integral + error * dt),
        )
        candidate_force = p + gains.ki * candidate_integral + d + cart_feedback
        # 条件积分：输出已饱和且积分会加重饱和时，不继续积累。
        if gains.ki == 0:
            self.integral = 0.0
        elif abs(candidate_force) <= self.force_limit or candidate_force * gains.ki * error < 0:
            self.integral = candidate_integral
        return p + gains.ki * self.integral + d + cart_feedback
