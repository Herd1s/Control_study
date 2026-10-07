# ControlLab 课程代码与软件开发规划

规划日期：2026-10-07。本文保留原始开发规格与实施顺序，其中“已有/尚无/拟新增”默认指规划基线，不代表 0.2.0 当前状态。0.2.0 历史记录见 [实现审计](IMPLEMENTATION_AUDIT.md)；0.2.1 当前实现、证据与未完成项见 [规格复核](SPEC_GAP_AUDIT.md)、[RL/TITA 复核](REQUIREMENT_GAPS_0.2.1.md) 和 [版本验证](VALIDATION_0.2.1.md)；可执行命令见 [README](../README.md)，原始排期见 [路线图](ROADMAP.md)。

## 1. 开发目标与边界

让教师能逐课开放功能，让学生先拖动、再观察、再写几行 Python，最终公平比较传统控制与强化学习。每次增加一个概念，不同时要求学生学习 Python 类、物理建模、控制理论和训练框架。

这一轮规划不把软件改为 Web 应用，不替换 PySide6，不重写已经可用的力输入动力学，不把 Isaac Sim 或 PyTorch 放进基础教学安装包。先把同一份实验配置用于桌面、命令行和训练，再增加课程。

### 已有代码及其局限

| 当前文件 | 已有能力 | 后续修改 |
| --- | --- | --- |
| `desktop/app.py` | 三个页面、拖车、观测、代码编辑 | 逐步提取课程状态和实验会话；不继续堆积32个分支 |
| `desktop/ui_widgets.py` | 动画、轨迹、读数、语法颜色 | 保留绘图；修复抓取偏移；增加可选教学高亮 |
| `desktop/engine.py` | 教学环境、超时子进程 | 保留进程隔离；把控制调用改为明确的一步一动作 |
| `envs/cartpole.py` | 连续牛顿输入、±10 N限幅、Gym接口 | 保持默认行为兼容；通过配置/包装器接场景和扰动 |
| `controllers/reference_pid.py` | 角度PID接口，默认Ki=0，含回中反馈 | 增加分量诊断；拆分可用于课程的控制器 |
| `runner.py` | 批量实验、CSV、报告、代码快照 | 抽出公用会话/记录器；支持短函数适配器 |
| `paths.py` | 用户代码与程序目录分离 | 增加课程进度、配置、模型和更新缓存位置 |
| `cli.py`、`.vscode/launch.json` | 软件启动与当前实验命令 | 保持旧命令；逐步增加课程/评价/训练入口 |
| `packaging/windows/installer.iss` | 安装器模板 | 验证正式安装器，接入升级流程 |

尚无：课程引擎、逐项开放观测、可配置初始状态/外力、正式评分器、短函数reset钩子、RL运行时、应用内更新。

## 2. 三个必须先解决的行为

### 2.1 手动体验与算法评分分开

当前鼠标是位置目标，推力为 `30*(target_x-x)-8*v`，再限制到±10 N。鼠标目标突然移到0.5 m时，本机仿真0.1 s后小车约到0.039 m，约0.5 s后到0.461 m；这是控制响应示例，不是显示延迟测量。另外，当前点击车身边缘会把该位置当车中心，未保存抓取点偏移。

实施顺序：

1. 先记录 `grab_offset_px = pointer_x - cart_center_x`。拖动目标为 `pointer_x-grab_offset_px`，按下但不移动时不能自己跑车。
2. 第一课新增 `manual_position_assist` 体验模式。鼠标指定小车轨迹，轨迹必须连续，并具有明确的速度/加速度上限；快速跳动、窗口缩放或光标出界不能产生无穷速度。
3. 小车受指定运动驱动时，杆仍按相同参数的受驱动动力学更新。可采用约束积分/逆动力学求所需力；不得只修改显示x或物理x、却不把支点加速度传给摆杆。
4. 先做小范围轨迹原型，与原力模型在相同可实现轨迹上对照。固定轨迹、运动方向、杆的响应方向均通过后，再做手感验收。超出标准电机能力的辅助动作单独记录，不伪装成±10 N控制成绩。
5. 松手默认切回零外加操纵力，保留物理速度；暂停才冻结状态。两种行为分别测试。
6. 第二课延续辅助体验并解释输入帮助；第三课主线切换为 `force_n`。目标速度是可选支线，显式经速度控制器转成力。

辅助体验记录 `input_mode=manual_position_assist`，不能进入PID/RL排行榜或同一评分表。软件继续复用参数、状态定义、记录器；“共享环境”不等于两种输入模式拥有相同约束。

