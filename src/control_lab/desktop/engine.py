"""Qt-independent teaching physics and asynchronous student-code execution.

Student Python runs in another local process to keep a stalled controller from
freezing the interface. This is trusted local code with normal file/network
access, NOT a security sandbox. Terminating the worker does not undo side effects.
"""

from __future__ import annotations

import math
import linecache
import multiprocessing
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
import time
import traceback
import sys
from types import ModuleType
from dataclasses import asdict, replace
from numbers import Real

from control_lab.core.scenario import get_episode_spec, upright_reset_spec
from control_lab.core.session import EpisodeSession
from control_lab.core.types import State
from control_lab.inputs.manual import ManualPositionAssist


class TeachingSimulation:
    """Desktop facade over the same session used by evaluation and training.

    Upright exploration retains the wide 80 degree threshold. Named challenges
    use explicit initial states, limits and force disturbances. Reset always
    returns to rest; start_scenario() starts the configured experiment.
    """

    dt = 0.02

    def __init__(self) -> None:
        self._closed = False
        self._spec = get_episode_spec("upright")
        self._session = EpisodeSession(self._spec)
        self._assist = ManualPositionAssist()
        self.reset()

    @property
    def session(self):
        return self._session

    def configure(self, scenario_id: str):
        self._spec = get_episode_spec(scenario_id)
        self.dt = self._spec.dt_s
        self.reset()

    def configure_spec(self, spec):
        """Restore an explicit recorded configuration without regenerating a seed."""
        from control_lab.core.types import EpisodeSpec
        if not isinstance(spec, EpisodeSpec):
            raise TypeError("spec must be an EpisodeSpec")
        self._spec = spec
        self.dt = spec.dt_s
        return self.reset()

    @property
    def observation(self) -> list[float]:
        """Return a copy, so callers cannot teleport or mutate the simulation."""
        return list(self._session.observed_state)

    def reset(self, seed: int = 42) -> list[float]:
        if self._closed:
            raise RuntimeError("Simulation is closed")
        self._session.reset(spec=upright_reset_spec(self._spec))
        return self.observation

    def start_scenario(self, challenge=False):
        spec = self._spec
        if challenge and not any(spec.scenario.initial_state) and spec.scenario.environment == "cartpole":
            spec = replace(spec, scenario=replace(spec.scenario, initial_state=State(theta=0.05)))
        self._session.reset(spec=spec)
        return self.observation

    @property
    def context(self):
        return {"target_v": self._session.target_velocity_mps,
                "time_s": self._session.step_index * self.dt}

    def add_disturbance(self, force_n=1.0, duration_steps=5):
        self._session.add_disturbance(force_n, duration_steps)

    @staticmethod
    def _result(result):
        return {
            "observation": list(result.observed_state),
            "commanded_force": result.requested_force_n,
            "applied_force": result.actuator_force_n,
            "fell": result.terminated,
            "elapsed": result.simulation_time_s,
            "time_limit": result.truncated,
            "record": asdict(result),
        }

    def step(self, force: float) -> dict:
        if self._closed:
            raise RuntimeError("Simulation is closed")
        return self._result(self._session.step(force))

    def step_manual(self, target_x):
        if self._closed:
            raise RuntimeError("Simulation is closed")
        acceleration = self._assist.acceleration(self._session.true_state, target_x, self.dt)
        return self._result(self._session.step_assisted(acceleration))

    def close(self) -> None:
        if not self._closed:
            self._session.close()
            self._closed = True


def _send_worker_error(connection: Connection, exc: BaseException) -> None:
    try:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=5))
        connection.send(("error", details[-6000:], time.monotonic()))
    except (OSError, EOFError, BrokenPipeError):
        pass


