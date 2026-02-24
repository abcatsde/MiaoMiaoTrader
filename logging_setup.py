from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
import json


class _ColorFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        level = record.levelname
        color = self.COLORS.get(level, "")
        message = super().format(record)
        if color:
            return f"{color}{message}{self.RESET}"
        return message


def _load_log_lang() -> str:
    config_path = Path(__file__).resolve().parent / "config" / "app.json"
    if not config_path.exists():
        return "zh"
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        value = data.get("log_lang", "zh")
        return value if value in ("zh", "en") else "zh"
    except Exception:
        return "zh"


def _translate_message(message: str) -> str:
    return message


class _LangFilter(logging.Filter):
    def __init__(self, lang: str) -> None:
        super().__init__()
        self._lang = lang

    def filter(self, record: logging.LogRecord) -> bool:
        if self._lang != "zh":
            return True
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not isinstance(message, str):
            return True
        record.msg = _translate_message(message)
        record.args = ()
        return True


def setup_logging(log_path: str = "logs/app.log", level: int = logging.INFO) -> None:
    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    log_lang = _load_log_lang()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(processName)s %(name)s %(message)s"
    )

    file_handler = TimedRotatingFileHandler(
        log_file,
        when="D",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=True,
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_LangFilter(log_lang))

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_ColorFormatter(formatter._fmt))
    stream_handler.addFilter(_LangFilter(log_lang))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
