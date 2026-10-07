# ControlLab 0.2.0：从亲手平衡到强化学习

ControlLab 是独立的 Windows 倒立摆教学软件：先拖动小车建立直觉，再观察状态、写几行 Python，逐步学习 P、PD、PI/PID，最后在同一连续推力任务上训练并比较强化学习策略。基础课堂使用 CPU，不依赖 Isaac Sim、TITA 或 NVIDIA 显卡。

软件提供 32 课的引导、练习模板、提示和参考答案，支持保存代码、实验轨迹与学习进度。传统控制面板可查看 P/I/D 分量、限幅、积分与滤波；对照实验在后台进程运行并保留每个回合的结果。强化学习需要另行配置独立 Python 环境；TITA 课程连接已有外部仿真工程。课程中的观察、解释和外部操作由学生或教师确认，进度勾选不等于算法已经达标。

## 打开软件与 VS Code

安装版从开始菜单打开 **ControlLab**；便携版双击 `ControlLab.exe`，分发时保留整个文件夹和 `_internal`。两者均包含基础课堂运行时。

开发时在 VS Code 打开 `ControlLab.code-workspace`，首次运行：

```powershell
# 将路径替换为本机 Python 3.11–3.13；本工程使用 3.13 验证
.\setup.ps1 -Python 'C:\Python313\python.exe'
.\.venv\Scripts\python.exe -m control_lab
```

若 PowerShell 阻止脚本执行，可对本次调用使用 `powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Python 'C:\Python313\python.exe'`。

VS Code 的 Python 解释器选择项目的 `.venv\Scripts\python.exe`，调试配置选择 **ControlLab：教学软件** 后按 F5。编辑 [examples/first_action.py](examples/first_action.py)，选择 **Python：我的第一段控制**，可将文件载入 Python 入门课 L05；保存修改后重新载入并点击“运行代码”。

```powershell
.\.venv\Scripts\python.exe -m control_lab doctor
.\.venv\Scripts\python.exe -m control_lab lesson --list
.\.venv\Scripts\python.exe -m control_lab lesson --id L13
```

## 写自己的控制器

入门使用短函数，状态字典包含 `x`、`v`、`theta`、`omega`，单位分别为 m、m/s、rad、rad/s；`dt=0.02` 秒。推力模式返回牛顿，正值向右，执行器统一限制为 ±10 N。

```python
def control(state, dt):
    return 0.0  # 先观察，再逐步写出自己的反馈规则

def reset():
    pass        # 有积分或历史状态时，在这里清空；无状态时可省略
```

短函数和旧版 `Controller.reset()/act(observation, dt)` 均可用于正式评价。目标速度是独立教学模式，返回值为 m/s，不能把它当作推力参加 `balance-v1` 评价。全零输出模板会倒下，这是待完成练习的预期效果。

```powershell
# 创建学生工作区，不覆盖已有代码
.\.venv\Scripts\python.exe -m control_lab init-workspace 'D:\我的控制实验'
# 动画演示参考控制器
.\.venv\Scripts\python.exe -m control_lab run --controller reference --render
```

参考控制器默认为角度 PD 加小车位置、速度反馈，`Ki=0`；积分用于解释偏差与饱和问题，并非所有平衡任务都必须加入。源码在 [controllers](src/control_lab/controllers)。

## 公平比较控制效果

“重新扶正”是全零状态的暂停体验；正式 `balance-v1` 使用冻结的非零初态、50 Hz 控制周期、±10 N、12°/2.4 m 终止边界和 500 步上限。手动辅助体验不进入同一评分表。

```powershell
.\.venv\Scripts\python.exe -m control_lab evaluate --controller reference --split validation --output-dir runs\reference-validation
.\.venv\Scripts\python.exe -m control_lab evaluate --controller student --controller-file 'D:\我的控制实验\my_controller.py' --split validation --output-dir runs\student-validation
.\.venv\Scripts\python.exe -m control_lab compare runs\reference-validation\report.json runs\student-validation\report.json --output runs\comparison.json
```

