from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
from threading import Lock
from typing import BinaryIO, Sequence


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    crashed: bool


class ProcessManager:
    """Manage one workspace process and capture output without pipe-reader races."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()
        self._log_file: BinaryIO | None = None
        self._log_offset = 0
        self._stop_requested = False

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
            if self._log_file is not None:
                self._log_file.close()
            self._log_file = tempfile.TemporaryFile(mode="w+b")
            self._log_offset = 0
            try:
                self._stop_requested = False
                self._process = subprocess.Popen(
                    list(command),
                    cwd=self.workspace,
                    stdin=subprocess.DEVNULL,
                    stdout=self._log_file,
                    stderr=subprocess.STDOUT,
                    shell=False,
                )
            except OSError:
                self._process = None
                self._log_file.close()
                self._log_file = None
                raise

    def stop(self, timeout: float = 3.0) -> ProcessResult | None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        with self._lock:
            process = self._process
            if process is None:
                return None
            self._stop_requested = True
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=timeout)
            result = ProcessResult(returncode=process.returncode, crashed=False)
            self._process = None
            return result

    def poll(self) -> ProcessResult | None:
        with self._lock:
            process = self._process
            if process is None:
                return None
            returncode = process.poll()
            if returncode is None:
                return None
            self._process = None
            return ProcessResult(
                returncode=returncode,
                crashed=returncode != 0 and not self._stop_requested,
            )

    def read_available(self) -> str:
        with self._lock:
            if self._log_file is None:
                return ""
            self._log_file.flush()
            self._log_file.seek(self._log_offset)
            data = self._log_file.read()
            self._log_offset = self._log_file.tell()
        return data.decode("utf-8", errors="replace")

    def communicate(self, timeout: float | None = None) -> str:
        process = self._process
        if process is None:
            return self.read_available()
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return self.read_available()
        return self.read_available()
