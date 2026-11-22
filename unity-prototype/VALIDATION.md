# ControlLab Unity 验证记录

记录日期：2026-11-22。当前 0.2.0 接入学习、我的小车、软件更新三页和“关于”，开关偏好与课程记录独立保存，支持课程中换肤返回及 GitHub 更新交接。以下先记录本次功能的检查方法与证据入口，再保留此前 212 项完整检查和工程清理后的 69 项定向回归；历史数量不代表本次版本已经重新执行对应检查。

## 0.2.0 设置与更新的验证范围

| 功能 | 本次需要核对的行为 |
| --- | --- |
| 设置布局与输入 | 800×600、1366×768 下三页与关于完整可操作；切换不需要滚动，遮罩阻挡背景输入，打开设置暂停实验，关闭后继续 |
| 偏好迁移 | 首次从旧 `learning-progress.json` 读取开关并创建独立 `app-preferences.json`；已有新偏好优先；损坏时使用有效备份并保留坏文件 |
| 保留课程 | 关闭再开启继续学习开关不修改课程位置；关闭后从首页退出不覆盖原第一章记录；重新开启并重启恢复原讲解 |
| 课程中换肤 | 编辑名字、车色、照片、涂鸦后直接回到原讲解；不进入 `Arriving`，小车位置、速度、杆角度与实验时间保持；编辑中正常退出也保存草稿并保留课程位置 |
| 重启语义 | 恢复学习页面及讲解，从竖直静止开始新的可操作实验；它与同次运行中换肤后保留原实验的行为分开验证 |
| GitHub 检查 | 打开设置不联网；点击检查后实际调用公开 API；无正式 Unity Release、已最新、发现新版本与网络/清单错误分别处理 |
| 下载与安装 | 下载可取消；大小、SHA256 和清单匹配后才允许安装；资料保存成功后退出，安装器等待旧进程关闭再替换程序并重新打开 |
| 安装包与资料 | `AppVersion.Current`、构建标记、程序集、安装器和更新清单一致；安装目录独立于资料目录；覆盖安装不删除学习位置和小车外观 |

`check_settings_windows.py` 使用 Windows 真实鼠标、Unicode 键盘、原生文件选择器和正常关闭消息，依次启动五个隔离 Player 会话。它使用真实旧格式资料作为迁移输入，通过只读遥测观察状态，不调用内部控制器修改课程或物理状态。照片使用工具生成的测试图片。

偏好存储检查在 .NET 下链接实际存储源码，用 `JsonUtility` 测试适配器核对文件迁移、开关变化、备份和写入失败；实际 Unity 序列化由 Player 的迁移、退出和重启检查补充。更新契约检查执行实际客户端与传输代码，安装器执行由捕获器代替；这些测试不会执行测试下载载荷，不能替代真正安装器验收。

真实 GitHub 检查单独记录，不将超时、限流、404 或校验失败计为成功。当前服务器没有符合要求的 Unity 正式发布时，预期状态为 `NoRelease`；“尚无 Unity 正式安装包”是正常查询结果。仓库将来发布 Unity 版本后，应按实际版本调整预期状态。

本次已通过 237 项 Windows 实际交互检查：新设置 44×2 项、退出恢复 42×2 项、800×600 装扮回归 37 项、1366×768 第一章回归 28 项。各会话均正常退出，运行日志无异常。另有 35 项偏好存储、46 项更新器契约检查通过；实际 Unity 界面与独立客户端均成功查询 GitHub，结果为 `NoRelease`。

16 个运行时文件、3 个 Editor 文件通过源码检查，零错误、零告警；最终 Player 构建日志是 `Logs/build-20261122-214002.log`。独立 .NET 物理重放通过 19 组、3848 次操作，最大绝对误差为 0；物理模型未改，Unity Editor 数值验证未重复执行。Windows PowerShell 5.1 实际生成安装器与完整便携 ZIP，清单、文件 SHA256 和 ZIP 内程序集均核对一致。当前汇总见 [verification-summary.json](Documentation/verification-summary.json)。

以下是本轮证据入口：

