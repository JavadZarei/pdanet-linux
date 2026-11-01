"""Run external commands safely: argument arrays only, always with a timeout."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CmdResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None  # "not-found" | "permission" | "os-error"

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None

    @property
    def output(self) -> str:
        return (self.stdout + ("\n" if self.stdout and self.stderr else "") + self.stderr).strip()


def _text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else ""


def run(
    argv: Sequence[str],
    timeout: float,
    env_extra: Mapping[str, str] | None = None,
) -> CmdResult:
    """Run *argv* (never a shell string). Never raises for ordinary failures."""
    if isinstance(argv, (str, bytes)) or not argv or not all(isinstance(a, str) for a in argv):
        raise TypeError("argv must be a non-empty sequence of strings")
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CmdResult(tuple(argv), 124, _text(exc.stdout), _text(exc.stderr), timed_out=True)
    except FileNotFoundError:
        return CmdResult(tuple(argv), 127, error="not-found")
    except PermissionError:
        return CmdResult(tuple(argv), 126, error="permission")
    except OSError as exc:
        return CmdResult(tuple(argv), 126, stderr=str(exc), error="os-error")
    return CmdResult(tuple(argv), proc.returncode, proc.stdout, proc.stderr)