开发推导入口：沿用当前Gym均匀杆参数，`l`为半杆长，给定连续轨迹的小车加速度`a`时，可用 `theta_ddot = (g*sin(theta)-a*cos(theta))/(4*l/3)` 更新杆；所需力由耦合方程反求 `F=(M+m)*a + m*l*theta_ddot*cos(theta) - m*l*omega**2*sin(theta)`。这是受驱动模式的实现草案，先用可实现的力轨迹与原模型逐步对照，再接鼠标；不得绕过这种耦合只平移小车图片。

手感验收候选：分别在常见窗口与缩放下，用匀速0.2 m/s的轨迹检查位置跟随误差和显示延迟；候选目标是稳态误差不超过5像素、动作可见延迟不超过100 ms。快速拖动触及速度/加速度限制时单独记录，不能把受限段算成普通跟随达标。具体阈值在原型和教师试用后冻结。

### 2.2 复位与挑战开始分开

“重新扶正”保持目前已修复的行为：`[x,v,theta,omega]=[0,0,0,0]`，暂停等待操作。理想模型在零输入下会一直静止。

以后提供独立的“开始挑战”：先加载非零初始状态/已记录的扰动，再开始计时。不能让零输入控制器靠全零初态获得平衡成绩。第一课保持自由探索、无分数；后续需要挑战时才出现按钮。

### 2.3 固定物理步与界面刷新解耦

现有界面20 ms计时器会在子进程等待时沿用上一动作推进仿真，`control()`调用次数可能少于物理步数。这会影响 `elapsed += dt`、积分和公平对比，需在教授L09以前修正。

拟会话状态机：

```text
PAUSED -> READY -> WAITING_ACTION -> APPLY_ONE_STEP -> READY
任意运行状态 -> PAUSED / FINISHED / ERROR
```

- 每个 `episode_id + step_id` 只请求一次动作；收到匹配结果才推进一个0.02 s物理步。
- 子进程较慢时降低实际播放速度；不能把窗口耗时作为dt，也不能悄悄重复旧动作。
- 暂停时不推进、不发下一请求；尚未返回的当前动作可缓存。重置增加episode_id，旧回包全部丢弃。
- 会话的逻辑时钟为 `step_index * dt`；GUI按独立绘图节奏显示最新状态，可插值但不能写回物理状态。
- 需要研究“真实时间延迟”时，使用显式延迟包装器和动作队列；这属于L29，不依赖随机电脑卡顿。
- 超时仍保留上限并停止本回合，不能以零动作悄悄顶替错误程序。

## 3. 拟新增代码目录

下面均为计划路径。按里程碑逐个创建，避免先生成大量空壳文件。

```text
src/control_lab/
  core/
    types.py                 # State, Action, StepResult, EpisodeSpec
    scenario.py              # 初值、扰动、噪声、延迟配置与验证
    session.py               # 一步一动作、暂停/重置/结束生命周期
    clock.py                 # 仿真时钟与播放速度
  inputs/
    manual.py                # 抓取点、连续鼠标轨迹、辅助模式
    velocity.py              # 速度指令转力，限幅与诊断
    adapters.py              # 短函数、类控制器、RL输出统一成牛顿
  controllers/
    p.py / pd.py / pid.py     # 可讲解的控制器、分量和状态
    centering.py              # 倒立摆回中；不复用普通小车的符号
    filters.py                # dt明确的一阶滤波器
    reference_pid.py          # 旧入口保留，代理到兼容实现
  envs/
    cartpole.py               # 现有基准力环境
    driven_cartpole.py       # 辅助位置轨迹驱动，完成验证后才启用
    cart_velocity.py          # 固定杆/单车速度PI专用场景
    wrappers.py              # 场景、外扰、测量、归一化动作
  lessons/
    schema.py / loader.py     # 课程清单加载、兼容与校验
    session.py / rules.py     # 课内步骤、白名单事件规则
    content/L01.json ...      # 教学步骤配置
    scenarios/               # 课程命名初态、扰动和目标计划
    templates/l05_*.py ...    # 学生代码起点；与用户副本分开
    solutions/               # 教师答案，默认不自动展示
  evaluation/
    protocol.py / metrics.py  # 固定用例、量纲与聚合
    compare.py                # 检查任务可比性、生成对照报告
    sweep.py / rescore.py      # 参数扫描、旧轨迹按新奖励重计分
  storage/
    records.py / progress.py  # 实验轨迹、课程进度、原子保存
    migrations.py            # 版本变化的备份与迁移
  desktop/panels/
    lesson.py / signals.py    # 右侧逐步引导、选择性读数
    controller.py            # P/D/I分量、参数对照
    training.py / updates.py  # 独立训练与更新界面
  rl/
    protocol.py / service.py  # 基础版只保留消息/进程接口
    env_factory.py           # 与正式评估共用配置
    rewards.py               # 可版本化的奖励与分量
    train.py / evaluate.py    # 仅训练环境导入SB3/PyTorch
    artifacts.py             # 模型和预处理元数据
  updates/
    releases.py / download.py # 查询、下载和完整性检查
    installer.py             # 安装器交接、退出、完成标记
  integrations/
    tita_profile.py           # 外部TITA环境配置与检查，后期可选
tests/
  test_session.py / test_scenarios.py / test_lessons.py
  test_adapters.py / test_metrics.py / test_progress.py
  test_rl_contract.py / test_updates.py
```

