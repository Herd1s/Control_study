"""Targeted resource migration; never regenerate unrelated authored lessons."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/control_lab/lessons/content"


def update(lesson_id):
    path = ROOT / f"{lesson_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = {step["id"]: step for step in data["steps"]}
    if lesson_id == "L14":
        steps["step_03"].update(
            instruction="先手动运行并保存三次同初态实验，再打开‘P / PI 参数实验’，用0、20、40、60、100做P扫描。查看scan.csv和每个失败原因。",
            evidence="保存三次实际实验，并完成一次至少三参数的P扫描。",
            completion={"all": [{"event": "experiment.saved", "min_count": 3},
                                {"event": "sweep.completed", "field": "kind", "equals": "p"},
                                {"event": "sweep.completed", "field": "candidate_count", "min": 3}]})
        steps["step_04"].update(activity="predict", instruction="查看扫描窗口同一坐标轴的真实角度曲线，写出一次过零后的运动现象。若没有持续振荡，如实写下，不把一次过零当振荡。",
                                 evidence="保存自己的曲线观察。", completion={"event": "prediction.submitted", "field": "value"})
        steps["step_06"].update(activity="experiment", instruction="在扫描窗口选择复核初态θ=−0.03 rad、ω=+0.05 rad/s，保持其他条件与Kp列表不变，再完成一次扫描。",
                                 evidence="完成‘复核初态’的P扫描。",
                                 completion={"all": [{"event": "sweep.completed", "field": "kind", "equals": "p"},
                                                     {"event": "sweep.completed", "field": "condition", "equals": "check"}]})
        data["notes"] = data["notes"].replace("软件后续提供“用这些参数重复实验”按钮。不要把以上打印循环误称为已经实现了批量仿真。",
            "软件的‘P / PI 参数实验’现已提供真实后台扫描，输出 scan.csv、scan.json 和每个候选的源码/条件/轨迹。打印循环本身仍不会推进物理。")
    elif lesson_id == "L21":
        steps["step_04"].update(activity="experiment", instruction="在评价面板依次评估零输入、角度PD、PD加回中，使用同一开发验证集100–119；代码错误与失败回合也保留。",
                                 evidence="完成至少三份评价，其中包含零输入基线。",
                                 completion={"all": [{"event": "comparison.saved", "min_count": 3},
                                                     {"event": "comparison.saved", "field": "controller", "equals": "zero"}]})
        steps["step_05"].update(activity="record", instruction="点击‘比较多个报告’，选择至少三种同条件方法。先看失败和通过率，再看平均/最差步数、角RMS、最大位置、用力和饱和比例。",
                                 evidence="保存一份至少三种方法的正式报告对照。",
                                 completion={"event": "comparison.completed", "field": "method_count", "min": 3})
        steps["step_06"].update(activity="observe", instruction="打开评价报告，分别查看一个通过回合和一个实际倒下回合，拖动时间滑条；在‘详细指标·协议·代码’核对源码与配置。可添加同条件报告并排回放。",
                                 evidence="真正打开一个通过与一个失败的轨迹回放。",
                                 completion={"all": [{"event": "evaluation.replayed", "field": "completed", "equals": True},
                                                     {"event": "evaluation.replayed", "field": "completed", "equals": False}]})
        start, end = data["notes"].find("**可立即用于现有 CLI"), data["notes"].find("**实验条件与对照**")
        if start >= 0 and end > start:
            data["notes"] = data["notes"][:start] + (
                "**正式 CLI**：使用 `control-lab evaluate --controller zero --split validation --output-dir runs/zero`，"
                "将控制器改为 `reference-angle` 与 `reference` 分别保存。三者读取冻结非零case表，不能用旧版 `run --seed` 代替正式协议。"
                "界面提供逐回合详细指标、回放和同协议报告比较；学生代码在独立进程限时运行。\n\n") + data["notes"][end:]
    elif lesson_id == "L22":
        steps["step_04"].update(evidence="运行并保留一份有控制器指纹的完整开发验证报告。",
                                 completion={"all": [{"event": "comparison.saved", "field": "split", "equals": "validation"},
                                                     {"event": "comparison.saved", "field": "controller_sha256"}]})
        steps["step_06"].update(activity="record", instruction="点击‘导出课程项目’，勾选至少三种不同方案的同条件练习/验证报告，补充解释并导出ZIP。包内包含README、源码、参数、协议和可回放轨迹；请同学按命令复算。",
                                 evidence="实际导出包含至少三种方法的项目ZIP；同伴讲解单独验收。",
                                 completion={"event": "project.exported", "field": "method_count", "min": 3})
    data["content_version"] = max(2, data["content_version"])
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    for lesson_id in ("L14", "L21", "L22"):
        update(lesson_id)
