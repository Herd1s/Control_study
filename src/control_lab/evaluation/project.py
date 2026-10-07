"""Export explicitly selected, verified control-method evidence as a project."""
import hashlib
import json
from pathlib import Path
import zipfile

from .compare import compare_reports
from .report_io import load_evaluation


def _reproduction_source(record):
    bundle = record.snapshot
    if bundle is None:
        raise ValueError("Every selected method needs a controller source/configuration snapshot")
    sources = bundle.get("sources", {})
    if "student_controller.py" in sources:
        return sources["student_controller.py"]
    name = bundle["controller_class"]
    config = dict(bundle["configuration"])
    if name == "control_lab.controllers.ZeroController":
        return "def control(state, dt):\n    return 0.0\n"
    if name == "control_lab.controllers.reference_pid.Controller":
        code = ["from control_lab.controllers.reference_pid import Controller",
                f"_controller = Controller(center_cart={config['center_cart']!r})"]
        for key, value in config["gains"].items():
            if key not in {"kp", "ki", "kd", "cart_kp", "cart_kd"}:
                raise ValueError("Unknown reference-controller parameter")
            code.append(f"_controller.gains.{key} = {value!r}")
        for key in ("force_limit", "integral_limit"):
            code.append(f"_controller.{key} = {config[key]!r}")
    elif name in {"control_lab.controllers.p.PController", "control_lab.controllers.pd.PDController",
                  "control_lab.controllers.pid.PIDController"}:
        module, class_name = name.rsplit(".", 1)
        code = [f"from {module} import {class_name}",
                "from control_lab.controllers.centering import CenteringFeedback"]
        allowed = {"kp", "ki", "kd", "force_limit_n", "integral_limit", "anti_windup"}
        arguments = [f"{key}={value!r}" for key, value in config.items() if key in allowed]
        if config.get("centering") is not None:
            center = config["centering"]
            arguments.append(f"centering=CenteringFeedback(kx={center['kx']!r}, kv={center['kv']!r})")
        if config.get("derivative_filter") is not None:
            raise ValueError("Export filtered custom controllers as a student source file so their filter configuration is explicit")
        code.append(f"_controller = {class_name}({', '.join(arguments)})")
    else:
        raise ValueError(f"This controller needs an explicit student source for project reproduction: {name}")
    code += ["", "def reset():", "    _controller.reset()", "", "def control(state, dt):",
             "    return _controller.act([state[k] for k in ('x', 'v', 'theta', 'omega')], dt)", ""]
    return "\n".join(code)


def export_project(report_paths, destination, *, title="我的倒立摆控制项目", reflection=""):
    records = [load_evaluation(path, require_complete=True) for path in report_paths]
    if len(records) < 3 or len(records) > 12:
        raise ValueError("Select 3 to 12 complete method reports for a course project")
    if len({record.report["controller_sha256"] for record in records}) != len(records):
        raise ValueError("Select distinct controller configurations, not repeated copies of the same method")
    comparison = compare_reports(record.report for record in records)
    if records[0].report["split"] == "held_out":
        raise ValueError("Use practice/validation reports for the reproducible tuning project; retain held-out evidence separately")
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Project export will not overwrite {destination}")
    files, methods, commands = {}, [], []
    json_bytes = lambda value: json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    for index, record in enumerate(records, 1):
        prefix = f"methods/{index:02d}"
        report = record.report
        source = _reproduction_source(record)
        files[prefix + "/controller.py"] = source.encode("utf-8")
        for name in ("report.json", "protocol.json", "controller_snapshot.json"):
            files[prefix + "/" + name] = (record.folder / name).read_bytes()
        for episode in report["episodes"]:
            record.case_rows(episode["case_id"])  # Validate before creating a ZIP.
            relative = Path(episode["trajectory_file"])
            files[prefix + "/" + relative.as_posix()] = (record.folder / relative).read_bytes()
        parameters = {"controller_class": record.snapshot["controller_class"],
                      "configuration": record.snapshot["configuration"],
                      "source_controller_sha256": report["controller_sha256"],
                      "reproduction_source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest()}
        files[prefix + "/parameters.json"] = json_bytes(parameters)
        command = (f"control-lab evaluate --controller student --controller-file {prefix}/controller.py "
                   f"--protocol {report['protocol_id']} --split {report['split']} --output-dir reproduced/{index:02d}")
        commands.append(command)
        methods.append({"folder": prefix, "controller": report["controller"], "controller_sha256": report["controller_sha256"],
                        "control_lab_version": report["control_lab_version"], "command": command,
                        "aggregate": report["aggregate"]})
    files["comparison.json"] = json_bytes(comparison)
    lines = [f"# {title.strip() or '我的倒立摆控制项目'}", "", "## 实验问题与解释", "",
             reflection.strip() or "请补充：预测、结果、失败原因、参数选择与仍存在的局限。", "",
             "## 固定条件", "", "所有方法使用同一协议、用例、动作限制、观测和奖励。详情见各方法 protocol.json。",
             "真实记录不会为失败补足步数。源报告和快照保留原指纹；内置控制器另生成等价参数的学生入口，入口指纹会不同。", "",
             "| 方法 | 完成回合 | 平均步数 | 最差步数 |", "| --- | --- | --- | --- |"]
    for method in methods:
        summary = method["aggregate"]
        lines.append(f"| {method['controller'].replace('|', '/')} | {summary['completed_episodes']}/{summary['episodes']} | {summary['mean_steps']:.2f} | {summary['worst_steps']} |")
    lines += ["", "## 在 VS Code 终端复算", "", "解压后以本目录为工作目录，激活对应版本的 ControlLab 环境。安装版可把 control-lab 换成 ControlLabCLI.exe 的完整路径。",
              "使用 manifest.json 记录的软件版本；学生源码的额外第三方依赖需由作者补充，不包含用户机器环境或私有目录。", "", "```powershell", *commands,
              "```", "", "复算目录必须不存在或为空。比较新结果中的完成率、错误、用力与摆角；不得据保留测试调参。",
              "", "## 文件说明", "", "- methods/：明确选中的源码、参数、协议、报告和全部逐步轨迹。",
              "- comparison.json：同协议的多方法对照。", "- manifest.json：软件版本、配置指纹和逐文件 SHA256。", ""]
    files["README.md"] = "\n".join(lines).encode("utf-8")
    manifest = {"schema_version": 1, "kind": "control_course_project", "title": title,
                "methods": methods, "protocol_hash": records[0].report["protocol_hash"],
                "cases_hash": records[0].report["cases_hash"],
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("manifest.json", json_bytes(manifest))
    return {"path": str(destination), "method_count": len(methods), "file_count": len(files)+1,
            "protocol_hash": manifest["protocol_hash"], "cases_hash": manifest["cases_hash"],
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest()}