原 `desktop/app.py` 最终只组合窗口、面板和会话；它不能负责训练循环、奖励公式、算法评分或下载替换自身。

## 4. 核心接口草案

以下为设计示例，不是本轮可导入的新增API。先冻结数据契约，再逐个实现。

```python
from dataclasses import dataclass
from typing import Literal, Protocol

@dataclass(frozen=True)
class State:
    x: float                 # m
    v: float                 # m/s
    theta: float             # rad，向右为正
    omega: float             # rad/s

@dataclass(frozen=True)
class Action:
    value: float
    kind: Literal["force_n", "velocity_mps", "position_m"]

@dataclass(frozen=True)
class ForcePulse:
    start_step: int
    duration_steps: int
    force_n: float

@dataclass(frozen=True)
class TargetChange:
    start_step: int
    velocity_mps: float

@dataclass(frozen=True)
class ScenarioConfig:
    scenario_id: str
    initial_state: State
    disturbances: tuple[ForcePulse, ...] = ()
    target_schedule: tuple[TargetChange, ...] = ()
    observation_noise_seed: int = 0

@dataclass(frozen=True)
class EpisodeSpec:
    protocol_id: str
    scenario: ScenarioConfig
    dt_s: float = 0.02
    force_limit_n: float = 10.0
    max_steps: int = 500
    theta_limit_rad: float = 0.20943951023931956
    x_limit_m: float = 2.4

@dataclass(frozen=True)
class StepResult:
    episode_id: str
    step_id: int
    simulation_time_s: float
    true_state: State
    observed_state: State
    requested_force_n: float
    actuator_force_n: float
    disturbance_force_n: float
    net_force_n: float
    reward: float
    terminated: bool
    truncated: bool
    end_reason: str | None

class Controller(Protocol):
    def reset(self) -> None: ...
    def act(self, observation: State, dt: float) -> float: ...
```

所有数值先校验有限值；布尔值不充当动作。学生输出超限时记录原请求，再限幅。外界推力与电机力分别记录：电机±10 N不意味着总外力也要截到±10 N。若原CartPole包装器无法分离两者，先扩展明确的外扰入口，不能用现有同一clip把外扰一起截断。

控制器只能读取 `observed_state`；评分器读取 `true_state`。这样加测量噪声不会改变真实物理位置，也不会让评分直接受显示噪声污染。初值、噪声和扰动各有独立随机数流，互不消耗对方的种子序列。

### 学生函数到类的过渡

L05–L08继续使用现有接口：

```python
def control(state, dt):
    return 1.0
```

L09以后拟支持可选reset：

```python
elapsed = 0.0

def reset():
    global elapsed
    elapsed = 0.0

def control(state, dt):
    global elapsed
    elapsed += dt
    return 1.0 if elapsed < 0.2 else 0.0
```

约定：加载模块一次，每回合开始调用 `reset()` 一次，每个物理步调用 `control()` 一次。没有reset的旧函数继续工作；教师对有记忆练习检查reset是否完整。进程重启、课程重试和命令行评估都遵守同样语义。后续介绍类时，通过适配器接 `Controller.reset/act`。0.2.0 已实现短函数/类适配，GUI 保存的函数可用于正式 CLI 评价。

`State`是软件内部契约，不直接替换学生已有参数。适配器分别生成：短函数的 `dict(x=..., v=..., theta=..., omega=...)`、旧类的四元素数组/序列、RL的float32观测数组。转换顺序固定、单位固定，并传递副本；旧类中 `x,v,theta,omega = observation` 继续有效。学生不需要为了软件重构重写作业。