实际安装与覆盖升级的 22 项检查全部通过：在独立目录安装 0.1.0，启动旧 Player 后运行 0.2.0 安装器，确认旧进程存活时不替换文件；正常退出后替换真实程序集、登记新版并自动打开新进程。含中文和空格的隔离资料目录被正确传递，学习进度、偏好、照片和绘画保存内容逐字节一致，新版“关于”显示 0.2.0，实验可操作。最后原生卸载清除了测试程序及注册项，保留测试资料，日常用户资料未变化。首轮清理断言曾早于 Inno 自删除完成；修正检查工具等待后置条件后，完整重跑通过，产品代码未因此修改。

尚无公开 Unity Release，本次没有推送、打标签或发布。真实 GitHub 查询已验证，下载与校验错误路径通过契约测试，安装器等待、覆盖及重启通过真实安装验证；从 GitHub 下载正式安装包再完成升级的整条在线流程仍需正式发布后验证。

| 证据 | 文件 |
| --- | --- |
| 800×600 新设置、迁移与换肤 | [settings-800x600/result.json](Logs/Verification/settings-800x600/result.json) |
| 1366×768 新设置、迁移与换肤及可选真实 GitHub 检查 | [settings-1366x768/result.json](Logs/Verification/settings-1366x768/result.json) |
| 独立偏好与课程记录检查 | [preferences-check/result.json](Logs/Verification/preferences-check/result.json) |
| GitHub 更新器契约及可选网络检查 | `Logs/Verification/update-check/` |
| 安装包、清单与便携包一致性 | [installer-package.json](Logs/Verification/installer-package.json) |
| 真实安装、覆盖、重启与卸载的 22 项检查 | [installer/result.json](Logs/Verification/installer-20261122T134833709532Z/result.json) |
| 安装器构建与验收方法 | [Windows 安装与发布](Packaging/Windows/README.md) |

本次修改不改变倒立摆动力学。后续学生 Python 编程、PID、强化学习和 TITA 尚未实现，本页结果不覆盖这些课程。

## 历史：已保留的完整功能验证

以下结果来自新设置接入之前的 Unity 6000.5.7f1、本机 Windows 环境。以下各节的“本轮”指该历史验证批次。源码检查、Editor 数值验证和独立 Player 交互测试分别记录，不能相互替代。

| 项目 | 本轮结果 |
| --- | --- |
| C# 源码类型检查 | 11 个运行时文件、3 个 Editor 文件；使用 Unity 自带 Roslyn 和参考程序集，零错误、零告警 |
| Unity 实际导入与构建 | 完整功能验证所用构建日志 `Logs/build-20261122-205419.log` 包含 `CONTROLLAB_BUILD_OK` 和成功退出记录；未见项目 C#、USS 或 shader 编译错误、告警 |
| Windows 发布目录 | `Builds/Windows/ControlLab Unity.exe` 与 `_Data`、Mono 运行库等完整输出已生成；实际测试运行独立 Player |
| Unity Editor 物理数值比对 | 沿用上一轮报告：19 组、3848 次操作；30784 个浮点字段和 19240 个生命周期字段检查通过；本轮模型未改，未重跑数值验证 |
| 数值误差 | 既有 Unity 6000.5.7f1 报告的最大绝对误差为 `1.865174681370263e-14`，低于容差 `1e-10` |
| 独立物理行为 | 沿用既有 7 组检查：初始竖直静止、显式 Euler、松手惯性、拒绝 NaN、1 N 持续 5 步、倒下与原位扶正、回合时限 |
| 800×600 设置与退出恢复 | 41 项检查全部通过；8 个 Player session 正常退出，无运行异常或强制终止 |
| 1366×768 设置与退出恢复 | 41 项检查全部通过；8 个 Player session 正常退出，无运行异常或强制终止 |
| 1366×768 装扮页 | 37 项检查全部通过；首次运行、重启两个 session 均退出 0，运行异常列表为空 |
| 800×600 装扮页 | 37 项检查全部通过；首次运行、重启两个 session 均退出 0，运行异常列表为空 |
| 1366×768 第一章回归 | 28 项检查全部通过；Player 退出码 0，`runtimeErrorLines` 为空 |
| 800×600 第一章回归 | 28 项检查全部通过；Player 退出码 0，`runtimeErrorLines` 为空 |
| 独立存储逻辑检查 | .NET 适配器下 28 项通过；与 Unity Player 的实际序列化验证分开统计 |
| 本轮交互总计 | 82 项设置与退出恢复 + 74 项装扮流程 + 56 项第一章回归，共 212 项通过 |
| 中文与材质 | 两种分辨率均识别到 `Microsoft YaHei UI`、主题与样式；第一章 22 个渲染对象的材质均使用受支持的 shader，截图中文字、按钮和场景正常显示 |

