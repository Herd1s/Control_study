# ControlLab 0.2.0 本地验证记录

日期：2026-10-07。环境：当前 Windows x64 开发机、Python 3.13.5；桌面 `.venv` 与 CPU 训练 `.venv-rl` 分开。本文按证据区分源码、冻结程序、安装及远端发布。当前实现范围和教学限制见 [实现审计](IMPLEMENTATION_AUDIT.md)。

## 源码与独立训练环境

- 最终桌面源码测试：**168 项通过，34 个子测试通过**，105.75 秒；5 条 Gymnasium 环境检查提示。日志：`logs/pytest-v020-final.log`。
- 独立 RL 合约测试：**11 项通过**，2.77 秒；2 条 Gymnasium 提示。日志：`logs/pytest-v020-rl.log`。这些提示涉及未限定观测边界和原始牛顿动作空间；训练适配器另有归一化动作契约。
- 桌面环境 `pip check` 通过；`requirements-lock.txt` 已按当前环境导出，训练依赖单独锁定。
- 更早的 0.2.0 候选 wheel 在新的独立环境安装、从工程外目录加载成功，没有拉入 Qt/pygame，课程资源齐全；见 `logs/wheel-runtime-validation.json`。此记录含当次 wheel 哈希，不能自动代表后续重建产物。

## 安装器与覆盖升级

最终候选正在构建，最终结果将补在本节，不能提前视为通过。

升级验证使用先前真实的 `ControlLab-0.1.0-windows-x64.zip`，旧 CLI 确认返回 0.1.0，不将新二进制改名冒充旧版。旧压缩包 SHA256 为 `9c678c9f35ecfd2f2ae7f011970d6fd9ae06bb656584d5a58f3175a13f3eb519`。

预检 HKCU/HKLM 两种注册表视图均无同 AppId 安装。将真实旧 payload 编译为 0.1.0 测试安装器后，安装到 `logs/installer-test-v020/app`，旧版 `doctor` 通过，并用旧 CLI 创建临时学生工作区。旧阶段证据：`logs/installer-test-v020/old-install-evidence.json`；测试完成后将卸载本次测试安装，保留验收日志与临时学生文件。

## 尚未验证的边界

当前开发机的冻结运行和隔离目录安装，不等于无 Python 的干净 Windows 机器验收。真实 GitHub Release 下载至安装完成的更新链、GitHub Actions 云端执行、安装被中断后的恢复和 Windows 代码签名均需单独验证或配置。源码测试中的更新下载异常、取消和坏哈希拒绝属于可重复的本地模拟测试。

短 PPO 训练与模型保存成功不等于稳定平衡；应查看独立验证报告及不同训练种子的差异。本轮未用保留测试集调参，未进行 TITA 实机控制。
