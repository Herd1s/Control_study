# ControlLab 0.2.1 验证记录（候选初稿）

记录日期：2026-10-08。范围为 `E:/Workspace/ControlLab` 的 0.2.1 源码增量。本文区分实际执行、源码功能与待验收项，不将课程 JSON 能加载、手动确认或测试数量等同于零基础学生已完成学习。

## 候选身份与发布状态

| 项目 | 当前状态 |
| --- | --- |
| 源码版本 | `control_lab.__version__ = "0.2.1"` |
| 最终提交与源码树身份 | 待冻结、待记录提交 SHA |
| 分项源码测试、真实 Qt/CLI 探针 | 下文已有实际证据 |
| 最终全量源码测试 | **249 passed、34 subtests passed，171.71s**；5项Gym空间声明warnings，见 `logs/source-021-full-tests.txt` |
| 依赖一致性 | 本地 `pip check` 通过；最终冻结包仍需独立检查 |
| 0.2.1 wheel/便携包/安装器 | **待构建和独立验收**；产物字节数与 SHA256 待填 |
| 0.2.1 GitHub Actions | **待运行并记录 URL、提交、结果** |
| 0.2.1 Release | **未声明正式发布**；草稿/公开状态与资产校验待填 |

部分本轮早期证据在源码增量过程中生成，其元数据仍显示 0.2.0；这反映采集时的版本号，不能将其称为最终 0.2.1 冻结包验收。最终包需重新记录自身版本、模块来源和哈希。旧版证据见 [VALIDATION_0.2.0.md](VALIDATION_0.2.0.md)。

## 基础课与工作区

根代理完成 `tests/test_student_workspace.py`、`tests/test_lessons.py`、`tests/test_teaching_charts.py` 的最终相关运行：**33 passed，24.07 s**。该结果由根代理实际运行报告；最终统一日志在全量验收栏补充，不伪造单独日志。

覆盖的关键行为包括：逐步预测/解释/草稿持久化及修订、步骤导航与新版要求识别、模板保留和差异、独立试算及分支、真实短片和预测卡、固定 10 物理步自动暂停、渐进读数/参数显隐、积分面积与控制器积分区分。保存失败不能先发已保存完成事件；运行中编辑的草稿不改变已启动源码快照。

L16 主窗测试实际运行两次 500 步：相同 `offset_right` 初态 `x=0.2 m`，只保杆的 PD 未回中；完整回中反馈首次达标为 **3.08 s**。测试核对真实行记录、界面标签和 `centering.reached` 事件；L13 参数页到第 7 步开放，L16 回中增益到第 3 步开放。

可视探针归档：`logs/ui-v021/evidence.json`。常用窗口 1380×860 与紧凑布局 853×480 逻辑尺寸有实际检查；L17实际100步后，面积与控制器主动报告的积分均为 `0.40410744403954585`，诊断有效、无错误。`L17.png` 与 `compact-guide.png` 已由根代理目检。这不是所有显示器、所有缩放和全部32课均完成真人视觉验收的声明。

## 评价、复算、传统控制与项目导出