既有物理逐操作重放由 **Unity Editor 中的 `PhysicsVerification.Run`** 执行，使用退役前 Python `TeachingSimulation` 实际生成的参考数据。旧源码和环境清理后，冻结参考及其来源信息仍保留在 `Tools/PhysicsCheck/Fixtures`；重放不再调用 Python 模型。这不是独立 Player 中逐步重放全部数值的报告。独立 Player 的证据是下述真实窗口、鼠标输入、模型状态与运行日志检查。此前独立 .NET 9 验证的最大误差为 0，既有 Unity 运行时结果以 `physics-verification-unity.json` 为准。

本轮新增设置、退出进度与装扮草稿保存，未改倒立摆物理模型。`PendulumModel.cs` 的 SHA256 与既有 Unity 数值报告一致：`777dc0d730760352afdd531fe2ee839c922e08bb0acf35b29b2cc98e9bf21b77`。该报告生成于 `2026-11-22T10:24:26.8182105Z`，本轮核对哈希后沿用，没有重新执行 19 组数值重放。

## 历史：独立工程清理与验证范围

旧版 Python/Qt 应用工程和其开发环境已退役，Unity 保持独立目录结构。原先位于父工程 `logs/unity-prototype` 的证据迁入本工程 `Logs/Verification`。报告内部的旧绝对路径保留为生成时记录，文档导航使用迁移后的路径。

该次目录迁移后重新构建，并完成 69 项定向 UI 回归；没有重新执行全部 212 项完整功能检查。定向重跑的对应报告保留当时结果；如果同名报告后续被重跑覆盖，以报告时间为准。该批次发生在三分类设置接入前，不计入 0.2.0 的设置与更新验收。

| 独立验证 | 实际结果 |
| --- | --- |
| 源码检查 | 从 Unity 工程目录运行，11 个运行时文件、3 个 Editor 文件检查通过；输出在本工程 `Logs/Verification/source-check` |
| 独立 Windows 构建 | `Logs/build-20261122-211120.log` 包含 `CONTROLLAB_BUILD_OK`，构建成功；不依赖旧版 Python/Qt 工程或虚拟环境 |
| 800×600 设置与退出恢复 | 使用系统 Python，在新验证目录执行 41 项检查全部通过；8 个 Player session 正常退出，无运行异常或强制终止 |
| 1366×768 第一章回归 | 使用系统 Python，在新验证目录执行 28 项检查全部通过；Player 退出 0，无运行异常 |
| 迁移后 UI 总计 | 41 项设置与恢复 + 28 项第一章操作，共 69 项定向回归通过 |
| 冻结参考完整性 | 系统 Python 3.14 与标准库读取工程内 fixture，SHA256 与随附 manifest 一致；19 组、3848 个操作 |
| .NET 数值重放 | `Tools/Verify-Physics.ps1` 在新目录下使用 .NET 9.0.14 重放实际 C# 模型；19 组、3848 操作、30784 数值字段、19240 生命周期字段及 7 项不变量全部通过，最大误差 0 |

这次 .NET 重放生成于 `2026-11-22T13:16:13.3244570Z`，模型哈希仍与既有报告一致。它重新验证了 C# 模型对冻结参考的一致性，没有重新运行已退役的 Python 模型，也没有重新执行 Unity Editor 数值重放。

## 历史：原设置与退出进度检查

该版本设置位于装扮页和第一章右上角。“记住上次进度”默认开启，开关变化立即保存。正常退出或失去焦点时保存未完成的名字、车色、照片和涂鸦；页面和讲解切换也会保存学习位置。当时 `cart-profile.json` 保存装扮，`learning-progress.json` 同时保存设置和学习位置。0.2.0 已将开关迁出到独立 `app-preferences.json`，当前行为见本页首节。

