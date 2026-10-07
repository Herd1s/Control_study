"""Run local student code in a disposable process with bounded calls.

This is execution isolation, not a security sandbox: student code still has the
user's filesystem permissions. No student import is executed in this process.
"""
import hashlib
import os
import time

from control_lab.controllers._common import state_values
from control_lab.desktop.engine import CodeController
from .adapters import FunctionControllerAdapter


class ControllerExecutionError(RuntimeError):
    def __init__(self, message, phase):
        super().__init__(message)
        self.phase = phase


class ControllerTimeoutError(ControllerExecutionError):
    pass


class _WorkerLifetime:
    """Windows closes this job when a QProcess evaluator is forcibly stopped."""
    def __init__(self, pid):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes as w

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong),
                        ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD),
                        ("SchedulingClass", w.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in
                        ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
        kernel.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        kernel.SetInformationJobObject.restype = w.BOOL
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
        kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        try:
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            limits = Extended()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not kernel.AssignProcessToJobObject(self.handle, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                kernel.CloseHandle(process)
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class IsolatedControllerAdapter(FunctionControllerAdapter):
    """Same module across healthy episodes; exactly one reset per episode.

    A failed worker is replaced at the next episode, with its restart recorded.
    Initialization failures are cached: executing the same broken import for
    every benchmark case adds no evidence and unnecessarily repeats side effects.
    """
    def __init__(self, source, filename="<student_controller>", *, execution_timeout=.5, startup_timeout=8.0):
        self.source = source.encode("utf-8") if isinstance(source, str) else bytes(source)
        self.code = self.source.decode("utf-8-sig")
        self.source_sha256 = hashlib.sha256(self.source).hexdigest()
        self.source_filename = str(filename)
        self.worker = CodeController(execution_timeout=execution_timeout, startup_timeout=startup_timeout)
        self._lifetime = None
        self._initialization_error = None
        self.worker_generation = 0

    def evaluation_identity(self):
        return {"execution": "isolated-student-v1", "source_sha256": self.source_sha256,
                "execution_timeout_s": self.worker.execution_timeout,
                "startup_timeout_s": self.worker.startup_timeout}

    @property
    def diagnostics(self):
        return dict(self.worker.last_diagnostics)

    @property
    def pid(self):
        return self.worker.pid

    def _wait(self, phase, *, action=False):
        while True:
            result = self.worker.poll()
            if self.worker.error:
                timed_out = self.worker.error.startswith(("代码进程启动超时", "代码初始化超过", "control() 执行超过", "reset() 执行超时"))
                cls = ControllerTimeoutError if timed_out else ControllerExecutionError
                raise cls(self.worker.error, phase)
            if action and result is not None:
                return result
            if not action and self.worker.ready:
                return
            time.sleep(.001)

    def reset(self):
        if self._initialization_error is not None:
            raise self._initialization_error
        if self.worker.ready:
            if not self.worker.reset_episode():
                raise ControllerExecutionError(self.worker.error or "reset request rejected", "reset")
            self._wait("reset")
            return
        self.close()
        self.worker.start(self.code)
        self.worker_generation += 1
        try:
            if self.worker.pid:
                self._lifetime = _WorkerLifetime(self.worker.pid)
            self._wait("initialize")  # The worker already calls reset here, once.
        except (Exception, SystemExit) as exc:
            self._initialization_error = exc
            self.close()
            raise

    def act(self, observation, dt, context=None):
        if not self.worker.ready:
            raise ControllerExecutionError("Reset the controller before requesting an action", "control")
        self.worker.request(state_values(observation), dt, context=context)
        return self._wait("control", action=True)

    def close(self):
        self.worker.stop()
        if self._lifetime is not None:
            self._lifetime.close()
            self._lifetime = None
        # CodeController.stop() is deliberately nonblocking for the GUI. Brief
        # polls reap retired process handles without depending on private fields.
        self.worker.poll()
