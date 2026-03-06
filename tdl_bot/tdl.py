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


def build_download_args(
    *,
    task: DownloadTask,
    debug: bool,
    proxy_url: Optional[str],
    reconnect_timeout: str,
    limit: int,
    threads: int,
    delay: str,
    group: bool,
    skip_same: bool,
    rewrite_ext: bool,
    desc: bool,
    takeout: bool,
    include: list[str],
    exclude: list[str],
    template: str,
    serve: bool,
) -> list[str]:
    """Build argv for `tdl download`.

    Defaults should keep consistent with tdl defaults; we only include flags when enabled
    or when set explicitly by configuration.
    """
    args: list[str] = []

    if debug:
        args.append("--debug")

    # Global flags
    if delay and delay != "0s":
        args += ["--delay", str(delay)]
    if limit and int(limit) != 2:  # tdl default is 2
        args += ["--limit", str(int(limit))]
    if threads and int(threads) != 4:  # tdl default is 4
        args += ["--threads", str(int(threads))]

    if proxy_url:
        args += ["--proxy", str(proxy_url)]

    # keep legacy behavior default reconnect-timeout=0 unless user changes
    if reconnect_timeout is not None:
        args += ["--reconnect-timeout", str(reconnect_timeout)]

    # Subcommand
    args.append("download")

    # Download flags
    args += ["--url", task.link]
    args += ["--dir", task.path]

    if group:
        args.append("--group")
    if skip_same:
        args.append("--skip-same")
    if rewrite_ext:
        args.append("--rewrite-ext")
    if desc:
        args.append("--desc")
    if takeout:
        args.append("--takeout")

    if include:
        # tdl expects repeated flag or comma-separated; help suggests -i mp4,mp3
        args += ["--include", ",".join(include)]
    if exclude:
        args += ["--exclude", ",".join(exclude)]

    if template:
        args += ["--template", template]

    if serve:
        args.append("--serve")

    return args


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
