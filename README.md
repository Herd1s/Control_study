# ControlLab · Unity 教学实验室

当前工作区仅维护 Unity 版：从小车装扮与手动倒立摆体验，逐步扩展到控制算法和强化学习教学。

- **下载安装（Windows）**：[ControlLab Unity 0.2.0 安装包](https://github.com/Herd1s/Control_study/releases/download/unity-v0.2.0/ControlLab-Unity-Setup-0.2.0.exe)
- **正式版本与便携包**：[unity-v0.2.0 Release](https://github.com/Herd1s/Control_study/releases/tag/unity-v0.2.0)
- **本地构建后运行**：[Start-Prototype.cmd](unity-prototype/Start-Prototype.cmd)
- **打开 Unity 工程**：[Open-Unity.cmd](unity-prototype/Open-Unity.cmd)
- **使用与开发说明**：[Unity README](unity-prototype/README.md)
- **安装包与 GitHub 发布**：[Windows 安装与发布](unity-prototype/Packaging/Windows/README.md)
- **设置界面原始交互草案**：[settings-design.html](unity-prototype/Documentation/settings-design.html)
- **实际验证记录**：[VALIDATION.md](unity-prototype/VALIDATION.md)

用 VS Code 打开 `ControlLab.code-workspace`，或直接打开 `unity-prototype` 文件夹。Unity 工程使用 6000.5.7f1，启动与构建不依赖原 Python/Qt 工程；交互验证脚本只需系统 Python 标准库。

当前 Unity **0.2.0** 已实现装扮、第一章和三类设置：学习进度、我的小车、软件更新，另设“关于”。继续学习开关与课程记录独立保存，关闭开关仍保留原记录；课程中修改名字、颜色、照片和涂鸦后，可直接返回原讲解与原实验。软件可手动检查、下载并交给安装器更新，来源固定为本仓库的 `unity-vX.Y.Z` 正式 Release。

**0.2.0 是首个 Unity 正式发行版。** 之前的 Unity 0.1.0 原型没有内置本次更新器，需要手动下载安装 0.2.0；安装后，后续新版可通过“设置 → 软件更新”获取。旧 Python/Qt 版也需要首次手动安装 Unity，旧版课程代码和学习记录不会自动迁入。

运行 `unity-prototype/Build-Installer.ps1` 可生成安装器、便携 ZIP 与更新清单，需要 Unity 和 Inno Setup 6；学生运行软件不需要这些开发工具。程序文件与本机学习资料分开保存。构建脚本不会自动发布，完整运行、维护与发布步骤见上方文档。

原 Python/Qt 工程和本地旧发布产物已退役。Git 历史保留；原学员资料位于工程目录外，不属于工程清理范围。学生 Python 编程、PID、强化学习和 TITA 课程尚未在当前 Unity 版实现。

源码与 Unity 0.2.0 安装包已正式发布；在线升级验证的当前范围与结果见 [验证记录](unity-prototype/VALIDATION.md)。