0.2.0 已提供 `lesson --id L13`、`evaluate --protocol balance-v1` 和 `train --output-dir ... --steps ...`，并保留 `gui`、`run`、`doctor`、`init-workspace`。原拟议的 `train --config ...` 未作为当前 CLI 参数，实际用法见 README 和 `--help`。

## 5. 课程配置与引导规则

拟清单最小示例：

```json
{
  "schema_version": 1,
  "lesson_id": "L13",
  "content_version": 1,
  "title": "比例控制：偏得越多，推得越用力",
  "prerequisites": ["L12"],
  "scenario_id": "angle-kick-practice-v1",
  "input_mode": "force_n",
  "visible_signals": ["theta", "force"],
  "template": "templates/l13_p.py",
  "steps": [
    {
      "id": "compare_gain",
      "instruction": "把系数从10改成30，用同一个初始倾斜再试一次。",
      "completion": {
        "all": [
          {"event": "experiment.saved", "min_count": 2},
          {"event": "reflection.submitted", "field": "p_gain_effect"}
        ]
      },
      "hints": ["先保持初始角度相同。", "只改乘在角度前面的数。"]
    }
  ]
}
```

- 加载器验证ID唯一、前置存在且无环、模板相对路径不越出课程资源目录、显示字段和事件均在白名单。
- 规则解释器支持 `all/any`、事件计数、数值区间和作业提交；不对JSON里的字符串使用eval。
- 文件保存次数只作过程证据，不能证明理解。涉及解释的问题由学生文字/选择回答或教师确认；不宣称自动判断自由文本正确。
- 正式表现分数取可信记录器的实际参数和轨迹，不能相信学生自己发送的“成功”事件；本地教学考核仍不是防作弊考试系统。
- 提示分三层：观察方向→相关概念→局部代码。参考答案在学生完成一次尝试后自愿查看，查看记录用于教师了解支持需求，不作为惩罚。
- 允许教师跳课，允许学生回看；默认前置提示不是不可解锁的付费式关卡。

课程进度示例存储字段：`schema_version, student_profile_id, lesson_id, content_version, completed_step_ids, attempt_refs, reflection, hints_opened, updated_at`。首次本地使用用匿名档案即可；这一阶段不做账号、云同步或班级排行榜。

## 6. 实验协议、扰动与评分

拟协议 `balance-v1` 的详细配置在 [协议草案](plans/benchmark_v1.proposal.json)。它需要先标定，再成为发布承诺。

| 项目 | 约定 |
| --- | --- |
| 力控制 | 所有被比较控制器最终输出牛顿，±10 N |
| 步长 | 固定0.02 s；观察数组顺序x、v、theta、omega |
| 结束 | \|theta\|>12°或\|x\|>2.4 m为terminated；500步上限为truncated |
| 初始条件 | 从发布时固定的非零状态用例表加载；不能用全零静置代替 |
| 数据划分 | 练习42–46；调参验证100–119；保留测试10042–10061 |
| 公平比较 | 同一用例状态、任务参数、外扰、观察权限和评价脚本 |
| 奖励 | 初版沿用Gym存活奖励；奖励实验独立版本，不混合比较原始回报 |

初值生成器拟沿用各分量[-0.05,0.05]区间，同时拒绝 `abs(theta)<0.01 rad` 的样本，确保存在可见偏斜。发布时固化生成后的四维状态及用例hash，不只保存随机seed。此规则不同于当前默认reset，实施后必须创建新协议版本并重跑参考基线。

扰动记录为明确的 `(start_step, duration_steps, force_n)`，例如第100步施加1 N共5步，作为初始教学候选。参数必须先由参考控制器与零输入对照标定；未验证不预设“一定能恢复”。测量噪声和延迟分别作独立组，不在初版同时打开多个难点。

每回合报告：存活步数、完成500步与否、真实角度RMS、最大\|x\|、控制力RMS、饱和比例、控制错误、结束原因、初值与种子。角度RMS只覆盖已运行时间，必须与存活时长一起看，避免“早倒下反而RMS小”。加噪声时同时保存观测与真实状态。

每组报告：完整回合率、步数均值/中位数/最差值、离散程度、逐回合明细。RL训练至少用3个独立根seed，分别报告；不能挑最好的一个模型冒充整体效果。模型挑选用验证集，保留集只在冻结配置后使用。改了控制器或奖励后，旧保留集结果不能继续称盲测。

## 7. PID课程实现要点

