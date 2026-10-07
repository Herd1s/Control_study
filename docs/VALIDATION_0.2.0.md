# ControlLab 0.2.0 本地验证记录

日期：2026-10-07。环境：当前 Windows x64 开发机、Python 3.13.5；桌面 `.venv` 与 CPU 训练 `.venv-rl` 分开。本文按证据区分源码、冻结程序、安装及远端发布。当前实现范围和教学限制见 [实现审计](IMPLEMENTATION_AUDIT.md)。

## 源码与独立训练环境

- 最终桌面源码测试：**168 项通过，34 个子测试通过**，105.75 秒；5 条 Gymnasium 环境检查提示。日志：`logs/pytest-v020-final.log`。
- 独立 RL 合约测试：**11 项通过**，2.77 秒；2 条 Gymnasium 提示。日志：`logs/pytest-v020-rl.log`。这些提示涉及未限定观测边界和原始牛顿动作空间；训练适配器另有归一化动作契约。
- 桌面环境 `pip check` 通过；`requirements-lock.txt` 已按当前环境导出，训练依赖单独锁定。
- 更早的 0.2.0 候选 wheel 在新的独立环境安装、从工程外目录加载成功，没有拉入 Qt/pygame，课程资源齐全；见 `logs/wheel-runtime-validation.json`。此记录含当次 wheel 哈希，不能自动代表后续重建产物。

## 最终 wheel 的隔离运行验收

最终构建后，沿用第一次验收建立的 `logs/wheel-runtime-test` 非 editable 隔离环境，用 `--force-reinstall --no-deps` 安装最终 wheel；未修改源码环境 `.venv` 或 `.venv-rl`。所有验收均从项目外的 Windows 临时目录运行，解释器加 `-I`，实际导入位置为隔离环境 `Lib/site-packages/control_lab/__init__.py`。安装来源元数据中的归档哈希与下面的最终产物一致。

- 产物：`dist/ControlLab/runtime/control_lab-0.2.0-py3-none-any.whl`，**300,738 字节**。
- SHA256：`698c4d6909fc62f1a9703d8416c83c7d77cfc2d5933b3318104e28dc9468ac2e`。
- 验收记录：`logs/wheel-runtime-validation-final.json`，状态 `passed`；详细产物、训练及评价日志在 `logs/wheel-runtime-final-20261007_230504/`。

| wheel 资源 | 数量 | 解压字节数 |
| --- | ---: | ---: |
| 课程 JSON | 32 | 276,645 |
| 学生模板 | 28 | 14,270 |
| 教师参考答案 | 28 | 14,421 |
| 固定评价资源 | 1 | 12,709 |

以上资源均从已安装包加载，并逐字节与 wheel 内容核对；Python 模板和答案全部通过语法解析，没有缺失资源。L19、L20、L29 的课程内容版本均为 2。L20 使用该 wheel 生成的真实 50 步带噪声轨迹完成离线分析，并实际生成 HTML/CSV/JSON；独立目标阶跃验证误差 D 项为 −12 N、仅测量 D 项为 0 N。L29 对 1 步和 2 步观测延迟各推进 4 步，逐状态核对延迟来源；杆质量 ±10% 场景为 0.09/0.11 kg。

Gymnasium 与 Stable-Baselines3 环境检查均通过，仅有观测空间正负无穷边界提示。CPU PPO 实际训练 **256 步**并保存模型，随后启动全新解释器重载该模型，在固定 `practice` 协议完成 5 回合，控制器错误数为 0；平均 34.4 步，5 回合均因倾角越界结束。这证明训练、保存、加载及评价通路可运行，不是学会平衡的性能证据。

隔离环境 `pip check` 通过。运行版本为 Python 3.13.5、PyTorch 2.9.1+cpu、Stable-Baselines3 2.9.0、Gymnasium 1.2.0、NumPy 2.2.6；该环境未安装 Qt/pygame，导入课程、信号分析及基础环境模块不会加载 PyTorch。

## 安装器与覆盖升级

最终便携候选由 `scripts/build_windows.ps1` 生成；构建日志为 `logs/build-v020-final.log`。使用本机已有 Inno Setup 6.7.3 编译正式 0.2.0 安装器成功，耗时 60.891 秒。

| 产物 | 结果 |
| --- | --- |
| `dist/installer/ControlLab-Setup-0.2.0.exe` | 52,968,672 字节 |
| SHA256 | `c1850ab9c4fd36f470d330aaca89c0bd63d46d005c14f91499afa03e5a1e691c` |

升级验证使用先前真实的 `ControlLab-0.1.0-windows-x64.zip`，旧 CLI 确认返回 0.1.0，不将新二进制改名冒充旧版。旧压缩包 SHA256 为 `9c678c9f35ecfd2f2ae7f011970d6fd9ae06bb656584d5a58f3175a13f3eb519`。

