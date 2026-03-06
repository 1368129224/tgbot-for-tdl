import asyncio
import re
from dataclasses import dataclass
from typing import Optional, AsyncIterator

from .constants import ANSI_ESCAPE_RE


@dataclass
class DownloadTask:
    link: str
    tag: str
    path: str
    proxy_url: Optional[str]


def build_tdl_command(tdl_path: str, task: DownloadTask, extra_args: str = "") -> str:
    # Build command while staying backward compatible with previous behavior.
    # Only pass --proxy when proxy is configured.
    proxy_part = f" --proxy {task.proxy_url}" if task.proxy_url else ""
    extra = f" {extra_args.strip()}" if extra_args and extra_args.strip() else ""
    # reconnect-timeout 0 preserved
    return (
        f"{tdl_path} --debug dl -u {task.link}"
        f"{proxy_part} -d {task.path} --reconnect-timeout 0{extra}"
    )


async def stream_lines(proc: asyncio.subprocess.Process) -> AsyncIterator[str]:
    if not proc.stdout:
        return

    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        yield line.decode(errors="replace")


def parse_progress(line: str) -> Optional[tuple[str, str]]:
    """Parse a tdl progress line.

    Returns (process, speed) if line contains progress, otherwise None.
    """
    # Strip ANSI
    line = re.sub(ANSI_ESCAPE_RE, "", line).strip()
    if not line:
        return None

    # Skip non-progress headings
    if line.startswith("CPU") or line.startswith("[") or line.startswith("All"):
        return None

    if "..." not in line:
        return None

    try:
        # Original code assumed: <name>... <percent> ... ;<speed>]
        parts = line.split("...")
        if len(parts) < 2:
            return None
        process = parts[1].split()[0]
        speed = parts[-1].split(";")[-1].strip().rstrip("]")
        return process, speed
    except Exception:
        return None


def parse_done(line: str) -> Optional[str]:
    line = re.sub(ANSI_ESCAPE_RE, "", line)
    if "done!" not in line:
        return None
    try:
        return line.split("...")[-1].strip()
    except Exception:
        return "done!"


def summarize_error(lines: list[str]) -> str:
    """Summarize probable error cause from tdl output."""
    if not lines:
        return "no output"

    # Prefer last non-empty lines
    tail = [ln.strip() for ln in lines if ln and ln.strip()]
    tail = tail[-10:]

    # Heuristics
    for ln in reversed(tail):
        low = ln.lower()
        if "error" in low or "fatal" in low or "panic" in low:
            return ln[:300]
        if "unauthorized" in low or "forbidden" in low:
            return ln[:300]
        if "timeout" in low:
            return ln[:300]
        if "no such file" in low or "not found" in low:
            return ln[:300]

    return tail[-1][:300] if tail else "unknown error"


async def run_tdl(cmd: str) -> tuple[int, list[str]]:
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    lines: list[str] = []
    async for line in stream_lines(proc):
        lines.append(line)

    rc = await proc.wait()
    return rc, lines
