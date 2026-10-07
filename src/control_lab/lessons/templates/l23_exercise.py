import random
_rng = random.Random(7)

def reset():
    _rng.seed(7)  # 课堂固定动作序列，方便重放；它不会学习

def control(state, dt):
    return _rng.uniform(-10.0, 10.0)
