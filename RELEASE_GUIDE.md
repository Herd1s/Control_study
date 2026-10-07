# ControlLab Windows 发布指南

当前代码版本为 0.2.1，唯一版本来源是 `src/control_lab/__init__.py` 的 `__version__`；wheel、安装器与 CI 从这里读取。默认更新仓库为 [Herd1s/Control_study](https://github.com/Herd1s/Control_study)。修改源码、添加远程仓库和本地构建都不会发布版本。

当前本地证据见 [0.2.1 验证记录](docs/VALIDATION_0.2.1.md)；已完成的上一版安装和 CI 证据见 [0.2.0 验证记录](docs/VALIDATION_0.2.0.md)；未完成的分发验收明确列出，不能由源码测试通过推断。

2026-10-07 已在当前开发机完成真实 0.1.0 payload 安装、0.2.0 覆盖升级、安装后 GUI/CLI 验证、卸载及学生文件保留检查，安装器已实际生成。干净 Windows 机器和真实远端 Release 更新链仍待验收。

## 本地构建

使用 Windows x64、Python 3.11–3.13（当前验证使用 3.13）和已有的 Inno Setup 6。基础开发环境包含 desktop、dev、packaging extras；训练依赖单独安装。

```powershell
.\setup.ps1 -Python 'C:\Python313\python.exe'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\scripts\build_windows.ps1 -Installer -Iscc 'C:\路径\Inno Setup 6\ISCC.exe'
```

不需要安装器时省略 `-Installer`。构建脚本打包 GUI 和 CLI、收集依赖许可证、生成核心 wheel，将 `setup-rl.ps1`、依赖锁和 wheel 放到发行目录的 `runtime` 中。Inno 编译器通过 `/DMyAppVersion` 接收真实版本；直接编译 `.iss` 时不提供版本会报错。

| 产物 | 用途 |
| --- | --- |
| `dist\ControlLab\ControlLab.exe` | 桌面课堂入口 |
| `dist\ControlLab\ControlLabCLI.exe` | 命令行入口，与 GUI 共用 `_internal` |
| `dist\ControlLab\runtime` | 学生独立 CPU 训练环境的安装材料 |
| `dist\installer\ControlLab-Setup-0.2.1.exe` | 按用户安装与覆盖升级 |

便携包必须包含整个 `dist\ControlLab`，而非两个 exe。基础安装包不包含 PyTorch 或 Isaac Sim。`runtime\setup-rl.ps1` 首次运行需要现成的 Python 和网络，训练环境存入系统文档目录，不随安装目录被替换。

## 发布前验证

```powershell
.\dist\ControlLab\ControlLabCLI.exe doctor
.\dist\ControlLab\ControlLabCLI.exe lesson --list
.\dist\ControlLab\ControlLabCLI.exe evaluate --controller reference --split validation --output-dir logs\release-validation-01
```

另外应在工程外目录打开 GUI，验证学生短函数子进程、保存作业、课程资源、评估停止及模型训练入口。使用全新的输出目录，保留报告和构建日志。验证集固定 20 例；发布检查不使用保留集调参。

安装器能成功编译只证明产生了文件。实际分发前还需在干净 Windows 用户环境检查首次安装、从上一版覆盖升级、取消安装和卸载，确认学习目录保留；独立训练脚本需验证可由随包 wheel 建立环境。源码测试、当前开发机上的冻结运行和这些安装验收应分别记录。未运行 GitHub Actions 时，不能声明云端 CI 已通过；短 PPO 运行也不能作为稳定平衡成绩。

安装器使用固定 AppId 与每用户目录 `%LOCALAPPDATA%\Programs\ControlLab`，无需管理员权限；不要在升级时更改 AppId，不要把学习数据放进安装目录。向导完成后可勾选打开软件，未承诺自动重启。`installation.json` 记录向导完成，不把启动安装进程视为升级成功。当前没有应用层自动回滚机制；分发前的覆盖升级验证不能省略。

## GitHub 构建与发布

[release.yml](.github/workflows/release.yml) 只接受手动触发或 `v*` 标签推送。普通分支提交不构建发布版。工作流使用已有 Inno 编译器，依次运行测试、构建、冻结 CLI 验证，再生成：

- `ControlLab-Setup-0.2.1.exe`
- `ControlLab-Portable-0.2.1-windows-x64.zip`
- `SHA256SUMS`（每行 `sha256值  文件名`，UTF-8 无 BOM）

手动触发且 `create_draft=false` 时只上传 Actions 产物。标签触发或显式请求 `create_draft=true` 时创建 **草稿 Release**，仍需维护者验收后发布；标签必须与源码版本一致，例如 `v0.2.1`。手动创建草稿还要求填入已存在的 `release_tag`，且所选提交必须与该标签一致。工作流不会代建标签。

此工作流只安装基础桌面开发环境；需要独立 RL 解释器的测试会在缺少该环境时跳过。CI 基础测试通过不能替代独立 CPU 训练、模型保存与重载验收。

仓库已连接，v0.2.0 已实际完成 GitHub Actions 构建与草稿产物核验；新版本仍需单独触发工作流并检查结果。本地生成文件不代表 GitHub 上已有对应版本。先下载产物完成验收，再决定是否公开草稿。不要覆盖已发布版本的文件或用同一标签发布不同构建，应递增版本。

## 应用内更新契约

客户端读取配置仓库的最新公开正式 Release，忽略草稿与预发布版本。安装器名必须为 `ControlLab-Setup-X.Y.Z.exe`，标签为 `vX.Y.Z` 或 `X.Y.Z`。校验采用 GitHub asset 的 SHA256 digest，或同一个 Release 的 `SHA256SUMS`；缺少可验证哈希时不会下载执行。

更新页打开时不联网，用户分别执行检查、下载与安装。网络超时和取消不会替换已安装程序或学习文件；下载先写独立临时目录，大小与哈希正确后才可安装，交给向导前再次校验。用户自定义仓库保存在学习数据目录，优先于默认值。尚无正式 Release 时显示明确提示。

客户端不读取或保存 GitHub token。CI 的 `GITHUB_TOKEN` 仅用于工作流创建草稿。HTTPS 和 SHA256 提供传输与文件一致性检查，不等于发布者身份签名；当前构建流程未配置 Windows 代码签名，不应声称已签名发行。
