"""Development-only resource compiler, inputs are the reviewed curriculum docs."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[2]

META = {
1: (50, 'upright', [], '手动输入怎样影响杆？', '用手提前小幅接住倾倒趋势；动作太猛也可能更快失败。完全静止的零初态不能证明已经会控制。', '先看杆的倾倒方向。', '底座运动会影响杆的运动。', '先尝试小幅拖动，松手观察，再扶正重来。'),
2: (50, 'upright', [], '暂停、扶正和外力各改变什么？', '暂停保留状态并停止时间；扶正清零并暂停；外力是另一个独立输入，会打破静止。', '对照操作前后画面。', '时间停止与状态清零是两件事。', '先暂停再继续，最后扶正，对照三次状态。'),
3: (55, 'moving_right', ['x','v'], '位置为正时速度一定为正吗？', '不一定。小车在右侧但向左走时x为正而v为负。', '分开看在哪里和往哪走。', '正负位置和正负速度独立。', '在右侧向左移动时暂停，记录x与v。'),
4: (55, 'angle_recovering', ['theta','omega'], '同角度不同角速度，下一步一样吗？', '不一样。theta描述当前倾斜，omega描述变化趋势；代码为rad/rad/s，界面可换算为度。', '先观察杆顶朝哪边运动。', '倾斜方向不等于转动方向。', 'theta>0且omega<0代表向右倾但正在回正。'),
5: (50, 'upright', ['force','x'], 'return 1.0和return 0.0各意味着什么？', '推力模式分别是1 N与0 N。0 N不等于速度立即归零。', '先看动作模式的单位。', '力改变运动趋势，并非设置位置。', '依次运行1、-1、0，每次先扶正。'),
6: (50, 'upright', ['x','force'], '改变量名会改变动作单位吗？', '不会。动作含义来自软件契约；变量名帮助阅读，注释不会自动转换单位。', '检查赋值与返回的名字。', '先给数命名，再返回变量。', 'force = 0.5，然后return force。'),
7: (55, 'offset_right', ['x','v','force'], '死区内返回0是否会让车立即停止？', '不会；死区是不给力的范围，已有速度仍会使车移动。位置开关规则也不是摆杆平衡控制器。', '检查位置落在哪个区间。', '所有分支都需要返回有限动作。', 'x>0.2返回-1，x<-0.2返回1，其余返回0。'),
8: (55, 'moving_right', ['v','force','time'], '慢放会不会改变dt？', '不会；每次控制对应一次0.02 s物理步，慢放只改变真实等待时间。', '单步查看输入和输出。', '软件负责重复调用，函数只算本次动作。', '不用while True；读取state并return一个力。'),
9: (55, 'upright', ['time','force'], '为什么累计值要跨调用保留、每回合重置？', '跨调用才能记得过去，回合重置才能让相同条件重复；暂停不能清空或增加仿真时间。', '观察elapsed有没有一直归零。', '记忆放在函数外，用reset清空。', 'control内elapsed += dt；reset内elapsed = 0.0。'),
10: (60, 'tilt_right', ['theta','force'], '没有报错是否证明控制正确？', '不能。语法可运行仍可能方向错误；应保存同初态的代码与轨迹，一次只改一个条件。', '先读第一条相关报错。', '分开语法错误、运行错误与逻辑错误。', '用指定状态试算返回值，再检查代码快照。'),
11: (50, 'moving_right', ['target_v','v','force'], '返回0 N和目标0 m/s为什么不同？', '零力不主动停车；目标零速度会由软件速度环尝试减速，两者不能直接混合评分。', '先核对N还是m/s。', '目标速度经过软件的速度反馈环。', '同一移动初态分别运行两种0输出，观察实际推力。'),
12: (55, 'tilt_right', ['theta','force'], 'P规则读什么，为什么正角度给正力？', 'P读取倾角；正角度代表杆向右倾，底座向右接杆。零角度仍可能有角速度，所以P可能缺少信息。', '回忆手动接杆的方向。', '倾斜越多，比例动作越大。', 'return gain * state["theta"]，先只改gain。'),
13: (65, 'tilt_right', ['theta','force'], 'kp=60、theta=.05 rad时输出多少，为什么？', '输出+3 N，镜像倾角输出-3 N。kp单位N/rad；增益不是推力本身。', '先判断正负，再算大小。', '这里误差采用theta-0。', 'force = kp * theta，不要混用度。'),
14: (65, 'tilt_right', ['theta','force','requested_force'], '增益最大是否一定最好？', '不一定；饱和后实际力不再增大，也可能振荡。需固定初态并同时看存活和误差，不能挑单次赢家。', '比较请求力与实际力。', '电机限幅与控制请求不同。', '逐个试0、20、40、60、100，保存完整失败回合。'),
15: (80, 'angle_fast_right', ['theta','omega','p','d','force'], '同角度不同omega，D怎样改变动作？', 'D读取角速度，正omega增加正向推力，负omega减少；omega已经每秒变化量，不要再除以dt。', '先判断正在越倒越快还是回正。', 'D利用角速度区分相同角度。', 'return 60*theta + 12*omega。'),
16: (80, 'offset_right', ['x','v','theta','force'], '为什么不能直接拼上独立小车的负位置反馈？', '倒立摆是耦合系统，底座动作先改变倾角再影响回中；当前参考完整反馈为60θ+12ω+2x+3v。', '先看保杆和回中是否同时完成。', '第一帧动作与最终回中方向未必相同。', '比较角度PD与加2*x+3*v的整段轨迹。'),
17: (80, 'cart_velocity', ['v','target_v','integral','force'], '积分怎样抵消持续负载？', '积分按error*dt累积历史速度差，让PI补充持续推力；该场景是单车速度台，不是倒立摆。', '先看目标速度与实际速度的差。', '持续误差会不断积累。', 'integral += (target_v-v)*dt；输出kp*error+ki*integral。'),
18: (65, 'cart_velocity_windup', ['v','target_v','integral','force','requested_force'], '输出饱和时哪些积分应暂停，哪些应保留？', '使饱和更严重的增量暂停，反方向误差允许释放积分；每回合要重置积分。', '比较未限幅请求与执行器实际力。', '力已到上限时继续积累会拖慢恢复。', '若candidate>limit且error>0，不接受本次积分增量；负饱和相反。'),
19: (80, 'balance_practice', ['theta','omega','p','d','i','force'], '为什么Ki可以等于0？', '积分用于具体的持续误差问题，不是必须凑齐PID；当前倒立摆参考PD加回中已可作为基线。', '逐项观察P、D、I。', '改变参数一次只改一项。', '先设置Ki=0复现基线，再记录试I是否改善。'),
20: (80, 'balance_practice', ['theta','omega','true_theta','force'], '曲线更平滑是否一定控制更好？', '不一定；滤波引入滞后。真实状态与带噪观测要分开，差分需要除dt并正确处理第一步。', '对比真实角度与观测读数。', '滤波以降低噪声换取响应滞后。', 'alpha=dt/(tau+dt)，filtered += alpha*(omega-filtered)。'),
21: (80, 'balance_validation', ['theta','x','force'], '为什么要保存初态、代码和失败回合？', '它们让对照可复现，避免挑最好一次；早倒回合RMS小也不能算更好，须结合存活长度。', '先确认所有实验条件一致。', '完整统计包括每一次失败。', '练习42–46，调参100–119；别提前查看保留测试。'),
22: (90, 'balance_test', ['theta','x','force'], '你的控制器证据能支持什么，不能支持什么？', '冻结后的同协议报告能说明给定用例的表现，不能声称任何扰动或实物上都稳定；需要失败案例和限制说明。', '先冻结代码与参数。', '解释成功条件和失败边界。', '提交代码快照、逐回合表、指标汇总和一个失败分析。'),
23: (50, 'balance_practice', ['theta','force','reward'], '随机动作是在学习吗？', '不是。随机策略只是选择动作的规则，没有根据奖励更新；环境提供状态转移，策略决定动作。', '先指出观测和动作。', '策略和环境负责不同事情。', 'random.uniform(-10,10)只生成随机力，不会自动学习。'),
24: (60, 'balance_practice', ['theta','x','force','reward'], '重新计分是否让旧策略学会新行为？', '不会，只改变同一轨迹的评分；真正改变策略需要训练。不同奖励下原始回报不能直接横比。', '先看这一步有没有更新策略。', '奖励表达偏好，物理指标单独报告。', '同一轨迹计算角度、位移、用力惩罚，记录奖励版本。'),
25: (60, 'balance_practice', ['theta','force'], 'terminated与truncated有什么区别？', '前者表示倒下等任务终止，后者表示时间等外部上限；循环可合并判断结束，但训练接口须保留二者。', '检查环境返回的五个值。', '归一化动作只转换一次。', '-1、0、1应映射为-10、0、10 N。'),
26: (60, 'balance_practice', ['reward','time'], '训练步数增长是否证明已经会平衡？', '不是；训练完成只说明管道可运行，需独立验证，并用多个训练seed检查稳定性。', '先核对环境与动作契约。', '训练和独立评估使用不同用例。', '固定预算和配置，分别用seed=0、1、2训练并保留全部结果。'),
27: (60, 'balance_validation', ['theta','reward'], '保存policy.zip是否足够复现？', '不够；需要环境、观察顺序、动作缩放、预处理、奖励、依赖和验证结果。重载模型不应依赖旧进程状态。', '首先比对模型元数据。', '动作单位或观察顺序不匹配会改变结果。', '重开进程加载，确定性predict，核对相同用例。'),
28: (60, 'balance_test', ['theta','x','force','reward'], '怎样公平比较PD与PPO？', '双方同状态权限、力单位、初态、dt、终止和评价指标；报告全部回合以及各训练seed，不挑最漂亮结果。', '先找输入模式或配置的差异。', '辅助位置或速度控制不能冒充直接力控制。', '用冻结测试用例逐个评估，分开物理指标与训练回报。'),
29: (60, 'robustness_delay', ['theta','true_theta','force'], '电脑卡顿与传感器延迟有什么区别？', '电脑卡顿改变播放速度；明确的一步观察延迟使控制用到20 ms前的信息，属于任务配置变化。', '每次只打开一个因素。', '延迟、噪声和参数变化要分别测试。', '比较0/1/2步延迟，关闭其他扰动后再换噪声。'),
30: (50, 'none', [], '从倒立摆到TITA哪些可迁移，哪些必须重做？', '可迁移观测、动作、反馈、试验和评价方法；必须核对多关节状态、接触、坐标、控制频率、动作单位及底层控制。', '先画输入输出链路。', '机器人不只有四个状态和一个推力。', '从实际配置读取维数，拒绝把CartPole模型直接加载到TITA。'),
31: (120, 'none', [], '短步数烟测与稳定行走训练有什么不同？', '烟测验证加载、训练、保存通路，不代表策略已稳定行走；TITA需要独立Isaac环境与固定版本。', '先核对解释器、仓库提交和任务ID。', '小预算管道验证不能替代性能评价。', '先运行官方只读任务清单，再用已验证的小规模入口；不要向硬件发命令。'),
32: (120, 'none', [], '进入实机阶段前需要哪些证据？', '接口与单位核对、仿真停止/超时/限幅记录、只读遥测方案、现场指导和停止方法；未具备时继续仿真。', '列出仿真与设备的差异。', '导出策略不是完成硬件部署。', '提交迁移报告、接口表、停止测试记录和后续计划；本课不驱动实机。'),
}

TEMPLATES = {
5: 'def control(state, dt):\n    return 1.0  # N；试着改为-1.0或0.0\n',
6: 'def control(state, dt):\n    position = state["x"]  # m：先读取，不改变物理状态\n    force = 0.5  # N\n    return force\n',
7: 'def control(state, dt):\n    position = state["x"]\n    if position > 0.2:\n        return -1.0\n    # 练习：补上左边区域的分支。\n    return 0.0\n',
8: 'def control(state, dt):\n    velocity = state["v"]\n    return -2.0 * velocity\n',
9: 'elapsed = 0.0\n\ndef reset():\n    global elapsed\n    elapsed = 0.0\n\ndef control(state, dt):\n    global elapsed\n    force = 1.0 if elapsed < 0.5 else 0.0\n    elapsed += dt\n    return force\n',
10: '# 逻辑练习：目标是小车在右边时往左拉；下面方向有意留待修正。\ndef control(state, dt):\n    if state["x"] > 0.2:\n        return 1.0\n    return 0.0\n',
11: '# 本课选择目标速度模式，此处单位m/s；主线恢复为推力N。\ndef control(state, dt):\n    return 0.5\n',
12: 'def control(state, dt):\n    angle = state["theta"]  # rad\n    gain = 10.0  # N/rad；一次只改这个数\n    return gain * angle\n',
13: 'kp = 20.0  # N/rad；依次比较20、40、60\n\ndef control(state, dt):\n    return kp * state["theta"]\n',
14: '# 扫描时每次只改kp；列表并不会自动运行仿真。\ngains_to_try = [0.0, 20.0, 40.0, 60.0, 100.0]\nkp = gains_to_try[1]\n\ndef control(state, dt):\n    return kp * state["theta"]\n',
15: 'kp = 60.0\nkd = 0.0  # 先记录P基线，再试4、8、12\n\ndef control(state, dt):\n    return kp * state["theta"] + kd * state["omega"]\n',
16: 'def control(state, dt):\n    balance = 60.0 * state["theta"] + 12.0 * state["omega"]\n    centering = 0.0  # 练习：加入2*x+3*v，再比较同场景\n    return balance + centering\n',
17: '# 仅用于单车速度实验台；不要在倒立摆场景运行。\nintegral = 0.0\nkp, ki = 2.0, 0.0  # 先P，之后把ki改成1.0\n\ndef reset():\n    global integral\n    integral = 0.0\n\ndef control(state, dt):\n    global integral\n    error = state.get("target_v", 0.3) - state["v"]\n    integral += error * dt\n    return kp * error + ki * integral\n',
18: '# 单车速度台：先观察未抗饱和的积分，目标与±1N限制由场景提供。\nintegral = 0.0\n\ndef reset():\n    global integral\n    integral = 0.0\n\ndef control(state, dt):\n    global integral\n    error = state.get("target_v", 0.3) - state["v"]\n    integral += error * dt\n    return 2.0 * error + integral\n',
19: 'integral = 0.0\nkp, kd, ki = 60.0, 12.0, 0.0\n\ndef reset():\n    global integral\n    integral = 0.0\n\ndef control(state, dt):\n    global integral\n    integral += state["theta"] * dt\n    return kp*state["theta"] + kd*state["omega"] + ki*integral + 2*state["x"] + 3*state["v"]\n',
20: 'filtered_omega = None\ntau = 0.02  # s；更平滑也会更滞后\n\ndef reset():\n    global filtered_omega\n    filtered_omega = None\n\ndef control(state, dt):\n    global filtered_omega\n    omega = state["omega"]\n    if filtered_omega is None:\n        filtered_omega = omega\n    alpha = dt / (tau + dt)\n    filtered_omega += alpha * (omega - filtered_omega)\n    return 60*state["theta"] + 12*filtered_omega + 2*state["x"] + 3*state["v"]\n',
21: '# 本课重点是同协议、多回合记录；控制代码先冻结不改。\ndef control(state, dt):\n    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]\n',
22: '# 结业作品起点：替换为你自己已冻结、保存过的控制规则。\ndef control(state, dt):\n    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]\n',
23: 'import random\n_rng = random.Random(7)\n\ndef reset():\n    _rng.seed(7)  # 课堂固定动作序列，方便重放；它不会学习\n\ndef control(state, dt):\n    return _rng.uniform(-10.0, 10.0)\n',
29: '# 延迟/噪声在场景层实现；控制器仍只读取本次观测。\ndef control(state, dt):\n    return 60*state["theta"] + 12*state["omega"] + 2*state["x"] + 3*state["v"]\n',
}
TEMPLATES[20] = '''# 先离线对比同一记录，再改变闭环；一次只改 omega_source 或 tau。
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
'''
SOLUTIONS = dict(TEMPLATES)
SOLUTIONS.update({
7: 'def control(state, dt):\n    if state["x"] > 0.2:\n        return -1.0\n    elif state["x"] < -0.2:\n        return 1.0\n    return 0.0\n',
10: 'def control(state, dt):\n    if state["x"] > 0.2:\n        return -1.0\n    return 0.0\n',
12: TEMPLATES[12].replace('gain = 10.0', 'gain = 30.0'),
13: TEMPLATES[13].replace('kp = 20.0', 'kp = 60.0'),
14: TEMPLATES[14].replace('gains_to_try[1]', 'gains_to_try[3]'),
15: TEMPLATES[15].replace('kd = 0.0', 'kd = 12.0'),
16: TEMPLATES[16].replace('centering = 0.0', 'centering = 2.0 * state["x"] + 3.0 * state["v"]'),
17: TEMPLATES[17].replace('kp, ki = 2.0, 0.0', 'kp, ki = 2.0, 1.0'),
18: '# 单车速度台的条件积分；限制必须与本课场景的±1N一致。\nintegral = 0.0\n\ndef reset():\n    global integral\n    integral = 0.0\n\ndef control(state, dt):\n    global integral\n    error = state.get("target_v", 0.3) - state["v"]\n    candidate = integral + error * dt\n    requested = 2.0 * error + candidate\n    worsening = (requested > 1.0 and error > 0.0) or (requested < -1.0 and error < 0.0)\n    if not worsening:\n        integral = candidate\n    return 2.0 * error + integral\n',
})


def extract():
    found = {}
    for filename in ('01_FOUNDATIONS.md', '02_FEEDBACK_CONTROL.md', '03_RL_AND_TITA.md'):
        text = (PROJECT / 'docs' / 'curriculum' / filename).read_text(encoding='utf-8')
        matches = list(re.finditer(r'^## (?:\d+\. )?L(\d\d)([^\n]*)$', text, re.M))
        for index, match in enumerate(matches):
            n = int(match.group(1))
            body = text[match.end():matches[index+1].start() if index+1 < len(matches) else len(text)]
            # Final lesson can be followed by an index/reference chapter.
            body = re.split(r'\n## (?!L\d\d)', body, maxsplit=1)[0]
            marker = re.search(r'\*\*(?:学生操作|课堂步骤|操作步骤)[：:]?\*\*[：:]?', body)
            if marker:
                block = body[marker.end():]
                block = re.split(r'\n\*\*', block, maxsplit=1)[0]
                instructions = re.findall(r'^\d+\. (.+)$', block, re.M)
            else:
                instructions = []
            if not 5 <= len(instructions) <= 9:
                raise ValueError((n, len(instructions), filename))
            title = match.group(2).strip(' ：:｜')
            title = re.sub(r'^（支线）[：:]?', '', title)
            found[n] = (title, body.strip(), instructions)
    return found


def build(extra_templates=None, lesson_ids=None):
    if extra_templates:
        TEMPLATES.update(extra_templates)
        SOLUTIONS.update(extra_templates)
    for n in (17, 18):
        TEMPLATES[n] = TEMPLATES[n].replace('state.get("target_v", 0.3)', 'state["target_v"]')
        SOLUTIONS[n] = SOLUTIONS[n].replace('state.get("target_v", 0.3)', 'state["target_v"]')
    for source_map in (TEMPLATES, SOLUTIONS):
        source_map[9] = source_map[9].replace('force = 1.0 if elapsed < 0.5 else 0.0',
            'force = 0.0\n    if elapsed < 0.5:\n        force = 1.0')
    for folder in ('content', 'templates', 'solutions'):
        (ROOT / folder).mkdir(exist_ok=True)
    source = extract()
    for n in range(1, 33):
        if lesson_ids is not None and n not in lesson_ids:
            continue
        title, notes, instructions = source[n]
        minutes, scenario, signals, question, answer, h1, h2, h3 = META[n]
        if n == 20:
            h3 = 'alpha=1-exp(-dt/tau)；tau=0直接通过。指数公式已提供，先只改tau。'
            answer += (' 同输入离线对照先排除闭环轨迹变化；第一条差分未知，不计入指标。'
                '角度误差单位rad、角速度误差单位rad/s，不能直接比较数值大小。'
                '误差定义theta-target；目标跳0.02rad、dt=0.02s、Kd=12时，误差D项为-12N，'
                '测量保持0时仅测量求导为0N。这是未限幅的独立信号计算，不是小车稳定性试验。')
        if n in (22, 28):
            scenario = 'balance_validation'  # held-out requires the dedicated frozen evaluation workflow
        if n == 7:
            scenario = 'position_right'
        if n in (17,18):
            requirements = ['cart_velocity']
        elif n in (25,26,27,28):
            requirements = ['rl_runtime']
        elif n >= 30:
            requirements = ['tita_external_environment']
        elif n == 29:
            requirements = ['robustness_scenario']
        else:
            requirements = []
        kind = 'none' if n <= 4 else ('script' if n in (24,25,26,27,28,30,31,32) else 'controller')
        availability = 'external_robot' if n >= 30 else ('external_runtime' if n in (25,26,27,28) else 'built_in')
        prerequisite = [] if n == 1 else [f'L{n-1:02d}']
        if n == 12: prerequisite = ['L10']
        if n == 23: prerequisite = ['L21']
        if n == 28: prerequisite = ['L22', 'L27']
        if n == 29: prerequisite = ['L20', 'L28']
        if n == 30: prerequisite = ['L28']
        if n == 32: prerequisite = ['L29', 'L31']
        steps = []
        for j, instruction in enumerate(instructions, 1):
            if n == 26 and j == 6:
                instruction += ' 本软件的一次CPU校准中，同样训练25,600步，seed0/1/2在20个验证回合中分别完成3/0/20回合；前两组主要因小车越界结束。这说明杆角度小不等于已经回中，单个好seed也不能代表所有训练。你的实验需保留自己的真实结果。'
            event, activity = 'step.acknowledged', 'observe'
            if any(word in instruction for word in ('写下','填写','预测表','手算','判断','解释')):
                event, activity = 'prediction.submitted', 'predict'
            elif any(word in instruction for word in ('保存','提交','记录')):
                event, activity = 'experiment.saved', 'record'
            elif any(word in instruction for word in ('运行','开始','试一次','重复','试3','试 3')):
                event, activity = ('code.run' if kind == 'controller' else 'simulation.started'), 'experiment'
            elif any(word in instruction for word in ('拖动','左右移动','按住','松开鼠标')):
                event, activity = 'cart.dragged', 'manual'
            elif '暂停' in instruction:
                event, activity = 'simulation.paused', 'observe'
            elif any(word in instruction for word in ('改为','补上','代码','赋值','加入')) and kind == 'controller':
                event, activity = 'code.edited', 'code'
            elif '单步' in instruction:
                event, activity = 'simulation.stepped', 'observe'
            if availability != 'built_in':
                event, activity = 'step.acknowledged', 'external'
            completion = {'event': event}
            if event == 'prediction.submitted':
                completion['field'] = 'value'
            if n == 20 and j == 2:
                event, activity = 'scenario.selected', 'observe'
                completion = {'event': 'scenario.selected', 'field': 'id', 'equals': 'measurement_theta_noise'}
            if n == 20 and j in (3, 6):
                event = 'signal.analysis.completed' if j == 3 else 'signal.kick.completed'
                activity = 'experiment'
                completion = {'event': event}
            if n == 20 and j == 4:
                event, activity = 'code.run', 'experiment'
                completion = {'all': [
                    {'event': 'scenario.selected', 'field': 'id', 'equals': 'measurement_omega_noise'},
                    {'event': 'code.run', 'min_count': 4}]}
            if n == 8 and j in (2, 3):
                event, activity = 'simulation.stepped', 'observe'
                completion = {'event': 'simulation.stepped', 'field': 'single', 'equals': True,
                              'min_count': 5 if j == 3 else 1}
            evidence = {
                'step.acknowledged':'完成上面的观察或外部操作后，点击“我已观察并完成操作”。',
                'prediction.submitted':'写下你的预测或解释，再点击“保存我的观察”。',
                'experiment.saved':'完成这一轮实验后，保存实验轨迹和代码。',
                'code.run':'运行这份代码，观察本次动作和结果。',
                'simulation.started':'开始一次实验，观察上面要求的现象。',
                'cart.dragged':'用鼠标抓住小车，完成上面的拖动练习。',
                'simulation.paused':'在需要观察的时刻暂停，保留当前画面。',
                'code.edited':'在你的代码副本中修改本步骤要求的一处内容。',
                'simulation.stepped':'暂停后使用单步，观察输入和输出。',
                'scenario.selected':'在实验场景中选择“角度测量噪声”，对照真实值与读数。',
                'signal.analysis.completed':'选择已保存的trajectory.csv并点击“分析同一条轨迹”；报告实际保存后才能继续。',
                'signal.kick.completed':'点击“运行目标跳变实验”；报告实际保存后才能继续。',
            }[event]
            if n == 20 and j == 4:
                evidence = '选择“角速度测量噪声”，修改tau并实际运行四次；每次保存观察，由学生或教师核对参数分别为0、0.02、0.05、0.1。'
            step_hints = [h1, h2, h3]
            if n == 20 and j == 3:
                step_hints = ['先运行并保存带角度噪声的实验，再打开右侧“信号实验”页签。',
                    '选择同一个trajectory.csv重算，观察原始差分与滤波曲线；这一步不重跑物理。',
                    'difference=(theta-last_theta)/dt；首样本无上一值。对照同一真值差分，可分清噪声与数值近似误差。']
            if n == 20 and j == 6:
                step_hints = ['打开右侧“信号实验”页签，点击“运行目标跳变实验”。',
                    '目标变了，测量仍为0；error=theta-target，因此误差突然减小。',
                    '12*(0-0.02)/0.02=-12N；测量差分=0。信号图不施加执行器限幅。']
            if n == 10 and j in (3, 7):
                event, activity = 'step.acknowledged', 'observe'
                completion = {'event': event}
                evidence = '实际查看保存的曲线与条件后，点击“我已观察并完成操作”；重放本身不生成新的实验成绩。'
            steps.append({'id':f'step_{j:02d}', 'title': {'observe':'观察','predict':'先预测','record':'留下记录','experiment':'运行实验','manual':'动手体验','code':'修改代码','external':'外部实验准备'}[activity],
                'instruction':instruction, 'activity':activity, 'evidence':evidence,
                'completion':completion, 'hints':step_hints})
        steps.append({'id':'reflection', 'title':'说说你的发现', 'instruction':question,
            'activity':'reflect','evidence':'提交自己的解释；软件只记录非空答案，正确性由自评或教师确认。',
            'completion':{'event':'reflection.submitted','field':'reflection'},'hints':[h1,h2,h3]})
        basename=f'l{n:02d}_exercise.py'
        template = f'templates/{basename}' if n in TEMPLATES else None
        solution = f'solutions/{basename}' if n in SOLUTIONS else None
        if kind != 'none' and template is None:
            raise ValueError(f'L{n:02d} needs executable resource')
        if template:
            (ROOT/template).write_text(TEMPLATES[n],encoding='utf-8')
            (ROOT/solution).write_text(SOLUTIONS[n],encoding='utf-8')
        options = list(dict.fromkeys([scenario, 'upright','tilt_right','tilt_left'])) if n <= 16 else [scenario]
        if n == 3: options=['moving_right','offset_right','upright']
        if n == 5: options=['upright','moving_right','tilt_right','tilt_left']
        if n == 7: options=['position_right','position_left','upright','moving_right']
        if n in (4,15): options=['angle_recovering','angle_fast_right','tilt_right','tilt_left']
        if n == 20: options=['balance_practice','measurement_theta_noise','measurement_omega_noise']
        if n in (17,18): options=['cart_velocity','cart_velocity_windup']
        if n == 17: options=['cart_velocity','cart_velocity_unloaded']
        data = {'schema_version':1,'content_version':1,'lesson_id':f'L{n:02d}','title':title,
            'summary':question,'duration_minutes':minutes,'prerequisites':prerequisite,
            'scenario_id':scenario,'scenario_options':options,'input_mode':'none' if n>=30 else ('manual_position_assist' if n<=4 else ('velocity_mps' if n==11 else 'force_n')),
            'visible_signals':signals,'steps':steps,'template':template,'solution':solution,
            'requires':requirements,'availability':availability,'editor_kind':kind,
            'reflection':question,'reference_answer':answer,'objectives':[question, '保存真实观察并说明本次结论的适用条件。'],
            'notes':notes}
        if n in (10, 20):
            data['content_version'] = 2
        if n == 26:
            data['reference_answer'] += ' 已记录的2026-10-07校准：同为25,600步，seed0/1/2完成率分别3/20、0/20、20/20，平均步数369.55、349.55、500；前两组主要是小车越界。仅验证集结果，不是保留测试，也不是任意电脑、预算或机器人上的效果保证。'
            data['calibration_evidence'] = {'source':'logs/rl-curriculum-20261007_220330',
                'split':'validation','requested_steps':25600,'training_seeds':[0,1,2],
                'completed_episodes':[3,0,20],'episodes_per_seed':20,'mean_steps':[369.55,349.55,500.0]}
        (ROOT/'content'/f'L{n:02d}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__ == '__main__':
    from _script_templates import SCRIPTS
    build(SCRIPTS)
