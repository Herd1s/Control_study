# ControlLab 0.2.1 验证记录（发布候选）

记录日期：2026-10-08。范围为 `E:/Workspace/ControlLab` 的 0.2.1 源码增量。本文区分实际执行、源码功能与待验收项，不将课程 JSON 能加载、手动确认或测试数量等同于零基础学生已完成学习。

## 候选身份与发布状态

| 项目 | 当前状态 |
| --- | --- |
| 源码版本 | `control_lab.__version__ = "0.2.1"` |
| 已提交产品源码身份 | `198966063916ea072c6b83ff1d5eba6c973d7c0c`，已推送main；标签 `v0.2.1` 指向此产品提交，后续仅追加验收文档 |
| 分项源码测试、真实 Qt/CLI 探针 | 下文已有实际证据 |
| 最终全量源码测试 | **249 passed、34 subtests passed，171.71s**；5项Gym空间声明warnings，见 `logs/source-021-full-tests.txt` |
| 依赖一致性 | 基础和独立RL环境 `pip check` 均通过；冻结模块路径与安装后独立运行均已验证 |
| 0.2.1 wheel/便携包/安装器 | **本地构建与实际安装升级通过**；产物身份和运行边界见下文 |
| 0.2.1 GitHub Actions | 远端运行与资产已由根代理核验；精确运行URL、结果与CI资产身份由根代理在本地文档交还后追加 |
| 0.2.1 Release | **已创建草稿，尚未公开**；Release ID405970519，实际下载及SHA核对通过 |

部分本轮早期证据在源码增量过程中生成，其元数据仍显示 0.2.0；这反映采集时的版本号，不能将其称为最终 0.2.1 冻结包验收。最终包需重新记录自身版本、模块来源和哈希。旧版证据见 [VALIDATION_0.2.0.md](VALIDATION_0.2.0.md)。

## 本地构建产物

`scripts/build_windows.ps1` 本地构建成功，完整日志为 `logs/build-v021-final.log`；其中Inno Setup编译44.578s成功。产物清单来自 `logs/v021-artifacts.json`：

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `ControlLab-Portable-0.2.1-windows-x64.zip` | 81,758,702 | `5c85b7e41d21ce826880127a575d3ca0fb3b77a976526075abc290f76f397c1b` |
| `ControlLab-Setup-0.2.1.exe` | 53,283,538 | `e37b903256d740d08885ae47491adf45606d98237b02d6ab40d6e98314250473` |
| `control_lab-0.2.1-py3-none-any.whl` | 402,037 | `4f65f96d0f7ca20bb9a3597bf7b6b7f004383b6635830b18ad5e65c1d81ad32f` |

以上是本地候选字节，后续CI重建资产需要另行校验，不能假定哈希相同。

### 发行wheel的独立运行

`logs/wheel-021-final-validation/evidence.json` 已验证上表402,037字节的实际发行wheel，SHA256与runtime manifest一致。`.venv-rl` 以正式wheel安装，**非editable**；8个核心模块均从该环境 `site-packages` 加载，环境没有Qt。工作目录位于工程外空目录，使用 `python -I`：

- doctor、课程资源读取通过；包内32份content共288,978字节、28份templates共15,713字节、28份solutions共16,368字节。
- 实际detached训练256步、保存模型、重新加载20个validation用例、目录关联1份报告及`pip check`通过，runner正常退出。
- 20回合控制器错误为0，完整时长为0/20，均因角度越界结束。这是短任务和发行wheel流程验收，不称学会平衡。

该结果属于本地源码提交 `1989660` 对应的发行wheel；冻结GUI与覆盖安装是下文独立验证，后续CI运行及资产也另行记录。

### 真实0.2.0→0.2.1覆盖安装

最终机器记录为 `logs/installer-test-v021-final/report.json`，`status=passed`，没有error或cleanup_error。测试前检查无同AppID注册，只在日志目录创建隔离安装。旧版使用实际CI生成的0.2.0安装器（SHA256 `c5863435eb46b21b2a9b8077aab46ce7329bf3b8aba033c283572d20050a8cf6`），新版使用上表0.2.1安装器；未把新版重命名冒充旧版。

