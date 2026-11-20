from __future__ import annotations

import logging
import re
from pathlib import Path

_SECRET_PATTERNS = (
    re.compile(r"(?i)\bBearer\s+[0-9A-Za-z._-]+"),
    re.compile(r"ya29\.[0-9A-Za-z._-]+"),
    re.compile(r"1//[0-9A-Za-z._-]+"),
    re.compile(r"GOCSPX-[0-9A-Za-z._-]+"),
    re.compile(
        r"(?i)\b(client_secret|refresh_token|access_token|authorization)\b"
        r"(\s*[:=]\s*)([\"']?)([^\s,\"']+)([\"']?)"
    ),
)


def redact(text: str) -> str:
    result = str(text)
    for pattern in _SECRET_PATTERNS[:-1]:
        result = pattern.sub("<redacted>", result)
    result = _SECRET_PATTERNS[-1].sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>", result
    )
    return result


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def setup_logging(
    log_root: Path | str,
    channel: str,
    *,
    level: int = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    logger = logging.getLogger("uploader")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    redacting_filter = RedactingFilter()

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redacting_filter)
        logger.addHandler(console_handler)

    channel_root = Path(log_root) / channel
    channel_root.mkdir(parents=True, exist_ok=True)
    log_path = channel_root / "uploader.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(redacting_filter)
    logger.addHandler(file_handler)
    return logger