1. P、D、I与回中输出分量分开计算，最终统一限幅。日志保留 `p_n, d_n, i_n, centering_n, unsaturated_n, applied_n`。
2. 当前符号约定为正角度右倾、正力向右；参考控制是 `60*theta+12*omega+2*x+3*v`，不是通常独立小车位置环的负号组合。代码注释与课堂实验共同解释符号。
3. 第一次D直接读取omega，之后才教由角度差分估计角速度，避免把数值求导和PD同时作为新概念。
4. I先在明确标出的单车速度场景教学：恒定负载→P留下速度误差→积分累积→PI减小稳态误差。回到倒立摆后说明状态/模型变了，Ki=0仍可合理。
5. 条件积分按“输出已饱和且当前积分增量会加重饱和”暂停积累；反向误差允许释放积分。每回合重置，暂停不积分。
6. 噪声滤波参数随dt定义；分别展示滤波前后观测，不把平滑后的曲线当真实物理改善。

对照实验不要强制所有课都达到10秒平衡。L13/14的合理失败是用来理解缺少哪些信息；L21/22才要求规范比较结果。

## 8. 强化学习运行时

基础包继续只包含Qt/Gym/numpy等教学依赖。训练建议在独立Python运行环境安装锁定的SB3和CPU版PyTorch，先验证版本兼容再生成锁文件，不直接修改现有Isaac环境。Python3.11作为兼容性优先的候选；当前桌面3.13环境保持独立。

通信使用受控子进程与逐行JSON消息，不在Qt主线程训练。拟请求：`start, stop, status, evaluate`；消息：`progress, checkpoint, evaluation, stopped, error`，包含run_id、step_count、wall_time、路径。停止训练先在检查点边界保存，再退出；GUI关闭必须能选择保留独立任务或停止，不遗留不可见工作进程。

