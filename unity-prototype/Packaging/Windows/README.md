# Unity Windows 安装与发布

此目录只维护 Unity 产品。旧 Python 安装包、`v0.x.x` 标签和全仓库 `releases/latest` 不作为 Unity 更新来源。

当前正式版本：[Unity 0.2.0 Release](https://github.com/Herd1s/Control_study/releases/tag/unity-v0.2.0)，可直接下载 [Windows 安装器](https://github.com/Herd1s/Control_study/releases/download/unity-v0.2.0/ControlLab-Unity-Setup-0.2.0.exe) 或 [完整便携 ZIP](https://github.com/Herd1s/Control_study/releases/download/unity-v0.2.0/ControlLab-Unity-Portable-0.2.0-windows-x64.zip)。以下流程用于维护后续版本。

0.2.0 是首个 Unity 正式发行版。历史 Unity 0.1.0 原型没有内置本次更新器，需手动安装 0.2.0；0.2.0 及后续版本才可使用应用内更新。旧 Python/Qt 版也不能通过旧更新器直接迁入 Unity。公开发布完成与线上升级验收分别记录，当前证据见 [验证记录](../../VALIDATION.md)。

## 生成发布候选

在 Unity 工程根目录运行：

```powershell
.\Build-Installer.ps1
```

先关闭正在运行的 `Builds/Windows` 软件，避免文件占用影响便携包生成。脚本先构建 Player，再使用本机 Inno Setup 6 编译安装器。已经构建并通过验证时，可使用 `-SkipPlayerBuild`。编译器不在默认安装位置时，传入 `-Iscc 'C:\完整路径\ISCC.exe'`。

版本只从 `Assets/ControlLab/Scripts/AppVersion.cs` 的 `Current` 常量读取。打包前要求 `Builds/Windows/build-info.json` 的产品、版本、平台与当前源码一致，并重新核对实际 `Assembly-CSharp.dll` 的 SHA256，避免把旧 Player 标成新版本。

输出位于 `Builds/Releases/X.Y.Z`：

- `ControlLab-Unity-Setup-X.Y.Z.exe`：每用户安装器。
- `ControlLab-Unity-Portable-X.Y.Z-windows-x64.zip`：完整便携软件。
- `unity-update.json`：Unity 更新器使用的发布清单。
- `SHA256SUMS`：交付核对清单。

## 本地安装与覆盖升级

默认安装到 `%LOCALAPPDATA%\Programs\ControlLabUnity`，使用独立于旧 Python 软件的固定 AppId。学习资料继续保存在 `%USERPROFILE%\AppData\LocalLow\ControlLab\ControlLab Unity`，不放入安装目录；卸载仅清理程序文件。

验收应使用专用目录，例如 `installer.exe /DIR="C:\Users\用户名\AppData\Local\Programs\ControlLabUnity-QA" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG="C:\测试日志\install.log"`，然后以 `--profile-directory` 启动软件隔离测试资料。不要用真实学生照片或覆盖日常资料验证。

`/DIR` 仅隔离程序文件，仍会注册同一个 Windows 卸载项并记住安装目录。验收前检查该产品是否已经安装；原先没有安装时，验收结束用 QA 目录内的卸载程序清理登记，避免下次正式安装沿用 QA 目录。

应用内安装在保存资料成功后，使用 `/WAITFORPID=<当前Player进程号> /RESTARTAPP=1` 交给安装器，然后退出。安装器最多等待 45 秒；原进程未退出则在替换文件前停止。安装结束写入安装目录中的 `installation.json` 并重新打开软件。

若原 Player 已显式使用 `--profile-directory`，交接只转发该绝对目录为 `/PROFILEDIR="路径"`，新版使用同一隔离资料。没有此参数的普通启动仍使用默认用户目录；不允许发布清单指定重启程序或任意重启参数。

安装器启动只代表已交接。新版启动后，更新服务还会核对当前版本、`pending-update.json` 和 `installation.json`，成功才记录 `last-update.json`。手动安装未必存在更新服务的 pending 记录，不会制造“应用内更新成功”的记录。

## GitHub 发布契约

发布目标固定为 `Herd1s/Control_study`，Unity 标签格式为 **`unity-vX.Y.Z`**。同一个 Release 必须包含安装器和 `unity-update.json`；清单的 `schema=1`、`productId=controllab-unity`、`platform=windows-x64`、版本、文件名、字节数及 SHA256 必须匹配实际资产。

客户端分页读取公开 Release，忽略草稿、预发布和旧 Python 标签。不会要求学生登录 GitHub 或输入 token，也不会在打开设置时自动联网。检查、下载、安装分别由用户点击。

完成本地源码、Player 交互和安装/覆盖安装验证后，维护者才能上传同一份候选文件并发布 Release。不要复用已发布版本号，也不要以同一标签替换不同二进制。本地构建脚本不会创建远端标签、上传文件或发布版本。

当公开发布列表没有符合要求的 Unity 正式版本时，软件显示“尚无 Unity 正式安装包”；这是 `NoRelease` 分支，曾在 0.2.0 发布前实际验证。当前 0.2.0 已发布。404、网络超时、请求限流、清单不匹配和校验失败各有独立提示；这些状态不能当作“已经最新”。

本轮未配置 Windows 发布者数字签名。HTTPS 与 SHA256 验证来源传输和文件一致性，不等同 Windows 代码签名。

## 可重复验证

```powershell
.\Tools\Check-Updates.ps1
.\Tools\Check-Updates.ps1 -Live
```

第一条在 .NET 下运行实际客户端、服务和传输实现的离线契约检查，安装器进程用捕获器替代，绝不执行测试载荷。第二条额外通过未认证公开 API 进行真实 GitHub 检查，并单独记录结果；网络失败不冒充离线功能失败或真实网络成功。两者均不上传、下载真实安装包或发布版本。

来源：[GitHub Releases API](https://docs.github.com/en/rest/releases/releases)、[Release assets API](https://docs.github.com/en/rest/releases/assets)、[Inno Setup 脚本事件](https://jrsoftware.org/ishelp/topic_scriptevents.htm)。