预检 HKCU/HKLM 两种注册表视图均无同 AppId 安装。将真实旧 payload 编译为 0.1.0 测试安装器后，安装到 `logs/installer-test-v020/app`，旧版 `doctor` 通过，并用旧 CLI 创建临时学生工作区。旧阶段证据：`logs/installer-test-v020/old-install-evidence.json`。

实际覆盖升级与清理结果均通过：

1. 运行 0.2.0 安装器时不传 `/DIR`，固定 AppId 自动复用旧安装位置；注册表版本变为 0.2.0。
2. 安装完成后的 `installation.json` 为 `installed_successfully`、版本 0.2.0。
3. 从安装目录运行 `doctor`，Python 与四项依赖全部来自安装目录的 `_internal`，物理 reset/step 通过。
4. 冻结 CLI 读取 32 课资源；安装后的 GUI 启动真实学生代码子进程，返回并应用 1.25 N、推进物理状态，退出码为 0。截图 `logs/installer-test-v020/installed-gui-code.png` 已检查。
5. 升级保留旧学生代码；卸载测试安装后，AppId 注册项和应用 exe 均已移除。临时学习目录中 7 个代码、进度与实验记录文件的逐文件 SHA256 全部不变。

最终机器记录为 `logs/installer-test-v020/report.json`，状态 `passed`；编译、安装、卸载和程序 stdout/stderr 均保存在同一目录。本次只卸载了预检后创建的隔离测试安装，没有删除用户文档目录。测试使用非交互安装参数验证文件与注册表行为，未替代人工向导操作验收。

## 冻结 GUI 的真实操作与进程生命周期

追加验证直接运行已构建的 `dist/ControlLab/ControlLab.exe`，SHA256 为 `47ac4d375f26cfbd171ad41f899ed8beb1a583dd435eae56aa71bc638880ba93`。使用 Windows UI Automation 的 InvokePattern/ValuePattern 操作原有按钮和输入框，没有修改产品源码、增加测试入口或直接调用窗口内部方法。每次使用独立的临时学习目录。

### L19：同模块的新回合与 reset

通过现有代码编辑器输入可记录 PID/回调次数的学生函数，实际点击运行、暂停、“新回合 · 保留代码”和单步。等待软件保存真实的回合重置确认事件后再单步，避免将自动化调用返回误当作 UI 处理完成。

| 学生程序 | 实际结果 |
| --- | --- |
| 无 `reset()` | 模块仅载入一次、worker PID 不变；第一回合从计数 1 开始，暂停时为 10，新回合首动作计数为 11 |
| 有 `reset()` | 模块仅载入一次、worker PID 不变；启动与新回合合计调用 reset 两次，两次相同初态的首动作计数均为 1 |
| 第二次 `reset()` 抛出异常 | GUI 显示具体错误，运行按钮恢复、同模块新回合按钮停用，没有继续调用 control 或悄悄推进新回合 |

三条路径关闭窗口后均未遗留学生 worker。证据为 `logs/frozen-native-qa/lifecycle-final/lifecycle-result.json`，各目录另存真实回调 JSONL、学生代码快照、进度与实验报告。首轮脚本因未等待异步 UI 重置确认而失败，其记录保留，但不作为产品缺陷或通过证据。

### 冻结 GUI → 独立 wheel 运行时 → 策略重载与回放

在原有 L27 页面输入已验证的非 editable `logs/wheel-runtime-test/Scripts/python.exe` 和先前 256 步烟测模型目录，实际点击“检查环境”“独立验证 · 20 回合”“回放验证用例”。进程检查确认三次操作使用三个不同 PID，执行路径均为指定外部 Python，命令均为 `-m control_lab.rl.service` 的对应子命令。

- 环境检查从实际 GUI 日志返回 Python 3.13.5、PyTorch 2.9.1+cpu、SB3 2.9.0 与正确外部解释器路径。
- 模型重新载入后完成 20 个固定验证用例，无控制器错误；平均 37.95 步、最差 28 步、完整回合 0/20。这是短训模型的通路验收，不是稳定平衡证据。
- 独立回放进程实际推进 `validation-100` 至第 34 步、因角度越界结束；GUI 收到状态并打开策略回放窗口，截图已检查。
- 关闭 GUI 后三个外部任务均已结束，没有遗留训练/推理进程。

证据为 `logs/frozen-native-qa/rl-final-v2/result.json`、真实 GUI 日志、20 回合报告与 `replay-window.png`。首轮脚本只在自动化树顶层寻找有父窗口的 Qt 对话框，导致选择器超时；改为后代选择器后通过，没有改动产品包。以上均未运行保留测试集。

## GitHub 云端构建与草稿资产核对

