from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Lock
from typing import Sequence


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    crashed: bool


class ProcessManager:
    """Manage one workspace process and capture its output."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._process: subprocess.Popen[str] | None = None
        self._lock = Lock()

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def start(self, command: Sequence[str]) -> None:
        if not command:
            raise ValueError("command must not be empty")
        with self._lock:
            if self.running:
                raise RuntimeError("process is already running")
            try:
                self._process = subprocess.Popen(
                    list(command),
                    cwd=self.workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError:
                self._process = None
                raise

    def stop(self, timeout: float = 3.0) -> ProcessResult | None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        with self._lock:
            process = self._process
            if process is None:
                return None
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
            result = ProcessResult(
                returncode=process.returncode,
                crashed=process.returncode not in (0, -15),
            )
            self._process = None
            return result

    def poll(self) -> ProcessResult | None:
        process = self._process
        if process is None:
            return None
        returncode = process.poll()
        if returncode is None:
            return None
        with self._lock:
            if self._process is process:
                self._process = None
        return ProcessResult(
            returncode=returncode,
            crashed=returncode != 0,
        )

    def read_available(self) -> str:
        process = self._process
        if process is None or process.stdout is None:
            return ""
        return process.stdout.read(0)

    def communicate(self, timeout: float | None = None) -> str:
        process = self._process
        if process is None or process.stdout is None:
            return ""
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return ""
        return output
