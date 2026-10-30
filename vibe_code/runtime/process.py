from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
from threading import Lock, Thread
from typing import BinaryIO, Sequence


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    crashed: bool


class ProcessManager:
    """Manage one workspace process and drain its output before reporting exit."""

    _MAX_OUTPUT_BYTES = 5 * 1024 * 1024

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = Lock()
        self._output = bytearray()
        self._output_offset = 0
        self._reader: Thread | None = None
        self._stop_requested = False
        self._last_result: ProcessResult | None = None

    @property
    def running(self) -> bool:
        process = self._process
        return process is not None and process.poll() is None

    def _drain_output(self, stream: BinaryIO) -> None:
        try:
            while True:
                chunk = os.read(stream.fileno(), 65536)
                if not chunk:
                    break
                with self._lock:
                    self._output.extend(chunk)
                    overflow = len(self._output) - self._MAX_OUTPUT_BYTES
                    if overflow > 0:
                        del self._output[:overflow]
                        self._output_offset = max(0, self._output_offset - overflow)
        finally:
            stream.close()

    def _join_reader(self, timeout: float = 2.0) -> None:
        reader = self._reader
        if reader is not None and reader.is_alive():
            reader.join(timeout=timeout)

    def start(self, command: Sequence[str]) -> None:
        if not command:
            raise ValueError("command must not be empty")
        with self._lock:
            if self.running:
                raise RuntimeError("process is already running")
            self._output.clear()
            self._output_offset = 0
            self._last_result = None
            self._stop_requested = False
            self._reader = None
            process = subprocess.Popen(
                list(command),
                cwd=self.workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                shell=False,
            )
            if process.stdout is None:
                process.kill()
                raise RuntimeError("Could not capture preview output")
            self._process = process
            self._reader = Thread(
                target=self._drain_output,
                args=(process.stdout,),
                name="vibe-code-preview-output",
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
        self._join_reader()
        result = ProcessResult(returncode=process.returncode, crashed=False)
        with self._lock:
            if self._process is process:
                self._process = None
            self._last_result = result
        return result

    def poll(self) -> ProcessResult | None:
        with self._lock:
            process = self._process
            if process is None:
                return self._last_result
        returncode = process.poll()
        if returncode is None:
            return None
        # The direct child has exited; join the pipe reader so its final bytes
        # are in the buffer before callers observe the exit result.
        self._join_reader()
        result = ProcessResult(
            returncode=returncode,
            crashed=returncode != 0 and not self._stop_requested,
        )
        with self._lock:
            if self._process is process:
                self._process = None
            self._last_result = result
        return result

    def read_available(self) -> str:
        with self._lock:
            data = bytes(self._output[self._output_offset:])
            self._output_offset = len(self._output)
        return data.decode("utf-8", errors="replace")

    def communicate(self, timeout: float | None = None) -> str:
        with self._lock:
            process = self._process
        if process is not None:
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                pass
            else:
                self.poll()
        return self.read_available()