800×600 与 1366×768 分别完成 41 项真实输入检查，合计 82 项通过。每种尺寸使用新的隔离资料目录，并依次启动、正常关闭 8 个 Player session；16 次退出均为 0，无运行异常或强制终止。测试通过 Win32 鼠标、Unicode 键盘与主窗口关闭消息操作软件；不调用内部控制器修改状态。

| 检查范围 | 实际操作与预期结果 |
| --- | --- |
| 默认设置与布局 | 新资料从装扮页开始，记住进度默认开启；首页和第一章都有设置入口；设置弹窗、开关与完成按钮无需滚动 |
| 开关保存 | 关闭开关并退出，重启仍为关闭；从第一章退出也返回装扮首页；小车名字、车色与涂鸦保留 |
| 未完成装扮 | 未点击“完成，进入第一章”也可正常退出；下一次打开恢复名字、车色和真实鼠标绘制的笔迹；名字输入框仍有焦点时退出也保存 |
| 第一章恢复 | 重新开启记住进度，选择“重力与力矩”后退出；重启直接进入第一章，并恢复展开的讲解与所选主题 |
| 物理状态 | 在运行中的实验退出，重启恢复学习位置，小车和杆从中央竖直静止开始，不恢复旧的速度、角度或拖动状态 |
| 设置期间交互 | 打开设置后物理时间与位置冻结，关闭后继续当前实验；遮罩阻挡底部“轻推一下”，不误启动背景实验 |
| 入场中退出 | 装扮完成、小车自动驶入期间退出，下一次直接进入准备好的第一章，保留装扮 |
| 损坏文件 | 进度主文件损坏且没有备份时进入可用的默认首页；有有效备份时恢复备份中的第一章和讲解；后续保存保留损坏文件原始字节 |
| 退出质量 | 每次正常关闭都检查进程退出码、运行日志和清理记录，必须退出 0、没有运行异常、没有强制终止 |

恢复的是当前原型中的页面与讲解位置，不是倒立摆正在运动的瞬间。设置弹窗本身不跨重启恢复。已验证正常窗口退出；进程被强制结束或断电时，尚未触发保存的装扮修改不属于本轮保证范围。

`LearningProgressStore` 另有 28 项独立存储逻辑检查，覆盖默认值、设置往返、有效备份、坏文件保留、旧记录缺少可选开关字段、未知版本/页面、类型错误、重复键、越界主题、无效 UTF-8、过大 JSON、写入失败及临时文件清理。该检查使用 .NET 9 和 `JsonUtility` 测试适配器，不能代替 Unity 的实际序列化；上表的跨 Player 退出、重启和坏文件恢复通过真实 Unity Player 验证，两组数量不混加。

## 历史：装扮首页与自动入场检查

1366×768 和 800×600 分别执行 37 项检查，合计 74 项全部通过。每次测试使用独立的 `--profile-directory`，照片由测试工具生成 96×48 PNG，不使用学生资料或私人照片；同一次测试的重启步骤复用该隔离目录。

| 检查范围 | 实际验证内容 |
| --- | --- |
| 首页与布局（8 项） | 新资料打开静止装扮页；客户区尺寸正确；名字、预设车色、自选车色、画布、照片与完成按钮分别完整可见 |
| 名字与颜色（4 项） | 真实键盘编辑名字；预设色改变车身；自选颜色打开本 Player 所属的原生对话框；取消后保留原车色 |
| 涂鸦编辑（4 项） | 鼠标笔迹产生像素与撤销记录；撤销恢复画布；清空移除绘画；重新绘制留下可保存内容 |
| 照片与独立图层（6 项） | 取消选图不添加照片；真实文件对话框导入测试 PNG；移除照片不改涂鸦；橡皮只擦绘画；撤销恢复被擦内容；取消替换照片保留两层 |
| 输入隔离（1 项） | 装扮编辑不抓取小车，也不启动倒立摆物理 |
| 自动入场（5 项） | 完成后进入 `Arriving`；小车经过连续的中间位置驶入；途中物理不运行；结束到达中央 `Lesson`；第一章从竖直静止状态开始 |
| 完成保存（3 项） | 名字与颜色写入隔离资料；照片与涂鸦分别保存为 PNG 图层 |
| 重启恢复（6 项） | 默认重启恢复第一章且不启动物理；点击“装扮小车”返回静止的装扮页；恢复名字、颜色、照片与绘画像素；保存图层的 PNG 字节 SHA256 保持一致 |

