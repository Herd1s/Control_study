"""在课程训练环境检查Gym接口；这是通路验证，不是训练成功。"""
import numpy as np
from gymnasium.utils.env_checker import check_env

def main():
    from control_lab.rl.env_factory import make_training_env
    env = make_training_env(seed=0, reward_id="survival-v1")
    try:
        check_env(env, skip_render_check=True)
        observation, info = env.reset(seed=42)
        assert len(observation) == 4
        assert env.action_space.shape == (1,)
        assert np.allclose(env.action_space.low, -1.0)
        assert np.allclose(env.action_space.high, 1.0)
        for action in (-1.0, 0.0, 1.0):
            env.reset(seed=42)
            observation, reward, terminated, truncated, info = env.step(np.array([action], dtype=np.float32))
            actual_force = float(info.get("actuator_force_n", info.get("applied_force", float("nan"))))
            assert np.isclose(actual_force, 10.0 * action), "实际推力与归一化映射不符"
            print("模型动作", action, "对应期望推力N", 10.0*action,
                  "terminated", terminated, "truncated", truncated)
        print("Gym接口检查结束；请同时核对实际推力，确认缩放只发生一次。")
    finally:
        env.close()

if __name__ == "__main__":
    main()
