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

## 尚未验证的边界

当前开发机的冻结运行和隔离目录安装，不等于无 Python 的干净 Windows 机器验收。真实 GitHub Release 下载至安装完成的更新链、GitHub Actions 云端执行、安装被中断后的恢复和 Windows 代码签名均需单独验证或配置。源码测试中的更新下载异常、取消和坏哈希拒绝属于可重复的本地模拟测试。

短 PPO 训练与模型保存成功不等于稳定平衡；应查看独立验证报告及不同训练种子的差异。本轮未用保留测试集调参，未进行 TITA 实机控制。
