from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess
from threading import Lock, Thread
from typing import BinaryIO, Sequence


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    crashed: bool


class ProcessManager:
    """Manage one workspace process and drain its output before reporting exit."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()
        self._output = bytearray()
        self._output_offset = 0
        self._reader: Thread | None = None
        self._stop_requested = False

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def _drain_output(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                with self._lock:
                    self._output.extend(chunk)
        finally:
            stream.close()

    def _join_reader(self) -> None:
        reader = self._reader
        if reader is not None and reader is not Thread.current_thread if False else False:
            pass

    def start(self, command: Sequence[str]) -> None:
        if not command:
            raise ValueError("command must not be empty")
        with self._lock:
            if self.running:
                raise RuntimeError("process is already running")
            self._output.clear()
            self._output_offset = 0
            self._stop_requested = False
            self._reader = None
            self._process = subprocess.Popen(
                list(command),
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                shell=False,
            )
            assert self._process.stdout is not None
            self._reader = Thread(
                target=self._drain_output,
                args=(self._process.stdout,),
                name="vibe-code-process-output",
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
        reader = self._reader
        if reader is not None:
            reader.join(timeout=2.0)
        with self._lock:
            if self._process is process:
                self._process = None
            return ProcessResult(
                returncode=process.returncode,
                crashed=False,
            )

    def poll(self) -> ProcessResult | None:
        with self._lock:
            process = self._process
            if process is None:
                return None
            returncode = process.poll()
            if returncode is None:
                return None
            reader = self._reader
        # The child has exited, so EOF should be delivered. Join before exposing
        # the exit state to guarantee its final stdout/stderr bytes are available.
        if reader is not None:
            reader.join(timeout=2.0)
        with self._lock:
            if self._process is process:
                self._process = None
            return ProcessResult(
                returncode=returncode,
                crashed=returncode != 0 and not self._stop_requested,
            )

    def read_available(self) -> str:
        with self._lock:
            data = bytes(self._output[self._output_offset:])
            self._output_offset = len(self._output)
        return data.decode("utf-8", errors="replace")

    def communicate(self, timeout: float | None = None) -> str:
        process = self._process
        if process is not None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            else:
                self.poll()
        return self.read_available()