入场动画配置时长为 2.6 秒。800×600 与 1366×768 各记录了 51 个 `Arriving` 状态采样，小车呈现位置从约 `-1.65` 连续变化到 `0`，显示比例从 `2.2` 缩至 `1`，不是直接跳到中央。所有入场采样均为 `isRunning=false`、物理时间 `0`；此段是场景过渡，随后才进入可操作的倒立摆实验。

两个最终装扮报告均为 `passed: true`。共四个 Player session 的退出码均为 0，`runtimeErrorLines` 和 `nativeDialogDiagnostics` 均为空，未强制终止进程。

## 历史：第一章交互回归检查

两种窗口尺寸各自执行 28 项检查，共 56 项全部通过。原有 18 项检查保留并重新执行：

| 检查范围 | 实际验证内容 |
| --- | --- |
| 窗口与界面（6 项） | 客户区尺寸正确；三个按钮分别完整可见；中文字体、主题和样式可用；22 个渲染对象的材质 shader 受支持 |
| 初始与说明（3 项） | 初始杆竖直且静止；鼠标点击展开说明时不抓取小车；再次点击可收起说明 |
| 拖动与松手（3 项） | 抓取边缘时保留鼠标偏移、无跳变；实际鼠标拖动使小车移动；松手后保留速度和惯性 |
| 倒下与重试（3 项） | 倒下状态出现且轻推按钮禁用；重新抓取后在受边界约束的当前位置扶正；“再试一次”返回中央竖直静止 |
| 外扰与失焦（3 项） | 轻推按钮产生真实物理扰动；失焦前确认正在抓取；失去焦点后解除抓取 |

既有讲解功能的 10 项检查在两个尺寸下均重新通过：

| 项目 | 实际验证内容 |
| --- | --- |
| 1. 讲解布局 | 展开讲解后用顶部卡片替代主标题，卡片不遮挡竖直杆；800×600 下卡片底部为 208 px，杆顶为约 228.06 px |
| 2. 静止时的动量 | 小车静止时隐藏蓝色动量方向箭头 |
| 3. 动量主题入口 | “动量与惯性”标签完整位于讲解卡片内 |
| 4. 重力主题入口 | “重力与力矩”标签完整位于讲解卡片内 |
| 5. 接住主题入口 | “怎样接住”标签完整位于讲解卡片内 |
| 6. 重力方向 | 切换到重力主题，橙色重力箭头显示且竖直向下 |
| 7. 自由浏览 | 切换到“怎样接住”不会启动实验或要求先完成其他主题 |
| 8. 收起讲解 | 收起卡片后恢复主标题 |
| 9. 真实拖动中的动量 | Windows 鼠标拖动小车时，蓝色箭头方向与模型速度方向一致 |
| 10. 倾斜时的重力 | 杆倾斜后，重力箭头仍保持世界坐标竖直向下，不随杆一起转动 |

输入由 Windows OS 鼠标事件产生，测试工具读取 Player 中的模型与 UI 状态作断言。两个最终 `result.json` 均记录 `passed: true`、`playerExitCode: 0`、`runtimeErrorLines: []`。

## 历史：实际导入和运行中修复的问题

- 将 `PanelSettings` 保存为资源资产，再在运行时实例化，以保留 Player 所需的 ICU 和文字渲染资源引用。
- 保留动态系统字体的原始 `font.name`，不再改为自定义名称，避免文字系统无法按字体家族定位系统字形。
- 将 USS 两处按压缩放值从 `.97 .97` 改为 `0.97 0.97`，消除实际导入时的解析告警。

以上修复后重新构建并重跑两种分辨率的 Player 检查。早期 Qt 窗口抓屏曾返回重复的缓存画面；最终取证已改为 Unity `ScreenCapture`，重新生成初始、说明展开、倒下和重置截图，并确认内容随状态变化。旧的 `failure.png` 不是最终验收依据。