1. 旧版安装并实际运行后，不给新版安装器另传目录；同AppID正确沿用旧安装位置，注册表与安装marker变为0.2.1。
2. 升级前后6份实际学生文件逐一SHA256相同，覆盖笔记、进度与备份、学生源码和实验轨迹/报告。
3. 安装目录同时保留实际旧/新wheel，`setup-rl.ps1 -ValidateOnly` 按manifest选择0.2.1并核对正确哈希。
4. 最小PATH为 `C:\WINDOWS\System32;C:\WINDOWS`，工作目录为独立空目录。冻结doctor、32课读取与参考控制20个validation回合均通过，后者每例500步、零控制器错误。
5. Windows UI Automation通过现有界面操作新旧程序，实际启动学生worker；Python DLL、模块和搜索路径都来自该安装目录 `_internal`，关闭GUI后worker退出。
6. 安装后的GUI调用正式wheel所在独立RL解释器，doctor、20回合评价、模型回放使用3个实际独立进程且全部退出。既有短训模型平均37.95步、最差28步、完整回合0/20、控制器错误0；回放 `validation-100` 实际34步结束。没有把短模型称为平衡成功。
7. 验收后仅卸载本次隔离安装，注册项和应用EXE清理；原6份学生文件仍保留相同哈希。

首次记录 `logs/installer-test-v021/report.json` 保留失败状态：QA的PowerShell5包装器受PSModulePath影响找不到Get-FileHash，发生于外部RL检查；产品安装脚本使用.NET哈希且已通过。修正日志目录里的QA包装器、正常关闭其残留窗口后，从无AppID注册状态重新跑完整验收，最终报告使用独立的`-final`目录。没有把首轮失败抹成成功，也没有为绕过测试修改产品二进制。

### 冻结程序的L19生命周期

`logs/frozen-v021-lifecycle/lifecycle-final/lifecycle-result.json` 对上表候选中的真实 `ControlLab.exe`（SHA256 `cfdea818fa0fd411a2c53a8054b100831eed05184b67f199f4be188448410ff3`）使用原生UI Automation操作，三分支均通过：

| 学生程序 | 实际观察 |
| --- | --- |
| 无reset | 模块只载入1次；同一worker在新回合继续计数，由9到10，不自动清除模块记忆 |
| 有reset | 模块只载入1次，启动和新回合共reset2次；相同初态的首动作计数均为1 |
| 第二次reset异常 | 界面显示错误，control调用数保持10，不继续推进新回合 |

三种路径关闭后worker都结束。这是最终冻结二进制的验收，不仅是源码Qt测试。

### 冻结界面启动持久化训练

`logs/frozen-v021-task/results/result.json` 验证实际发行程序中的新增路径：原生UI Automation点击L25“运行256步通路检查”，冻结0.2.1经TaskStore登记任务，启动`.venv-rl`正式wheel中的`task_runner`。任务实际完成256步并保存`policy.zip`，界面收到完成结果后正常关闭。该项覆盖冻结GUI→持久化任务→外部运行时，并非直接调用后端来替代界面按钮。

最终验收的隔离安装已正常卸载，检查没有ControlLab进程或AppID注册。首轮失败QA遗留目录 `logs/installer-test-v021/app` 的递归清理被自动审批以 `blocked by policy` 拒绝，因此保留；未绕过拒绝，也未把日志目录全部清空写成通过条件。这不影响`installer-test-v021-final`的完整升级、卸载与数据保留结果。

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

更新缓存恢复后端与UI相关 **15项通过**（`tests/test_updates.py`、`tests/test_updates_panel.py`）。坏哈希、扫描后篡改均拒绝；恢复仍需用户明确确认。根代理后加安装器启动失败恢复按钮及主窗关闭的相关检查 **2 passed，9.59s**。这里没有执行破损安装→真实重装全链路。运行时包manifest另有 **7项实际PowerShell测试通过，3.30s**（`tests/test_runtime_bundle.py`），用于识别正确wheel、清单和哈希；旧新版wheel共存时只选择manifest指定的版本。后续冻结构建结果单列，不能从脚本测试推断安装器已经通过。

