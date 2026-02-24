from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import sys

import json
from pathlib import Path
import uvicorn

from robot_runner import run_robot
from logging_setup import setup_logging


setup_logging()


def _run_web() -> None:
    config_path = Path(__file__).resolve().parent / "config" / "app.json"
    port = 8088
    if config_path.exists():
        try:
            port = int(json.loads(config_path.read_text(encoding="utf-8")).get("web_port", 8088))
        except Exception:
            port = 8088
    uvicorn.run("WebManager.app:app", host="0.0.0.0", port=port, log_level="info")


def main() -> None:
    web = mp.Process(target=_run_web, name="web-manager")
    bot = mp.Process(target=run_robot, name="robot-runner")

    web.start()
    bot.start()

    def _shutdown(_signum: int, _frame) -> None:
        for proc in (web, bot):
            if proc.is_alive():
                proc.terminate()
        for proc in (web, bot):
            proc.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    web.join()
    bot.join()


if __name__ == "__main__":
    main()