讲解卡保持在画面顶部，在展开时替代主标题，保留小车与杆的完整观察区域。蓝色箭头只表达小车动量方向；橙色质心标记与重力箭头帮助观察重力及力矩。三个主题可以随时切换，不增加必做步骤；箭头由实际模型状态驱动，不改变动力学。

上一轮装扮测试首次选图未完成，原因是测试工具使用 `WM_SETTEXT` 写原生文件名控件，没有正确完成文件对话框的输入流程。工具已改用 `Alt+N` 聚焦文件名、实际 Unicode 键盘输入路径并确认打开，随后两种尺寸均真实选图成功。失败清理也改为先取消原生对话框、等待 Unity 恢复写入状态，再关闭主窗口，避免原生模态调用尚未返回时同时关闭 Player；此前由测试清理造成的异常退出不作为普通应用运行失败的结论。

本轮设置测试补充等待讲解卡完成布局后再点击主题，消除了固定短延时下控件尺寸仍为零的测试竞态。QA 专用 `RuntimeProbe` 的状态文件原子替换曾遇到一次短暂的文件占用；现改为下一次写入重试，连续 3 次 I/O 失败才记录告警，成功后清零。读取活动快照仍使用支持 `FILE_SHARE_DELETE` 的句柄。此修复仅作用于带 QA 参数的遥测，不改变学习进度与小车资料的保存规则；普通启动不启用遥测。

## 历史结果文件与截图

以下路径相对于 Unity 工程根目录。日志和测试截图已统一移入本工程 `Logs/Verification`，是被 Git 忽略的本机生成产物；仅检出源码时不会自动获得这些报告。冻结物理参考位于随源码保存的 `Tools/PhysicsCheck/Fixtures`。

| 证据 | 文件 |
| --- | --- |
| 独立工程最新构建日志 | [build-20261122-211120.log](Logs/build-20261122-211120.log) |
| 完整功能验证构建日志 | [build-20261122-205419.log](Logs/build-20261122-205419.log) |
| 源码检查及 SHA256 | [source-check/result.json](Logs/Verification/source-check/result.json) |
| 800×600 设置与退出进度结果 | [progress-800x600/result.json](Logs/Verification/progress-800x600/result.json) |
| 1366×768 设置与退出进度结果 | [progress-1366x768/result.json](Logs/Verification/progress-1366x768/result.json) |
| 独立存储逻辑检查（.NET 测试适配器） | [progress-store-check/result.json](Logs/Verification/progress-store-check/result.json) |
| 独立工程冻结参考完整性 | [frozen-reference-check.json](Logs/Verification/frozen-reference-check.json) |
| 独立工程 .NET 数值重放 | [physics-verification-dotnet.json](Logs/Verification/physics-verification-dotnet.json) |
| Unity Editor 数值验证（模型哈希一致，沿用既有报告） | [physics-verification-unity.json](Logs/Verification/physics-verification-unity.json) |
| 1366×768 装扮、入场与恢复结果 | [studio-1366x768/result.json](Logs/Verification/studio-1366x768/result.json) |
| 800×600 装扮、入场与恢复结果 | [studio-800x600/result.json](Logs/Verification/studio-800x600/result.json) |
| 1366×768 第一章回归结果 | [player-1366x768/result.json](Logs/Verification/player-1366x768/result.json) |
| 800×600 第一章回归结果 | [player-800x600/result.json](Logs/Verification/player-800x600/result.json) |

800×600：设置弹窗完整显示开关、说明与完成按钮，背景操作已禁用。

![800×600 记住上次进度设置](Logs/Verification/progress-800x600/settings-studio.png)

800×600：重启后恢复第一章与“重力与力矩”讲解，小车保留涂鸦，杆从竖直静止开始。

![800×600 恢复学习位置](Logs/Verification/progress-800x600/lesson-resumed.png)

800×600：初始装扮首页，画布与完成入口无需滚动即可使用。

![800×600 装扮首页](Logs/Verification/studio-800x600/studio-initial.png)

1366×768：修改名字和车色，导入测试图片并叠加白色涂鸦；预览小车同步显示合成外观。

