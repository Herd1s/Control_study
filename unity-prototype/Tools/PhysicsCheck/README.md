# 独立物理数值验证

本工具把随 Unity 工程保存的冻结参考数据，逐操作重放到**实际的 C# PendulumModel**。不依赖已删除的旧 Python/Qt 工程，也不需要旧工程的虚拟环境。

参考位于 `Fixtures/physics-golden.json`，共 19 组、3848 次操作；`Fixtures/manifest.json` 固定其 SHA256、协议和操作数。数据由此前的 Python TeachingSimulation 生成，内部的 Python 源文件哈希仅记录历史来源。旧 Python 源码已退出本项目，不能再重新生成这份对照；也不能用待测 C# 实现生成期望值并称为独立比对。

从 Unity 工程根目录运行，需系统 Python（仅标准库）和支持 net9.0 的 .NET SDK：

```powershell
.\Tools\Verify-Physics.ps1
```

本机也可以明确指定已安装的 Python：

```powershell
.\Tools\Verify-Physics.ps1 -PythonCommand 'C:\Python314\python.exe'
```

包装脚本先检查冻结数据完整性，再运行 .NET 重放，报告均写入本 Unity 工程的 `Logs/Verification`。也可分别执行：

```powershell
python .\Tools\PhysicsCheck\verify_frozen_reference.py
dotnet run --project .\Tools\PhysicsCheck\PhysicsCheck.csproj --configuration Release -- .\Tools\PhysicsCheck\Fixtures\physics-golden.json .\Logs\Verification\physics-verification-dotnet.json .\Assets\ControlLab\Scripts\PendulumModel.cs
```

Unity Editor 菜单入口为 **ControlLab → Verify Physics Against Frozen Reference**，或批处理调用 `ControlLab.UnityPrototype.PhysicsVerification.Run`。使用同一冻结参考和实际 C# 模型，输出 `Logs/Verification/physics-verification-unity.json`。Editor 需要适用的 Unity 许可证；.NET 控制台不启动 Unity。

重放覆盖平缓拖动、突然反向、目标边界、松手惯性、轻推与叠加轻推、倒下冻结和原位扶正、重置与固定随机手势，并另有 7 组模型不变量检查。数值容差为 `1e-10`。这项检查验证对照协议下的数学模型，不能替代独立 Player 的鼠标、设置、装扮、界面和退出恢复验证。

当前 Unity 原型使用独立固定步长数学模型，没有让 PhysX 求解倒立摆动力学。后续 PID、强化学习课程需在 Unity 工程中重新实现与验证；旧 Python/Qt 课程和控制源码不再作为依赖。修改动力学协议时，应另行定义参考来源及新的验证方法，并保留本冻结数据的历史身份。
