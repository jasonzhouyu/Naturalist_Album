"""把 sys.stdout / sys.stderr tee 到 relic-album.log，控制台不受影响。

每行落盘时加上毫秒级时间戳，方便事后回看。日志超过 10MB 时启动时截掉前一半。
设计目标：纯 import 副作用，main.py 顶部一行 import 即可启用。
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "relic-album.log"
MAX_LOG_BYTES = 10 * 1024 * 1024
TZ = timezone(timedelta(hours=8))


class _Tee:
    """同时写控制台和日志文件；只在日志文件那一份每行加时间戳。"""

    def __init__(self, console, file):
        self.console = console
        self.file = file
        self._buf = ""

    def write(self, s: str) -> int:
        try:
            self.console.write(s)
            self.console.flush()
        except Exception:
            pass
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            ts = datetime.now(TZ).strftime("%H:%M:%S.%f")[:-3]
            try:
                self.file.write(f"[{ts}] {line}\n")
                self.file.flush()
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        try:
            self.console.flush()
        except Exception:
            pass
        if self._buf:
            ts = datetime.now(TZ).strftime("%H:%M:%S.%f")[:-3]
            try:
                self.file.write(f"[{ts}] {self._buf}")
                self.file.flush()
            except Exception:
                pass
            self._buf = ""

    # 一些库会探测这两个方法
    def fileno(self) -> int:
        return self.console.fileno()

    def isatty(self) -> bool:
        try:
            return self.console.isatty()
        except Exception:
            return False


def _trim_if_oversized() -> None:
    if not LOG_FILE.exists():
        return
    if LOG_FILE.stat().st_size <= MAX_LOG_BYTES:
        return
    try:
        data = LOG_FILE.read_bytes()
        keep = data[-(MAX_LOG_BYTES // 2):]
        # 从下一个换行处对齐
        nl = keep.find(b"\n")
        if 0 <= nl < 4096:
            keep = keep[nl + 1:]
        LOG_FILE.write_bytes(b"--- log truncated ---\n" + keep)
    except OSError:
        pass


def setup() -> Path:
    _trim_if_oversized()
    fp = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    banner = f"\n=== {datetime.now(TZ).isoformat()} startup pid={__import__('os').getpid()} ===\n"
    fp.write(banner)
    fp.flush()
    sys.stdout = _Tee(sys.__stdout__, fp)
    sys.stderr = _Tee(sys.__stderr__, fp)
    return LOG_FILE


# 纯 import 副作用启用
LOG_PATH = setup()
