"""Portable source builds and bounded persistent V2 engine processes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import shlex
import shutil
import signal
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def executable_default() -> Path:
    return ROOT / ".local" / "bin" / ("hex_search.exe" if os.name == "nt" else "hex_search")


def environment() -> dict:
    """Report hardware context without claiming the reported CPU count is quota."""
    data = {"system": platform.system(), "release": platform.release(),
            "machine": platform.machine(), "python": platform.python_version(),
            "cpu_model": platform.processor(), "logical_cpus": os.cpu_count()}
    if hasattr(os, "sched_getaffinity"):
        data["affinity_cpus"] = len(os.sched_getaffinity(0))
    for name in ("cpu.max", "memory.max"):
        path = Path("/sys/fs/cgroup") / name
        if path.is_file():
            data["cgroup_" + name.replace(".", "_")] = path.read_text().strip()
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.startswith("model name"):
                data["cpu_model"] = line.partition(":")[2].strip()
                break
    return data


def resolve_compiler(compiler: str | None = None) -> list[str]:
    if compiler:
        direct = Path(compiler)
        command = [str(direct)] if direct.is_file() else shlex.split(compiler, posix=os.name != "nt")
        if len(command) == 1 and Path(command[0]).stem.lower() == "zig":
            command.append("c++")
        resolved = shutil.which(command[0]) or (str(Path(command[0]).resolve()) if Path(command[0]).is_file() else None)
        if not resolved:
            raise ValueError("Compiler does not exist: " + command[0])
        command[0] = resolved
        return command
    for name in ("g++", "clang++", "zig"):
        path = shutil.which(name)
        if path:
            return [path, "c++"] if name == "zig" else [path]
    raise ValueError("Install a C++17 compiler (g++, clang++ or zig c++) and retry.")


def build(source: Path | None = None, output: Path | None = None,
          compiler: str | None = None, legacy: bool = False) -> dict:
    source = Path(source or ROOT / ("deployment/agents/Group026/RAVE_TS.cpp" if legacy else "native/hex_search.cpp")).resolve()
    output = Path(output or (executable_default().with_name("legacy_hex.exe" if os.name == "nt" else "legacy_hex") if legacy else executable_default())).resolve()
    if not source.is_file():
        raise ValueError("Source file not found: " + str(source))
    original = ROOT / "deployment" / "agents" / "Group026" / "RAVE_TS"
    if output == original.resolve() or output == source:
        raise ValueError("Build output must not overwrite the preserved original source or executable.")
    if any(output.is_relative_to((ROOT / directory).resolve()) for directory in ("engine", "deployment")):
        raise ValueError("Build outputs belong in .local/build; historical directories are immutable.")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = resolve_compiler(compiler)
    version = subprocess.run(command + ["--version"], capture_output=True, text=True, timeout=20, check=True).stdout.strip()
    flags = ["-std=c++17", "-O3", "-pthread"]
    if os.name == "nt" and "mingw" in (str(command[0]) + version).lower():
        flags += ["-static", "-static-libgcc", "-static-libstdc++"]
    full_command = command + flags + [str(source), "-o", str(output)]
    completed = subprocess.run(full_command, capture_output=True, text=True, timeout=180)
    if completed.returncode:
        raise RuntimeError("Native build failed:\n" + completed.stderr[-12000:])
    receipt = {"schema_version": 1, "kind": "legacy" if legacy else "native",
               "source": str(source), "source_sha256": sha256(source),
               "compiler": command, "compiler_version": version,
               "compiler_sha256": sha256(Path(command[0])), "command": full_command,
               "executable": str(output), "executable_sha256": sha256(output),
               "environment": environment()}
    output.with_name(output.name + ".build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if not legacy:
        test = subprocess.run([str(output), "--self-test"], capture_output=True, text=True, timeout=30)
        receipt["self_test"] = {"returncode": test.returncode, "stdout": test.stdout.strip(), "stderr": test.stderr.strip()}
        if test.returncode:
            raise RuntimeError("Native self-test failed: " + test.stderr + test.stdout)
        output.with_name(output.name + ".build.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


class EngineError(RuntimeError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class NativeProcess:
    """One process per participant and game. Reader threads prevent pipe deadlock."""
    def __init__(self, command: list[str]):
        self.command = command
        self.telemetry: list[dict] = []
        self.lines: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self.peak_rss_bytes = None
        self._stop_sampling = threading.Event()
        options = {"start_new_session": True} if os.name != "nt" else {"creationflags": subprocess.CREATE_NO_WINDOW}
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                        errors="replace", bufsize=1, **options)
        self._threads = [threading.Thread(target=self._read_stdout, daemon=True),
                         threading.Thread(target=self._read_stderr, daemon=True),
                         threading.Thread(target=self._sample_memory, daemon=True)]
        for thread in self._threads:
            thread.start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                self.lines.put(line.rstrip("\r\n"))
        finally:
            self.lines.put(None)

    def _read_stderr(self):
        for line in self.process.stderr:
            line = line.strip()
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = {"kind": "stderr_text", "text": line[:4000]}
            with self._lock:
                self.telemetry.append(item)

    def _memory_bytes(self):
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes
            size_type = ctypes.c_size_t
            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [(name, size_type) for name in
                            ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                             "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            function = ctypes.windll.psapi.GetProcessMemoryInfo
            function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            function.restype = wintypes.BOOL
            if function(int(self.process._handle), ctypes.byref(counters), counters.cb):
                return counters.PeakWorkingSetSize
            return None
        try:
            for line in Path(f"/proc/{self.process.pid}/status").read_text().splitlines():
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError):
            return None

    def _sample_memory(self):
        while not self._stop_sampling.is_set():
            try:
                value = self._memory_bytes()
                if value is not None:
                    self.peak_rss_bytes = max(value, self.peak_rss_bytes or 0)
            except (OSError, AttributeError):
                pass
            self._stop_sampling.wait(.05)

    def request(self, message: str, timeout: float) -> tuple[tuple[int, int], float]:
        started = time.perf_counter()
        if timeout <= 0:
            raise EngineError("timeout", "Participant exhausted its game budget.")
        try:
            self.process.stdin.write(message + "\n")
            self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            raise EngineError("process_error", "Native process exited before receiving a position.") from None
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty:
            raise EngineError("timeout", "Native response exceeded the configured timeout.") from None
        if line is None:
            raise EngineError("process_error", "Native stdout closed without a move.")
        fields = line.split(",")
        try:
            if len(fields) != 2:
                raise ValueError
            move = int(fields[0]), int(fields[1])
        except ValueError:
            raise EngineError("protocol_error", "Expected exactly two comma-separated integer coordinates.") from None
        return move, time.perf_counter() - started

    def close(self):
        value = self._memory_bytes()
        if value is not None:
            self.peak_rss_bytes = max(value, self.peak_rss_bytes or 0)
        self._stop_sampling.set()
        try:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            self.process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            if self.process.poll() is None:
                if os.name != "nt":
                    try:
                        os.killpg(self.process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    self.process.kill()
                self.process.wait(timeout=3)
        for thread in self._threads:
            thread.join(timeout=1)
        for stream in (self.process.stdout, self.process.stderr):
            if stream:
                stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
