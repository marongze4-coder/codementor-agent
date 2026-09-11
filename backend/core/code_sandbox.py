from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from pydantic import BaseModel

from backend.config import get_settings


class SandboxTestCase(BaseModel):
    id: str
    name: str
    input_data: str = ""
    expected_output: str
    timeout_seconds: int = 3
    weight: int = 1
    is_hidden: bool = True


class SandboxResult(BaseModel):
    test_case_id: str
    name: str
    passed: bool
    exit_code: int | None = None
    duration_ms: int = 0
    stdout: str = ""
    stderr: str = ""
    error_type: str | None = None


async def _run_command(*args: str, input_data: bytes = b"", timeout: int = 5):
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(input_data), timeout=timeout)
        return process.returncode, stdout, stderr
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise


async def sandbox_status() -> tuple[bool, str]:
    settings = get_settings()
    if not settings.sandbox_enabled:
        return False, "sandbox_disabled"
    docker = shutil.which("docker")
    if not docker:
        return False, "docker_not_found"
    try:
        code, _stdout, _stderr = await _run_command(
            docker,
            "image",
            "inspect",
            settings.sandbox_image,
            timeout=3,
        )
    except (asyncio.TimeoutError, OSError):
        return False, "docker_unavailable"
    if code != 0:
        return False, "sandbox_image_missing"
    return True, "ready"


async def run_python_test(source_path: str, case: SandboxTestCase) -> SandboxResult:
    """Run one Python submission in an isolated, network-disabled Docker container."""
    settings = get_settings()
    ready, reason = await sandbox_status()
    if not ready:
        return SandboxResult(
            test_case_id=case.id,
            name=case.name,
            passed=False,
            error_type=reason,
            stderr="代码沙箱未就绪，本用例需要教师复核。",
        )

    source = Path(source_path).resolve()
    if not source.is_file():
        return SandboxResult(
            test_case_id=case.id,
            name=case.name,
            passed=False,
            error_type="source_missing",
            stderr="提交文件不存在。",
        )

    docker = shutil.which("docker") or "docker"
    mount = f"{source.parent}:/workspace:ro"
    command = [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--memory",
        f"{settings.sandbox_memory_mb}m",
        "--cpus",
        str(settings.sandbox_cpus),
        "--pids-limit",
        "64",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "-i",
        "-v",
        mount,
        "-w",
        "/workspace",
        settings.sandbox_image,
        "python",
        f"/workspace/{source.name}",
    ]
    started = time.perf_counter()
    timeout = max(1, min(case.timeout_seconds, settings.sandbox_timeout_seconds))
    try:
        code, stdout_bytes, stderr_bytes = await _run_command(
            *command,
            input_data=case.input_data.encode("utf-8"),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return SandboxResult(
            test_case_id=case.id,
            name=case.name,
            passed=False,
            duration_ms=round((time.perf_counter() - started) * 1000),
            error_type="timeout",
            stderr=f"运行超过 {timeout} 秒。",
        )

    stdout = stdout_bytes.decode("utf-8", errors="replace")[-12000:]
    stderr = stderr_bytes.decode("utf-8", errors="replace")[-12000:]
    actual = stdout.strip().replace("\r\n", "\n")
    expected = case.expected_output.strip().replace("\r\n", "\n")
    return SandboxResult(
        test_case_id=case.id,
        name=case.name,
        passed=code == 0 and actual == expected,
        exit_code=code,
        duration_ms=round((time.perf_counter() - started) * 1000),
        stdout=stdout,
        stderr=stderr,
        error_type=None if code == 0 else "runtime_error",
    )