每次使用新的输出目录。报告包含成功率、平均/最差步数、控制错误和全部回合，另存协议、控制器快照及 CSV 轨迹。比较器拒绝不同场景、观测、输入模式或用例集合的混合比较。练习集 5 例，验证集 20 例；保留集需先冻结控制器并提供验证报告中的 SHA256，不能反复查看保留集调参。

界面中的“对照实验与报告”可选择控制器与练习/验证集，后台运行期间可停止；被取消的评估不记为完整成绩。便携版终端用 `ControlLabCLI.exe` 替换上面的 `.venv\Scripts\python.exe -m control_lab`。

## 独立强化学习环境

基础安装包不包含 PyTorch。首次训练需要联网下载依赖，并使用 Python 3.11–3.13 建立独立 CPU 训练环境：

```powershell
# 在源码工程根目录运行，创建 .venv-rl
.\setup-rl.ps1 -Python 'C:\Python313\python.exe'
.\.venv-rl\Scripts\python.exe -m control_lab.rl.service doctor
.\.venv-rl\Scripts\python.exe -m control_lab train --steps 25600 --seed 0 --reward survival-v1 --output-dir runs\ppo-seed0
.\.venv-rl\Scripts\python.exe -m control_lab evaluate --model-dir runs\ppo-seed0 --split validation --output-dir runs\ppo-validation
```

已安装或便携版在程序目录运行 `runtime\setup-rl.ps1 -Python 'C:\Python313\python.exe'`。它安装随包提供的运行时 wheel，将训练环境放入系统“文档”目录下的 `ControlLab\runtimes\rl`；不把依赖写进程序目录。安装完成后，将脚本打印的 Python 路径填入软件强化学习页，点击“检查环境”，再训练、停止并保存、继续训练、验证或回放。

PPO 使用同一物理任务，归一化动作仅转换一次为牛顿推力。模型目录包含策略、训练配置和完整性信息；短运行成功只证明训练与保存通路可用，策略是否稳定必须看独立验证结果。模型不能直接用于 TITA 实机。

## 数据、更新与分发

默认用户数据位于系统“文档”目录的 `ControlLab` 文件夹，包含练习、进度、报告、模型和更新缓存；系统文档可能重定向到 OneDrive。源码目录和软件安装目录与这些数据分开。自行指定的实验目录由自己管理。

更新页默认仓库为 [Herd1s/Control_study](https://github.com/Herd1s/Control_study)，已有自定义设置优先。打开页面不会联网；检查、下载、安装分别点击。尚无正式 Release 时会明确提示。下载验证 HTTPS 来源、大小和 SHA256，安装前再校验；SHA256 验证文件一致性，不是发布者数字签名。安装前保存作业并停止实验，向导完成后可选择重新打开软件。

```powershell
# 生成整个便携目录
.\scripts\build_windows.ps1
# 使用本机已有 Inno Setup 生成安装器
.\scripts\build_windows.ps1 -Installer -Iscc 'C:\路径\Inno Setup 6\ISCC.exe'
```

构建和发布步骤见 [RELEASE_GUIDE.md](RELEASE_GUIDE.md)。版本唯一来源为 [src/control_lab/__init__.py](src/control_lab/__init__.py)。安装器按用户安装，使用固定 AppId 覆盖升级；卸载脚本不删除文档中的学习数据。

本机测试与便携版运行不等于干净机器上的安装、覆盖升级和卸载验收；GitHub Actions 工作流只有实际运行后才算验证。发布前按发布指南逐项记录证据。[验证记录](docs/VALIDATION.md) 应按版本查看。课程规划入口为 [ROADMAP](docs/ROADMAP.md) 与 [DEVELOPMENT_PLAN](docs/DEVELOPMENT_PLAN.md)，其中设计项以当前代码和版本验收记录为准。