GitHub 恢复后，`main` 与 `v0.2.0` 指向 `773509117c9685175e1731f0e437a9db9461fbd3`。[Actions 运行 37647006563](https://github.com/Herd1s/Control_study/actions/runs/37647006563) 于 2026-10-07 15:52:15 UTC 完成，Windows job 和全部执行步骤成功。云端日志显示 **166 passed、2 skipped、34 subtests passed**；CI 基础环境未安装可选 RL 运行时，这两项跳过不能替代前文的独立 RL 验证。云端还运行了冻结 CLI doctor、32 课资源检查和固定 validation 用例评估。

[Release API 记录 405924361](https://api.github.com/repos/Herd1s/Control_study/releases/405924361) 确认 `tag_name=v0.2.0`、`draft=true`、`published_at=null`，三份资产均为 `uploaded`。本次没有发布草稿。下载同一次 CI 的 artifact `11494419268` 后，在本地逐字节计算 SHA256；内部 `SHA256SUMS` 与实际文件、Release API 的 digest 三方一致：

| 云端资产 | 字节数 | SHA256 |
| --- | ---: | --- |
| ControlLab-Portable-0.2.0-windows-x64.zip | 83,171,581 | `edd942eb58c0077ddc3fe454122b2031076f7ee35b2166cc6e60fe13bddca7d9` |
| ControlLab-Setup-0.2.0.exe | 53,021,491 | `c5863435eb46b21b2a9b8077aab46ce7329bf3b8aba033c283572d20050a8cf6` |
| SHA256SUMS | 203 | `6ea5ff35e91ef773c41b41dc16086b3fb50910ce311f89309a693b10e8840888` |

CI artifact ZIP 的 SHA256 为 `8b1903b90aec7cefa9e9dc59d2fd21879ee7c28c4686fab1047c6eaaecc7e4c5`，与 GitHub artifact digest 一致。本地证据：`logs/github-ci-validation/verification.json`。云端重新构建的文件与前文开发机安装验收文件哈希不同，因此另做了下面的独立安装验收。草稿下载入口仍不公开，普通客户端不会发现它；未演练公开 Release 至安装完成的更新链。

### CI 安装器字节的独立安装与去除开发环境路径验收

从已校验 artifact 直接取出 SHA256 为 `c5863435…a8cf6` 的真实 CI 安装器，再次检查 HKCU/HKLM 的 32/64 位 AppID 注册均不存在，才安装到 `logs/github-ci-validation/installed-test/app`。安装退出成功，同一 AppID 注册指向该隔离目录，`installation.json` 正确记录 0.2.0 安装完成。

启动冻结 CLI/GUI 的子进程前，清除 Python、虚拟环境、Conda、Qt 和 Isaac 相关环境变量，并将 PATH 限制为 `C:\WINDOWS\System32;C:\WINDOWS`；工作目录是独立空目录。没有重命名、删除或卸载开发机的 Python。

- 安装目录内 CLI 的 doctor、32 课资源读取、20 个固定 validation 用例实际运行成功；所有 desktop 依赖从该安装目录 `_internal` 加载。
- 使用 Windows UI Automation 操作原有 GUI 编辑器和“运行代码”按钮，输入可记录进程信息的学生函数；真实 worker 执行了 34 次控制调用。
- worker 的 `sys.executable` 与进程命令行指向安装目录 `ControlLab.exe --multiprocessing-fork`；实际加载的 `python313.dll`、`python3.DLL` 均来自安装目录 `_internal`。
- worker 的 `sys.path` 全部位于安装目录，`control_lab`、NumPy、Gymnasium 的模块路径均指向安装副本，没有开发源码或外部 Python 路径。冻结运行时只向最小 PATH 补入本安装包的依赖目录。
- 正常关闭 GUI 后 worker 已结束；再次核对注册目录后，只卸载本次隔离副本，AppID 注册与应用 EXE 均已清理，学习记录保留。

证据与完整日志位于 `logs/github-ci-validation/installed-test/report.json`、`native-worker-result.json`、`worker-environment.json`。这一结果验证了 CI 安装副本不依赖开发 Python 的可执行文件、模块搜索路径或 DLL；仍不替代一台全新 Windows 机器的系统组件兼容性验收。

这份验证对应已提交的 0.2.0；当前尚未提交、待完整验收与重新打包的教学功能补全不包含在该草稿中。

## 尚未验证的边界

当前开发机的冻结运行和隔离目录安装，不等于无 Python 的干净 Windows 机器验收。真实 GitHub Release 下载至安装完成的更新链、安装被中断后的恢复和 Windows 代码签名均需单独验证或配置。GitHub Actions 云端构建已按上文实际通过。源码测试中的更新下载异常、取消和坏哈希拒绝属于可重复的本地模拟测试。

短 PPO 训练与模型保存成功不等于稳定平衡；应查看独立验证报告及不同训练种子的差异。本轮未用保留测试集调参，未进行 TITA 实机控制。
