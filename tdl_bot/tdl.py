"""与 tdl 命令行交互的封装。

这里的目标是：
- 以“结构化配置 -> argv 参数列表”的方式生成 tdl 命令
- 解析 tdl 输出（进度/完成/错误摘要）并提供给上层 bot 使用

注意：
- tdl 的输出格式可能随着版本变化而变化，因此解析逻辑应尽量“宽松 + 容错”。
"""

import re
from dataclasses import dataclass
from typing import Optional

from .constants import ANSI_ESCAPE_RE


@dataclass
class DownloadTask:
    """单个下载任务（bot 侧抽象）。"""

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
    """构建 `tdl download` 的 argv 参数列表。

    约定：
    - 默认值尽量与 tdl 的默认保持一致
    - 只有当配置显式开启/设置时，才添加对应参数

    重要：
    - 返回的是 argv 列表，推荐配合 `create_subprocess_exec` 使用，避免 shell 转义问题。
    """

    args: list[str] = []

    # ===== 全局 flags（作用于所有子命令） =====
    if debug:
        args.append("--debug")

    # delay/limit/threads：tdl 有默认值，如果与默认一致可以不传
    if delay and delay != "0s":
        args += ["--delay", str(delay)]

    # tdl 默认 limit=2；如果配置为 2，可不传（但为了可读性也可以选择始终传）
    if limit and int(limit) != 2:
        args += ["--limit", str(int(limit))]

    # tdl 默认 threads=4
    if threads and int(threads) != 4:
        args += ["--threads", str(int(threads))]

    # proxy：只有配置了才传
    if proxy_url:
        args += ["--proxy", str(proxy_url)]

    # reconnect-timeout：本项目历史行为为 0（无限重连退避），与 tdl 默认不同
    # 为保持兼容，这里始终传（由配置控制）
    if reconnect_timeout is not None:
        args += ["--reconnect-timeout", str(reconnect_timeout)]

    # ===== 子命令 =====
    args.append("download")

    # ===== download 子命令 flags =====
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

    # include/exclude：tdl 支持逗号分隔
    if include:
        args += ["--include", ",".join(include)]
    if exclude:
        args += ["--exclude", ",".join(exclude)]

    if template:
        args += ["--template", template]

    # serve：目前仅预留，占位
    if serve:
        args.append("--serve")

    return args


def parse_progress(line: str) -> Optional[tuple[str, str]]:
    """从 tdl 的输出行中解析进度信息。

    返回：
    - (progress, speed) 或 None

    说明：
    - tdl 输出可能包含 ANSI 颜色码，需要先清理
    - 这里沿用历史解析策略：从包含 "..." 的行里抽取 percent 与速度
    """

    # 去掉 ANSI 控制符
    line = re.sub(ANSI_ESCAPE_RE, "", line).strip()
    if not line:
        return None

    # 跳过一些非进度行
    if line.startswith("CPU") or line.startswith("[") or line.startswith("All"):
        return None

    if "..." not in line:
        return None

    try:
        parts = line.split("...")
        if len(parts) < 2:
            return None
        process = parts[1].split()[0]
        speed = parts[-1].split(";")[-1].strip().rstrip("]")
        return process, speed
    except Exception:
        return None


def parse_done(line: str) -> Optional[str]:
    """判断一行输出是否表示下载完成，并提取完成信息。"""
    line = re.sub(ANSI_ESCAPE_RE, "", line)
    if "done!" not in line:
        return None
    try:
        return line.split("...")[-1].strip()
    except Exception:
        return "done!"


def summarize_error(lines: list[str]) -> str:
    """从 tdl 的输出中做一个“尽量可读”的错误摘要。

    目的：
    - bot 在下载失败时，把“最可能的原因”回传给用户

    说明：
    - 这里只做启发式规则；不要追求 100% 精确。
    """

    if not lines:
        return "no output"

    # 取最后若干行非空输出
    tail = [ln.strip() for ln in lines if ln and ln.strip()]
    tail = tail[-10:]

    # 简单关键字匹配（从后往前找最接近错误原因的一行）
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