第一版采用PPO小型MLP、CPU、单环境建立基线，再决定是否并行。PPO支持连续Box动作；归一化动作 `a∈[-1,1]` 显式映射到 `F=10*a N`，评估适配器只转换一次。[SB3 PPO](https://stable-baselines3.readthedocs.io/en/master/modules/ppo.html)

环境检查先跑Gym/SB3 checker，再检查seed、reset、step类型与终止原因。`terminated` 与外部时间上限的 `truncated` 必须分别传递，不在自写包装器里合并丢失。[Gymnasium时间限制说明](https://gymnasium.farama.org/tutorials/gymnasium_basics/handling_time_limits/)

模型包至少包括：策略文件、训练参数、依赖版本、环境/协议hash、观察顺序和单位、动作缩放、奖励版本、训练seed、评价结果、源码提交ID。若使用观测归一化，要保存对应统计，评估时冻结更新；初版可先不启用运行统计归一化来减少变量。[SB3训练与评估建议](https://stable-baselines3.readthedocs.io/en/master/guide/rl_tips.html)

GUI回放通过独立推理进程调用相同适配器；第一版不要求导出ONNX。加载时发现观察维数、动作模式、协议版本不兼容则明确拒绝，不能默默裁剪或补零。

## 9. 用户数据与更新

拟数据布局在实际Documents目录下，不依赖系统盘符：

```text
ControlLab/
  workspace/<lesson_id>/<student_file>.py
  progress/profile.json
  runs/<run_id>/metadata.json + trajectory.csv + report.json
  models/<model_id>/...
  backups/<migration_id>/...
```

编辑器同时保留原模板版本、用户当前稿和实验快照。自动保存写临时文件再原子替换；运行中的代码用快照固定，学生继续编辑不会修改本回合结果。升级课程模板不覆盖学生文件，新模板另存并提示差异。读取失败恢复最近成功备份并告知，不清空学生目录。

更新工程原安排在 M6，以下保留设计要求；0.2.0 已有检查、下载校验、安装交接和 CI 实现，实际发布整链验收状态见实现审计：

1. 统一版本来源：从一个版本文件生成包元数据、`__version__`和Inno版本，校验三者一致。
2. 先验证安装器：固定AppId、按用户安装、升级复用目录，安装与数据分离。[Inno同一应用说明](https://jrsoftware.org/ishelp/topic_sameappnotes.htm)
3. GitHub Releases发布安装器、版本说明和校验信息；提供稳定通道，课堂默认不提示预发布。[GitHub Releases接口](https://docs.github.com/en/rest/releases/releases)
4. 后台检查→用户阅读说明→下载到缓存→校验→保存代码/停止仿真与worker→应用退出→安装器更新→确认完成再启动。
5. 不覆盖运行中的exe。下载失败继续使用旧版；安装失败记录阶段并提供旧安装包恢复入口。未经整条恢复路径实测不能宣传自动回滚。
6. HTTPS和SHA256用于传输/完整性；正式可信发布还需校验可信签名或经验证的发布源，不能把同源hash当发布者身份认证。发布令牌只放CI密钥，不打包进客户端。
7. 接入Actions时先产出草稿Release与测试结果，由维护者确定课程版本和正式发布；推普通代码不自动强推更新。网络不可用不影响已经安装的课堂。

## 10. 开发任务与验收

| ID | 里程碑 | 代码交付 | 必须通过的验收 |
| --- | --- | --- | --- |
| DEV-E01 | M0 | 状态、动作、EpisodeSpec和场景验证 | 单位/范围/非法值明确；旧CLI无行为回归 |
| DEV-E02 | M0 | session固定步与worker序号 | 一个动作只推进一步；暂停无步数；旧回包不污染重置 |
| DEV-E03 | M0 | manual抓取偏移、辅助位置原型 | 非中心按下不动；轨迹有限；杆响应支点运动；不得伪造评分 |
| DEV-E04 | M0 | 非零初值、外扰与复位分离 | 同场景可复现；全零静置不算挑战成功 |
| DEV-E05 | M1 | lesson schema/loader/rules | 无效ID/路径/循环前置能报告；无需eval |
| DEV-E06 | M1 | 课程面板与进度保存 | 重开恢复；查看提示；跳课；模板不覆盖用户作业 |
| DEV-E07 | M2 | 函数/reset/类适配器 | 每回合reset一次；每步control一次；旧代码可运行 |
| DEV-E08 | M2 | 公用记录器和快照 | GUI/CLI同配置同控制器轨迹一致；错误仍保留证据 |
| DEV-E09 | M3 | 控制器分量/参数对照 | 符号正确；切参开新实验；曲线和日志对应 |
| DEV-E10 | M4 | 单车速度模型、PI/抗饱和、滤波 | 模型名称清楚；积分重置；限幅/噪声实现可追溯 |
| DEV-E11 | M4 | 正式协议和比较器 | 不同协议拒绝合并；失败回合不遗漏；不只显示最好结果 |
| DEV-E12 | M5 | RL工厂/训练服务/模型包 | checker通过；可停止；正常保存；归一化动作只映射一次 |
| DEV-E13 | M5 | RL评价/回放 | 模型元数据不匹配拒绝；独立seeds报告；主线程不训练 |
| DEV-E14 | M6 | 安装包、版本生成、升级 | 全新Windows及旧版升级；保存/卸载/数据保留 |
| DEV-E15 | M6 | GitHub检查/下载/安装交接/CI | 超时、取消、错误hash、安装失败均可退出且保住作业 |
| DEV-E16 | M7 | 延迟/外扰实验、外部TITA配置 | 普通课堂无Isaac依赖；TITA模型不当CartPole策略加载 |

一次提交建议只完成一项契约和其必要验证。每完成一课，交付清单是：课程配置、学生模板、教师参考、已知失败案例、验收证据、用户说明，而不是只有一个能运行的动画。

## 11. 验证矩阵与发布门槛

| 层级 | 重点 | 运行时机 |
| --- | --- | --- |
| 物理/输入 | force映射、初值、脉冲力、辅助约束、噪声不改真值 | 相关逻辑修改后 |
| 时间/生命周期 | 暂停、reset、超时、进程死亡、迟到结果、单步 | 会话或进程修改后 |
| 课程 | 32课ID/前置/资源引用、提示、进度迁移 | 新增/修改课程配置后 |
| GUI | 拖动偏移、读数显隐、代码错误、分量图、保存反馈 | 面板或交互修改后 |
| 算法评估 | 参考基线、同输入可复现、统计包含失败、协议hash | 物理/控制器/协议修改后 |
| RL | 256步级别烟测验证管道；完整训练单独人工验收 | 训练API或依赖修改后 |
| 分发 | 冻结exe子进程、无Python新机器、从旧安装器升级 | 发布候选版本 |
| 教学 | 3–5名新手观察：卡在哪步、能否解释、提示依赖 | 每个课程阶段首版 |

发布门槛分开：软件门槛是功能正确、文件可保留、错误可恢复；教学门槛是学生能独立完成并解释；算法门槛是已标定协议下达到指定表现。不能用“训练进程跑完”代替“学生理解”或“策略稳定”。
