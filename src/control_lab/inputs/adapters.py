"""Map student functions and legacy classes to one requested-force interface.

Loading executes trusted local Python once. This synchronous adapter is not a
security or timeout sandbox; GUI execution continues to use its worker process.
"""
import hashlib
import importlib.util
from pathlib import Path
import sys
import types
from collections.abc import Mapping
import numpy as np

from control_lab.controllers._common import finite_number, positive, state_values


class FunctionControllerAdapter:
    def __init__(self, control, reset=None, diagnostics=None):
        if not callable(control) or (reset is not None and not callable(reset)):
            raise TypeError("control and optional reset must be callable")
        self.control = control
        self.reset_hook = reset
        if diagnostics is not None and not callable(diagnostics):
            raise TypeError("optional diagnostics must be callable")
        self.diagnostics_hook = diagnostics

    @property
    def diagnostics(self):
        parts = self.diagnostics_hook() if self.diagnostics_hook is not None else {}
        if not isinstance(parts, dict):
            raise TypeError("diagnostics() must return a dictionary")
        allowed = {"p_n", "d_n", "i_n", "centering_n", "unsaturated_n", "applied_n", "integral", "frozen"}
        return {key: value if key == "frozen" and isinstance(value, bool) else finite_number(value, key)
                for key, value in parts.items() if key in allowed}

    def reset(self):
        if self.reset_hook is not None:
            self.reset_hook()

    def act(self, observation, dt, context=None):
        values = state_values(observation)
        state = dict(zip(("x", "v", "theta", "omega"), values))
        if isinstance(observation, Mapping):
            for field in ("target_v", "time_s"):
                if field in observation:
                    state[field] = finite_number(observation[field], field)
        if context is not None:
            if not isinstance(context, Mapping):
                raise TypeError("controller context must be a mapping")
            if set(context) - {"target_v", "time_s"}:
                raise ValueError("context may contain only target_v and time_s; state fields cannot be replaced")
            for field, value in context.items():
                state[field] = finite_number(value, field)
        return finite_number(self.control(state, positive(dt, "dt")), "controller force")


class LegacyControllerAdapter:
    def __init__(self, controller):
        if not callable(getattr(controller, "reset", None)) or not callable(getattr(controller, "act", None)):
            raise TypeError("Controller must define reset() and act(observation, dt)")
        self.controller = controller

    @property
    def diagnostics(self):
        return getattr(self.controller, "diagnostics", None)

    def reset(self):
        self.controller.reset()

    def act(self, observation, dt, context=None):
        copied = np.asarray(state_values(observation), dtype=np.float64)
        return finite_number(self.controller.act(copied, positive(dt, "dt")), "controller force")


def controller_from_source(source: str | bytes, filename="<student_controller>"):
    data = source.encode("utf-8") if isinstance(source, str) else source
    if not isinstance(data, bytes):
        raise TypeError("source must be text or bytes")
    # Each load gets fresh module globals; each episode resets the same instance.
    name = "control_lab_student_" + hashlib.sha256(data).hexdigest()[:16]
    module = types.ModuleType(name)
    module.__file__ = str(filename)
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(data, str(filename), "exec"), module.__dict__)
        if callable(getattr(module, "control", None)):
            controller = FunctionControllerAdapter(module.control, getattr(module, "reset", None),
                                                   getattr(module, "diagnostics", None))
        elif callable(getattr(module, "Controller", None)):
            controller = LegacyControllerAdapter(module.Controller())
        else:
            raise TypeError("Define control(state, dt), or a Controller class with reset/act")
        controller.source_sha256 = hashlib.sha256(data).hexdigest()
        controller.source = data
        controller.source_filename = str(filename)
        controller.module = module
        return controller
    finally:
        # The adapter holds the module/functions. Avoid leaking every edit into sys.modules.
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def load_controller(path):
    path = Path(path).expanduser().resolve()
    return controller_from_source(path.read_bytes(), path)