![1366×768 装扮完成预览](Logs/Verification/studio-1366x768/studio-customized.png)

本轮装扮测试中的 `lesson-after-arrival.png` 已等待第一章文字淡入完成后再捕获；下面的第一章截图同样来自界面稳定后的回归测试。

1366×768：动量主题展开，三个主题标签与底部操作完整显示；小车静止时不显示动量箭头。

![1366×768 说明展开](Logs/Verification/player-1366x768/explanation.png)

800×600：重力主题显示橙色质心及竖直重力箭头，顶部讲解卡未遮挡杆。

![800×600 重力主题](Logs/Verification/player-800x600/gravity.png)

## 复现方法

以下命令均从 `unity-prototype` 工程根目录运行，不依赖已删除的旧版 `.venv` 或 `src`。源码检查使用 Unity 自带编译器，**不会启动 Unity Editor，也不会构建 Player**：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\Check-Source.ps1
```

冻结参考的来源、哈希和重放方法见 [Tools/PhysicsCheck/README.md](Tools/PhysicsCheck/README.md)。使用系统 Python 校验冻结文件，再由 .NET SDK 重放实际 C# 模型：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\Verify-Physics.ps1
```

也可以在 Unity 菜单选择 **ControlLab → Verify Physics Against Frozen Reference**，或批处理执行 `ControlLab.UnityPrototype.PhysicsVerification.Run`。该操作读取同一冻结参考并产生新的 Unity Editor 数值报告，不重新生成已退役 Python 模型的结果。

关闭正在使用该工程的 Unity Editor 和 Player 后，从 Unity 工程根目录构建 Windows Player：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build-Windows.ps1
```

随后使用已安装的系统 Python 执行真实窗口测试。四个工具仅使用 Python 标准库，不需要旧虚拟环境、PySide6、Gymnasium 或强化学习依赖。测试会移动鼠标并切换窗口焦点，执行时保持桌面可用：

```powershell
python .\Tools\check_settings_windows.py --width 1366 --height 768 --check-github --expect-update-state NoRelease
python .\Tools\check_settings_windows.py --width 800 --height 600
python .\Tools\check_progress_windows.py --width 1366 --height 768
python .\Tools\check_progress_windows.py --width 800 --height 600
python .\Tools\check_studio_windows.py --width 1366 --height 768
python .\Tools\check_studio_windows.py --width 800 --height 600
python .\Tools\check_player_windows.py --width 1366 --height 768
python .\Tools\check_player_windows.py --width 800 --height 600
```

四个工具每次创建新的隔离资料目录，必须串行运行，避免争抢鼠标和窗口焦点。设置与装扮工具在测试内部重启 Player；装扮工具会验证默认恢复第一章后仍可返回装扮修改。第一章回归工具通过界面点击“完成，进入第一章”，等待入场完成后再执行原有检查。若仓库已有符合条件的正式版本，将 `--expect-update-state` 调整为实际预期的 `UpToDate` 或 `Available`；省略 `--check-github` 只运行本地界面检查，不算完成网络验证。

偏好及更新器独立检查需要 .NET SDK，不启动 Unity，也不操作桌面：

```powershell
dotnet run --project .\Tools\PreferencesCheck\PreferencesCheck.csproj --configuration Release -- .\Logs\Verification\preferences-check
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\Check-Updates.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\Tools\Check-Updates.ps1 -Live
```

最后一条额外检查真实 GitHub API，并独立记录网络结果，不下载真实安装包。安装器生成、隔离安装、覆盖升级和安装后的启动检查按 [Windows 安装与发布](Packaging/Windows/README.md) 执行；这些步骤与更新器模拟测试分开记录。构建脚本不自动上传或发布。

## 尚未覆盖的范围

- 其他电脑、显卡、系统缩放和系统字体组合的兼容性。
- 经 GitHub 正式发布后的跨版本在线安装全流程；本地安装器和客户端测试不等于已完成线上分发。当前仓库是否存在适配的正式安装包，以本轮网络报告为准。
- 学生 Python 编程、PID、强化学习及后续课程的数据记录。这些不在第一课自由探索原型中，本轮结果不代表它们已经迁移或通过验收。
