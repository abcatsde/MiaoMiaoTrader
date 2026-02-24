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
    output = message
    output = output.replace("plan.created", "计划已创建")
    output = output.replace("plan.start", "计划开始")
    output = output.replace("plan.done", "计划完成")
    output = output.replace("plan.failed", "计划失败")
    output = output.replace("step.start:", "步骤开始:")
    output = output.replace("step.done:", "步骤完成:")
    output = output.replace("Robot loop error", "机器人循环错误")
    output = output.replace("Request failed", "请求失败")
    output = output.replace("Network error", "网络错误")
    output = output.replace("Invalid JSON", "无效 JSON")
    output = output.replace("Missing API key/secret/passphrase for signed request.", "签名请求缺少 API Key/Secret/Passphrase。")
    output = output.replace("Restart disabled", "重启已禁用")
    output = output.replace("Invalid token", "Token 无效")
    output = output.replace("WebManager Access token", "Web 管理访问 Token")
    output = output.replace("title=", "标题=")
    output = output.replace("inputs=", "输入=")
    output = output.replace("outputs=", "输出=")
    output = output.replace("observations=", "观察=")
    output = output.replace("decisions=", "决策=")
    output = output.replace("errors=", "错误=")
    output = output.replace("rationale=", "理由=")
    output = output.replace("stance=", "态度=")
    output = output.replace("Start", "启动")
    return output


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
