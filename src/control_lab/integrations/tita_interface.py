"""Versioned TITA interfaces from a real external Isaac Lab environment.

The desktop imports only standard-library code. The probe runs in the selected
robotics Python and creates one headless simulation, without policy training.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

INTERFACE_MARKER = "CONTROLLAB_TITA_INTERFACE "

# Kept as a string so frozen desktops can launch this in a different Python ABI.
INTERFACE_PROBE = r'''
import hashlib, importlib, importlib.metadata, inspect, json, pathlib, platform, subprocess, sys
from datetime import datetime, timezone
profile, output = json.loads(sys.argv[1]), pathlib.Path(sys.argv[2])
from isaaclab.app import AppLauncher
launcher = AppLauncher({"headless": True})
app = launcher.app
try:
    import gymnasium as gym
    import torch
    import ddt_lab.tasks
    train_id = "DDT-Velocity-Flat-Tita-v0"
    play_id = "DDT-Velocity-Flat-Tita-Play-v0"
    def plain(value):
        if value is None or isinstance(value, (str, bool, int, float)): return value
        if isinstance(value, torch.Tensor): return value.detach().cpu().tolist()
        if isinstance(value, (list, tuple)): return [plain(x) for x in value]
        if isinstance(value, dict): return {str(k): plain(v) for k,v in value.items()}
        if callable(value): return value.__module__ + ":" + value.__name__
        if hasattr(value, "__dict__"):
            return {k: plain(v) for k,v in vars(value).items() if not k.startswith("_")}
        return str(value)
    def config(task):
        entry = gym.spec(task).kwargs["env_cfg_entry_point"]
        if isinstance(entry, str):
            module, name = entry.split(":")
            entry = getattr(importlib.import_module(module), name)
        return entry()
    cfg, play_cfg = config(train_id), config(play_id)
    def snapshot(c):
        return dict(num_envs=c.scene.num_envs, env_spacing=c.scene.env_spacing,
                    control_dt_s=c.sim.dt*c.decimation, physics_dt_s=c.sim.dt,
                    policy=plain(c.observations.policy), actions=plain(c.actions),
                    commands=plain(c.commands), events=plain(c.events))
    train_snapshot, play_snapshot = snapshot(cfg), snapshot(play_cfg)
    differences = []
    def diff(a,b,path=""):
        if isinstance(a,dict) and isinstance(b,dict):
            for key in sorted(set(a)|set(b)): diff(a.get(key), b.get(key), (path+"."+key).strip("."))
        elif a != b: differences.append(dict(field=path, train=a, play=b))
    diff(train_snapshot, play_snapshot)
    cfg.scene.num_envs = 1
    cfg.seed = 42
    env = gym.make(train_id, cfg=cfg)
    try:
        env.reset(seed=42)
        base = env.unwrapped
        robot = base.scene["robot"]
        am, om = base.action_manager, base.observation_manager
        actions = []
        for name in am.active_terms:
            term = am.get_term(name)
            kind = type(term).__name__
            unit = {"JointPositionAction":"rad", "JointVelocityAction":"rad/s", "JointEffortAction":"N*m"}.get(kind)
            if unit is None: raise ValueError("Unmapped action semantics: " + kind)
            joints = term._joint_names
            def at(value, j):
                value = plain(value)
                while isinstance(value,list) and len(value)==1 and isinstance(value[0],list): value=value[0]
                return value[j] if isinstance(value,list) else value
            for j,joint in enumerate(joints):
                actions.append(dict(index=len(actions), term=name, joint=joint, type=kind,
                    raw_unit="dimensionless", target_unit=unit, scale=at(term._scale,j),
                    offset=at(term._offset,j), clip=plain(term.cfg.clip),
                    processing="target = clip(raw * scale + offset); clip uses target units"))
        obs = om.compute(update_history=False)
        groups = {}
        source_functions = []
        for group,names in om.active_terms.items():
            terms, cursor = [], 0
            gc = getattr(cfg.observations, group)
            for name, tc, shape in zip(names,om._group_obs_term_cfgs[group],om.group_obs_term_dim[group]):
                raw = tc.func(base, **tc.params)
                width = raw.shape[-1]
                fn = tc.func.__name__
                source_functions.append(tc.func)
                params = tc.params
                asset = params.get("asset_cfg")
                joints = list(robot.joint_names)
                if asset is not None:
                    ids = asset.joint_ids
                    joints = joints[ids] if isinstance(ids,slice) else [joints[int(i)] for i in ids]
                units = {"base_lin_vel":"m/s", "base_ang_vel":"rad/s", "projected_gravity":"dimensionless",
                         "joint_pos_rel_without_wheel":"rad", "joint_pos_rel":"rad", "joint_vel_rel":"rad/s",
                         "last_action":"dimensionless", "contact_state":"dimensionless",
                         "joint_kp_factor":"dimensionless", "joint_kd_factor":"dimensionless"}
                if fn == "generated_commands":
                    components, unit = ["vx_body","vy_body","yaw_rate"], ["m/s","m/s","rad/s"]
                elif fn in ("base_lin_vel","base_ang_vel","projected_gravity"):
                    components, unit = ["x_body","y_body","z_body"], [units[fn]]*width
                elif fn == "last_action":
                    components, unit = [a["joint"] for a in actions], [units[fn]]*width
                elif fn == "contact_state":
                    sensor=params["sensor_cfg"]
                    bodies=base.scene.sensors[sensor.name].body_names
                    ids=sensor.body_ids
                    components=bodies[ids] if isinstance(ids,slice) else [bodies[int(i)] for i in ids]
                    unit=[units[fn]]*width
                elif fn in units:
                    components, unit = joints, [units[fn]]*width
                else: raise ValueError("Unmapped observation semantics: " + fn)
                if len(components)!=width: raise ValueError("Component/width mismatch: " + group+"/"+name)
                terms.append(dict(name=name, function=tc.func.__module__+":"+fn,
                    start=cursor, stop=cursor+width, width=width, components=components, raw_units=unit,
                    manager_shape=list(shape), scale=plain(tc.scale), clip=plain(tc.clip), noise=plain(tc.noise),
                    history_length=tc.history_length, flatten_history_dim=tc.flatten_history_dim,
                    note="Wheel entries retained as zero before observation noise (not removed)." if fn=="joint_pos_rel_without_wheel" else ""))
                cursor += width
            groups[group]=dict(terms=terms, frame_width=cursor, tensor_shape=list(obs[group].shape),
                enable_corruption=gc.enable_corruption, history_length=gc.history_length,
                flatten_history_dim=gc.flatten_history_dim,
                history_order="oldest_to_newest", actor_input=group=="policy")
        sources = {}
        from isaaclab.envs.mdp.actions import joint_actions
        from isaaclab.utils.buffers.circular_buffer import CircularBuffer
        for obj in [type(cfg), type(play_cfg), type(cfg).__mro__[1], joint_actions, CircularBuffer, *source_functions]:
            filename=inspect.getsourcefile(obj)
            if filename and pathlib.Path(filename).is_file():
                p=pathlib.Path(filename); sources[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
        repos={}
        for name,path in (("DDT_Lab",profile["ddt_root"]),("IsaacLab",profile["isaaclab_root"])):
            result=subprocess.run(["git","-C",path,"rev-parse","HEAD"],capture_output=True,text=True,timeout=10)
            dirty=subprocess.run(["git","-C",path,"status","--porcelain","--untracked-files=no"],capture_output=True,text=True,timeout=10)
            repos[name]=dict(path=path,commit=result.stdout.strip(),modified_tracked_files=dirty.stdout.splitlines())
        report=dict(schema_version=1,kind="tita_runtime_interface",environment_id=train_id,play_environment_id=play_id,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),hardware_control=False,
            measurement_scope="Training task: one actual headless environment reset; play differences: instantiated configuration, not a second rollout.",
            python=platform.python_version(),packages={n:importlib.metadata.version(n) for n in ("isaacsim","isaaclab","torch","ddt_lab")},
            repositories=repos,source_sha256=sources,seed=42,runtime_num_envs=1,
            control_dt_s=base.step_dt,physics_dt_s=cfg.sim.dt,decimation=cfg.decimation,
            observation_groups=groups,observation_names=[t["name"] for t in groups["policy"]["terms"]],
            action_names=[a["joint"] for a in actions],action_units=[a["target_unit"] for a in actions],actions=actions,
            actuator_config=plain(cfg.scene.robot.actuators),train_configuration=train_snapshot,
            play_configuration=play_snapshot,train_play_differences=differences,
            zero_action_note="Raw zero requests default joint-position offsets and zero wheel-velocity targets; it is NOT motor disable or a hardware emergency stop.")
        report["interface_sha256"]=hashlib.sha256(json.dumps(report,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.open("x",encoding="utf-8") as f: json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
        print("CONTROLLAB_TITA_INTERFACE "+str(output),flush=True)
    finally: env.close()
finally: app.close()
'''


def load_interface(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("kind") != "tita_runtime_interface" or data.get("schema_version") != 1:
        raise ValueError("不是受支持的 TITA 运行时接口表")
    digest = data.get("interface_sha256")
    payload = {k: v for k, v in data.items() if k != "interface_sha256"}
    actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if digest != actual:
        raise ValueError("接口表内容与记录的 SHA256 不一致")
    if not data.get("actions") or data.get("control_dt_s", 0) <= 0:
        raise ValueError("接口表缺少实际动作或控制周期")
    return data


def interface_summary(data):
    policy = data["observation_groups"]["policy"]
    lines = [data["environment_id"], f"控制周期 {data['control_dt_s']:g} s；策略输入 {policy['tensor_shape']}（批次、历史、单帧）；动作 {len(data['actions'])} 维。",
             "观测顺序（半开索引 / 分量 / 原始单位 / 缩放）："]
    for term in policy["terms"]:
        lines.append(f"[{term['start']}:{term['stop']}] {term['name']} / {', '.join(term['components'])} / {', '.join(term['raw_units'])} / {term['scale']}")
    lines.append("动作顺序（raw 无量纲，经 scale+offset 后限幅）：")
    for action in data["actions"]:
        lines.append(f"[{action['index']}] {action['joint']} → {action['type']}，{action['target_unit']}；scale={action['scale']} offset={action['offset']} clip={action['clip']}")
    lines.extend(["历史由旧到新；轮子位置维保留并在加噪前置零。", "训练 / 回放配置差异："])
    for change in data["train_play_differences"]:
        def compact(value):
            return "启用（参数见 JSON）" if isinstance(value, dict) else "禁用" if value is None else str(value)
        lines.append(f"{change['field']}: {compact(change['train'])} → {compact(change['play'])}")
    lines.extend(["完整 JSON 同时保存未变化的命令、复位和材料随机化；回放并非关闭所有随机化。",
                  "测量范围：训练任务创建一个实际仿真；回放差异来自实例化配置，未单独运行第二个场景。",
                  "原始零动作表示默认关节位置偏置与零轮速目标，不等于切断电机或实机急停。"])
    return "\n".join(lines)


def check_policy_compatibility(interface, metadata):
    """Reject mismatched identities/shapes; does not execute or deserialize a model."""
    if not isinstance(metadata, dict):
        raise ValueError("模型元数据必须是 JSON 对象")
    candidate = dict(metadata)
    environment = metadata.get("environment")
    if isinstance(environment, dict) and isinstance(environment.get("observation"), dict) and isinstance(environment.get("action"), dict):
        fields = environment["observation"].get("fields")
        actions = environment["action"].get("fields")
        if not isinstance(fields, list) or not fields or not isinstance(actions, list) or not actions:
            raise ValueError("模型环境缺少观测/动作字段，不能完成兼容性实验")
        candidate.update(environment_id=environment.get("environment_id"),
                         observation_shape=[len(fields)], action_dim=len(actions))
    if (not isinstance(candidate.get("environment_id"), str) or
            not isinstance(candidate.get("observation_shape"), list) or
            not candidate["observation_shape"] or type(candidate.get("action_dim")) is not int):
        raise ValueError("不是可识别的策略元数据：需要环境标识、观测形状和动作维数")
    expected = {"environment_id": interface["environment_id"],
                "observation_shape": interface["observation_groups"]["policy"]["tensor_shape"][1:],
                "action_dim": len(interface["actions"]),
                "interface_sha256": interface["interface_sha256"]}
    reasons = [f"{key}: expected {value!r}, got {candidate.get(key)!r}"
               for key, value in expected.items() if candidate.get(key) != value]
    return {"compatible": not reasons, "reasons": reasons, "model_executed": False,
            "candidate_interface": {key: candidate.get(key) for key in expected},
            "hardware_control": False, "scope": "metadata only; matching metadata does not validate policy performance"}
