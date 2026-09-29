from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Lock, Thread
from queue import Empty, Queue
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
        self._output: Queue[str] = Queue()
        self._reader: Thread | None = None
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
            try:
                self._stop_requested = False
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
            self._reader = Thread(
                target=self._drain_output,
                args=(self._process,),
                daemon=True,
            )
            self._reader.start()

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
            result = ProcessResult(
                returncode=process.returncode,
                crashed=False,
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
            crashed=returncode != 0 and not self._stop_requested,
        )

    def read_available(self) -> str:
        chunks: list[str] = []
        while True:
            try:
                chunks.append(self._output.get_nowait())
            except Empty:
                break
        return "".join(chunks)

    def _drain_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            self._output.put(line)

    def communicate(self, timeout: float | None = None) -> str:
        process = self._process
        if process is None or process.stdout is None:
            return ""
        try:
            output, _ = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            return ""
        return output