TITA有界可视回放已实际通过，证据为 `logs/tita-visible-play-validation-v2/bounded-play-result.json`。运行原始 `play.py`、`Play-v0`、`headless=False`、1个环境，实际执行120次 `wrapper.step`，8个动作均为有限值，进程退出码0，日志有正常 `Simulation App Shutting Down`。使用既有 `model_2` checkpoint，没有重训或操作硬件。

| TITA证据 | SHA256 |
| --- | --- |
| `steps.jsonl` | `79ef7784955fd3330c2739052d82a9577e9fb208f5e1956edd5e04c3f2cb9175` |
| 既有`model_2` checkpoint | `65c25a660de5f7f75371ccd330e1b642d85c562b0ab92dda34ff47b9a990dc78` |

这证明有界仿真、推理和正常退出通路，不证明平衡性能或实机安全。首轮探针包装器访问 `Gym wrapper.scene` 报错，之后只修正日志目录里的探针包装器；原失败记录保留，不冒充产品成功。先前headless/ONNX/PT导出和0.2.0安装证据也不挪作0.2.1最终包通过结果。

## 待完成与不包含的验收

- **软件选修功能**：L29可配置域随机化训练尚未实现，目前只有实验设计；不能写已完成随机化训练或迁移。
- **教学效果**：3–5名零基础学生试讲、独立复述、实际手感与课程节奏尚需真人；完成软件事件不等于理解。
- **本版发布**：源码提交、本地wheel/冻结包/安装器构建、受控最小PATH下运行及真实0.2.0→0.2.1升级已通过；标签v0.2.1、CI构建及实际下载资产校验已通过；Release保持草稿，未向学生发布更新。后加测试单列，不能把分项数字直接相加作全量数量。
- **部署外部边界**：干净Windows机器、公开Release下载到应用内安装完成全链路、安装强制中断恢复、Windows代码签名未验证或未配置。本地实际安装覆盖/卸载保留数据与源码缓存恢复测试均有各自证据，不能与尚未完成的外部验收混为一谈。
- **机器人边界**：没有进行TITA实机控制，没有给硬件上电或发运动指令；仿真接口和模拟停止实验不能替代真实机器人接口、限位和安全验收。

原规格缺口逐项追踪见 [SPEC_GAP_AUDIT.md](SPEC_GAP_AUDIT.md)。该审计保留发现时的原要求，并追加修复及证据，不通过降低原要求来宣称完成。

## GitHub 云端构建与实际下载

[Actions 37653826940](https://github.com/Herd1s/Control_study/actions/runs/37653826940) 成功完成：Windows CI **254 passed、4 skipped、34 subtests passed，98.46s**。4项跳过需要独立RL解释器；对应独立环境、Qt任务生命周期和最终wheel另有上文真实证据。5项warnings是Gym空间声明。随后云端实际构建安装器/便携包，冻结CLI doctor、32课资源与参考控制器20回合评价均通过。

Release ID `405970519`，标签 `v0.2.1`，API核对 `draft=true`、`published_at=null`。草稿不会出现在学生软件的公开更新检查中；本次没有进行正式发布。

已实际下载 Actions artifact `11498286879`（136,050,882字节），SHA256 `61d50b4624d42ae9e29970df0d2c1ae57ea57389343c3bca10249471bb03ddd2` 与GitHub记录一致。解包逐个核对下列文件的字节数、API digest与SHA256SUMS，全部一致。证据：`logs/github-ci-021-validation/api-evidence.json`、`verification.json`。

| 云端资产 | 字节数 | SHA256 |
| --- | ---: | --- |
| `ControlLab-Portable-0.2.1-windows-x64.zip` | 83,697,914 | `aa6f480d9da3a8809a0d2c12d27cdde123483e5f458581fb363543727fecddf3` |
| `ControlLab-Setup-0.2.1.exe` | 53,346,688 | `547de5099ac8362daadf6b87a47bdf90a8578b845dbc8cc3d2f09a80caf5a84d` |
| `SHA256SUMS` | 203 | `a1dd3829464eb1a87df5912ebf60d6518dae78d9deca26d14e00698810024531` |

云端便携包中的runtime manifest与wheel SHA也一致；32课JSON、28练习、28参考答案齐全。tasks、task_runner、catalog、centering与主窗源码字节与标签源码相同。云端与本地是两次构建，hash不同分别记录；没有把本地安装验收冒称对云端安装器字节做过同一次安装。