def _code_worker(connection: Connection, code: str, trace_lines: bool = False) -> None:
    """Top-level spawn target, also importable by a frozen Windows executable."""
    try:
        connection.send(("booted", time.monotonic()))
        module = ModuleType("control_lab_student")
        module.__file__ = "<student_controller>"
        sys.modules[module.__name__] = module
        namespace = module.__dict__
        linecache.cache["<student_controller>"] = (len(code), None, code.splitlines(keepends=True), "<student_controller>")
        exec(compile(code, "<student_controller>", "exec"), namespace)
        control = namespace.get("control")
        diagnostics = namespace.get("diagnostics")
        reset = namespace.get("reset")
        if not callable(control) and callable(namespace.get("Controller")):
            from control_lab.inputs.adapters import LegacyControllerAdapter
            adapter = LegacyControllerAdapter(namespace["Controller"]())
            control = lambda state, dt: adapter.act([state[key] for key in ("x", "v", "theta", "omega")], dt)
            reset = adapter.reset
            diagnostics = lambda: adapter.diagnostics or {}
        if not callable(control):
            raise TypeError("请定义函数 control(state, dt)，并返回一个数值。")
        if reset is not None:
            if not callable(reset):
                raise TypeError("reset 必须是一个无参数函数。")
            reset()
        connection.send(("ready", time.monotonic()))
        while True:
            message = connection.recv()
            if message[0] == "stop":
                return
            if message[0] == "reset":
                if reset is not None:
                    reset()
                connection.send(("reset_done", message[1], time.monotonic()))
                continue
            _, request_id, observation, dt, context = message
            state = dict(zip(("x", "v", "theta", "omega"), observation))
            state.update(context)
            executed = []
            def trace(frame, event, arg):
                if event == "line" and frame.f_code.co_filename == "<student_controller>" and len(executed) < 128:
                    if frame.f_lineno not in executed:
                        executed.append(frame.f_lineno)
                return trace
            if trace_lines:
                sys.settrace(trace)
            try:
                raw_value = control(state, dt)
            finally:
                if trace_lines:
                    sys.settrace(None)
            if isinstance(raw_value, bool) or not isinstance(raw_value, Real):
                raise TypeError("control(state, dt) 应返回数值，不能返回 True 或 False。")
            value = float(raw_value)
            if not math.isfinite(value):
                raise ValueError("control(state, dt) 返回了无穷大或 NaN，请返回有限数值。")
            parts = diagnostics() if callable(diagnostics) else {}
            if not isinstance(parts, dict):
                raise TypeError("diagnostics() 应返回字典。")
            allowed = {"p_n", "d_n", "i_n", "centering_n", "unsaturated_n", "applied_n", "integral", "frozen"}
            parts = {key: raw for key, raw in parts.items() if key in allowed}
            for key, raw in parts.items():
                if key == "frozen" and isinstance(raw, bool):
                    continue
                if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(float(raw)):
                    raise ValueError(f"诊断分量 {key} 必须是有限数值。")
                parts[key] = float(raw)
            connection.send(("result", request_id, value, time.monotonic(), parts, executed))
    except (EOFError, BrokenPipeError):
        pass
    except BaseException as exc:
        _send_worker_error(connection, exc)
    finally:
        connection.close()