最终分项命令：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_centering_analysis.py tests/test_control_course_tools.py tests/test_evaluation_panel.py tests/test_isolated_evaluation.py tests/test_recording_reproduction.py tests/test_control_adapters.py tests/test_recording_replay.py tests/test_evaluation.py -q
```

结果：**47 passed，102.32 s**。原始输出：`logs/control_course_validation_v021_final.txt`。主要实际证据如下：

| 行为 | 实际验证 | 证据入口 |
| --- | --- | --- |
| 学生独立评价 | 顶层导入、reset、control/diagnostics 超时均可结束；每例错误保留；健康回合不重复初始化；错误后新worker；取消保留部分报告 | `tests/test_isolated_evaluation.py` |
| Windows 强杀清理 | 实际启动评价父 CLI，再终止父进程；学生 worker 随 Job Object 退出，已完成回合 CSV/report 保留 | 同上；不是只模拟异常 |
| GUI→CLI逐值复算 | 力输入、速度输入、单车 PI、角度噪声、观测延迟，含非默认dt及脉冲；同配置/源码记录复算最大差为0 | `tests/test_recording_reproduction.py` |
| 正式报告读取/比较 | 验证协议、案例、代码身份及路径；完整长回合和提前失败回合同时间对照，末端不补造样本；PPO报告不导入模型也可读 | `tests/test_control_course_tools.py`、`logs/l28-root-integration/evidence.json` |
| 三方法项目包 | 解压真实项目ZIP，执行包内生成的三种方法入口重新评价，三个aggregate与原报告一致 | `tests/test_control_course_tools.py` |
| P/PI真实扫描 | Qt按钮启动真实CLI，输出候选轨迹/CSV/指标/共同时间曲线；PI使用独立单车协议 | `logs/control_tools_evidence_v021_styled/verification.json`及目录内scans |
| 回中持续窗口 | 双阈值、严格1s窗口、缺样中断、位置过零但速度过大不通过；杆角失败与小车边界失败分开；在线/离线相同 | `tests/test_centering_analysis.py`、`logs/centering_validation_v021.json` |

回中对照：只保杆方案到 10 s 仍停在 `x=0.2 m`，杆未倒、回中时间为 `None`。完整反馈在 2.08 s 进入位置/速度双容差，3.08 s 完成第一个 1 s 窗口，10 s 时当前连续时长为 7.92 s。这是公布场景的实测结果，不保证任意扰动均通过。

PI 对照：12 s 内无保护方案未恢复；积分限幅在目标切换后 **1.86 s** 恢复，条件积分 **6.02 s**。恢复定义为目标速度误差不超过 0.03 m/s、相邻实测状态跨度至少 1 s。条件积分并不总是最快，报告保留这种取舍。

正式回放在根主窗的 L28 集成证据中，共同时间为 10.00 s，短 PPO 轨迹在 0.68 s 已结束，界面明确“此时无后续样本”，完整反馈继续显示 10 s 实测状态。完成事件包含真实 `compared=true`，并非人工构造成功事件。

采用产品字体/样式的实际小窗口截图位于 `logs/control_tools_evidence_v021_styled/`。长路径不会撑出图表；内容通过滚动可达。更早无产品字体的试截图不作为最终界面证据。

## 强化学习增量

详细课程差距和逐项状态见 [REQUIREMENT_GAPS_0.2.1.md](REQUIREMENT_GAPS_0.2.1.md)。本轮已有真实证据：

| 实验 | 结果和边界 | 证据 |
| --- | --- | --- |
| 自定义奖励全链 | 版本化奖励→CPU PPO实际256步→保存→新进程重载→20验证/20保留；错误模型冻结拒绝 | `logs/rl-021-pipeline-20261007_235220/evidence.json` |
| 零训练基线 | 真实未learn模型包和5练习回合，训练步数0 | 同目录untrained及evidence |
| RL环境契约 | −1/0/1实际映射−10/0/10N；零力31步倾倒terminated；参考500步truncated | `logs/rl-021-panel-validation/evidence.json` |
| 鲁棒性面板 | 真实Qt触发5初态×7因素×PD/PPO，70回合、14组摘要；同方法组配置与噪声公平，保存失败与轨迹 | 同目录robustness及evidence；本次推理未新增训练 |
| 后台任务生命周期 | 真正退出父界面后任务继续；新界面恢复监控并停止，实际333步保存；不是只隐藏窗口 | `logs/persistent-training-021-validation/evidence.json`、`tests/test_training_tasks.py` |
| 关闭主窗的三个选择 | 实际点击取消、保留任务、停止保存；取消不写STOP，保留后新窗重连同任务，停止写STOP后异步关闭 | `logs/persistent-training-021-validation/window-close-evidence.json`、`tests/test_training_window_close.py` |
| 模型目录 | 实际索引3模型包、关联2报告并经Qt选择；按模型/元数据/报告指纹匹配验证来源，不加载策略来做索引 | 同目录evidence及`model-catalog-native.png` |

256 步自定义奖励模型验证与保留集均为 **0/20 完整回合**，但控制器错误为0；分别平均37.25和36.0步。它证明训练、奖励保存、重载与冻结评价通路，不证明学会平衡。保留集只用于验证软件冻结流程，未据此再调参。

RL代理另有35项课程/奖励/鲁棒性相关测试、14项训练面板/奖励回归、持久化任务和现有流程13项及目录Qt3项通过的分项记录；这些覆盖有重叠，不相加作为总测试数。新增主窗关闭测试另有 **1 passed，9.04s**，三种close调用分别约20/50/30ms，主窗不阻塞等待训练结束。该次在启动阶段0步停止并保存有效模型，不能与前一项333步跨父进程生命周期实验混为同一次。旧版三独立seed长期训练证据继续引用旧记录，不算本轮新增训练。

独立 `.venv-rl` 运行时另行验证：**21 passed，0 skipped/failed/errors，7.29s**，覆盖核心契约、奖励及鲁棒性；该解释器不含PySide6，版本为0.2.1，`pip check` 无冲突，只有2项Gym观测空间无界声明warning。证据：`logs/rl-021-independent-validation.json`、`logs/rl-021-independent-tests.xml`。这是独立环境验证，不并入基础环境249项数字，也没有新增训练。

## TITA 与更新交接

TITA实际接口与模拟命令门的证据为 `logs/tita-interface-panel-validation/result.json`：真实外部QProcess加载单环境配置，得到policy观测形状 `[1,10,33]`、8个动作、控制dt 0.02 s；动作与观测的关节顺序不相同，接口表明确记录。对应接口/模拟规则相关测试18项通过。

L32四个模拟用例共18个trace步骤验证限幅、超时归零、stop、急停锁存及明确rearm；错误的gate实现能被测试检出。记录始终 `hardware_control=false`、`ready_for_hardware=false`。这里没有把模拟命令门写成机器人急停或实机安全认证。

本轮TITA可视回放、更新安装确认的更晚证据如有追加，由对应代理核对后补入；先前headless/ONNX/PT导出和0.2.0安装证据不挪作0.2.1最终包通过结果。

## 待完成与不包含的验收

- **软件选修功能**：L29可配置域随机化训练尚未实现，目前只有实验设计；不能写已完成随机化训练或迁移。
- **教学效果**：3–5名零基础学生试讲、独立复述、实际手感与课程节奏尚需真人；完成软件事件不等于理解。
- **本版发布**：全量源码249项与34子项已通过；最终源码提交、wheel/冻结包/安装器构建、0.2.1干净路径运行及升级验收、CI、Release资产校验仍由根代理填入真实结果。后加测试单列，不能把分项数字直接相加作全量数量。
- **部署外部边界**：干净Windows机器、公开Release下载到应用内安装完成全链路、安装强制中断恢复、Windows代码签名未验证或未配置。0.2.0真实安装覆盖/卸载保留数据和CI资产已验证，详见旧版文档；不能继续说安装能力完全未测试，也不能据此宣称0.2.1新包已通过。
- **机器人边界**：没有进行TITA实机控制，没有给硬件上电或发运动指令；仿真接口和模拟停止实验不能替代真实机器人接口、限位和安全验收。

原规格缺口逐项追踪见 [SPEC_GAP_AUDIT.md](SPEC_GAP_AUDIT.md)。该审计保留发现时的原要求，并追加修复及证据，不通过降低原要求来宣称完成。