class CodeController:
    """Single outstanding action request, no blocking reads or waiting joins.

    Usage in a GUI timer: poll(), consume any result/error, then request(obs, dt).
    Requests during startup or while busy are ignored, keeping the pipe bounded.
    Every result corresponds to exactly one requested state. The caller consumes
    it once, advances one physics step, then requests the next action.
    """

    def __init__(self, execution_timeout: float = 0.5, startup_timeout: float = 8.0) -> None:
        if not math.isfinite(execution_timeout) or execution_timeout <= 0:
            raise ValueError("execution_timeout must be finite and positive")
        if not math.isfinite(startup_timeout) or startup_timeout <= 0:
            raise ValueError("startup_timeout must be finite and positive")
        self.execution_timeout = float(execution_timeout)
        self.startup_timeout = float(startup_timeout)
        self.error: str | None = None
        self.last_diagnostics: dict = {}
        self.last_lines: list[int] = []
        self._process: BaseProcess | None = None
        self._connection: Connection | None = None
        self._retired: list[BaseProcess] = []
        self._stage = "stopped"
        self._deadline: float | None = None
        self._request_id = 0
        self._pending = False

    @property
    def ready(self) -> bool:
        return self._stage == "ready" and self.error is None

    @property
    def busy(self) -> bool:
        return self._pending

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def _reap(self) -> None:
        waiting = []
        for process in self._retired:
            if process.is_alive():
                waiting.append(process)
            else:
                process.join(timeout=0)
                process.close()
        self._retired = waiting

    def stop(self) -> None:
        """Terminate promptly; preserve error until the next explicit start()."""
        self._stage = "stopped"
        self._pending = False
        self._deadline = None
        connection, self._connection = self._connection, None
        process, self._process = self._process, None
        if connection is not None:
            connection.close()
        if process is not None:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0)
            if process.exitcode is not None:
                process.close()
            else:
                self._retired.append(process)
        self._reap()

    def _fail(self, message: str) -> None:
        self.error = message
        self.stop()

    def start(self, code: str, *, trace_lines: bool = False) -> None:
        self.stop()
        self.error = None
        self.last_diagnostics = {}
        self.last_lines = []
        if not isinstance(code, str) or not code.strip():
            self.error = "请先编写 control(state, dt) 函数。"
            return
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe(duplex=True)
        process = context.Process(target=_code_worker, args=(child, code, trace_lines), daemon=True)
        try:
            process.start()
        except Exception as exc:
            parent.close()
            child.close()
            self.error = f"无法启动代码进程：{exc}"
            return
        child.close()
        self._connection = parent
        self._process = process
        self._stage = "booting"
        self._pending = False
        self._deadline = time.monotonic() + self.startup_timeout

    def request(self, obs: list[float], dt: float, context: dict | None = None) -> None:
        self._reap()
        if not self.ready or self._pending or self._connection is None:
            return
        try:
            values = [float(value) for value in obs]
            dt = float(dt)
            if len(values) != 4 or not all(math.isfinite(value) for value in values):
                raise ValueError("观测必须包含 4 个有限数值。")
            if not math.isfinite(dt) or dt <= 0:
                raise ValueError("dt 必须是大于 0 的有限数值。")
            extras = dict(context or {})
            if any(key not in {"target_v", "time_s"} for key in extras):
                raise ValueError("未知的控制器上下文字段。")
            if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in extras.values()):
                raise ValueError("控制器上下文必须是有限数值。")
            self._request_id += 1
            self._deadline = time.monotonic() + self.execution_timeout
            self._connection.send(("step", self._request_id, values, dt, extras))
            self._pending = True
        except (Exception, SystemExit) as exc:
            self._fail(f"代码请求失败：{exc}")

    def reset_episode(self) -> bool:
        """Keep the loaded module; invalidate a previous action and call reset once.

        A missing optional reset deliberately leaves student memory intact. The
        acknowledgement is asynchronous and stale step results cannot be applied.
        """
        if not self.ready or self._connection is None:
            return False
        timeout = self.execution_timeout * (2 if self._pending else 1)
        self._request_id += 1
        self._pending = False
        self._stage = "resetting"
        self.last_diagnostics = {}
        self._deadline = time.monotonic() + timeout
        try:
            self._connection.send(("reset", self._request_id))
            return True
        except (OSError, EOFError, BrokenPipeError) as exc:
            self._fail(f"回合重置失败：{exc}")
            return False

    def poll(self) -> float | None:
        self._reap()
        if self._connection is None or self.error is not None:
            return None
        result = None
        try:
            while self._connection is not None and self._connection.poll(0):
                message = self._connection.recv()
                kind = message[0]
                if kind == "booted":
                    self._stage = "initializing"
                    self._deadline = message[1] + self.execution_timeout
                elif kind == "ready":
                    if self._deadline is not None and message[1] > self._deadline:
                        self._fail(f"代码初始化超过 {self.execution_timeout:g} 秒，已停止。请检查顶层循环或耗时操作。")
                        return None
                    self._stage = "ready"
                    self._deadline = None
                elif kind == "result" and self._pending and message[1] == self._request_id:
                    if self._deadline is not None and message[3] > self._deadline:
                        self._fail(f"control() 执行超过 {self.execution_timeout:g} 秒，已停止。请检查循环或耗时操作。")
                        return None
                    result = float(message[2])
                    self.last_diagnostics = dict(message[4])
                    self.last_lines = list(message[5]) if len(message) > 5 else []
                    self._pending = False
                    self._deadline = None
                elif kind == "reset_done" and self._stage == "resetting" and message[1] == self._request_id:
                    if self._deadline is not None and message[2] > self._deadline:
                        self._fail("reset() 执行超时，已停止。")
                        return None
                    self._stage = "ready"
                    self._deadline = None
                elif kind == "error":
                    self._fail(message[1])
                    return None
        except (OSError, EOFError, BrokenPipeError) as exc:
            self._fail(f"代码进程已退出：{exc}")
            return None
        if self._deadline is not None and time.monotonic() > self._deadline:
            if self._stage == "booting":
                self._fail("代码进程启动超时，请重试。")
            elif self._stage == "initializing":
                self._fail(f"代码初始化超过 {self.execution_timeout:g} 秒，已停止。请检查顶层循环或耗时操作。")
            elif self._stage == "resetting":
                self._fail("reset() 执行超时，已停止。请检查回合初始化代码。")
            else:
                self._fail(f"control() 执行超过 {self.execution_timeout:g} 秒，已停止。请检查循环或耗时操作。")
            return None
        if self._process is not None and not self._process.is_alive():
            self._fail(f"代码进程意外退出（退出码 {self._process.exitcode}）。")
            return None
        return result
