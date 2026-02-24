from __future__ import annotations

import logging
import multiprocessing as mp
import signal
import sys
import time

import json
from pathlib import Path
import uvicorn

from robot_runner import run_robot
from logging_setup import setup_logging


setup_logging()
logger = logging.getLogger(__name__)


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
    stop = False
    restart_signal = Path(__file__).resolve().parent / "config" / "restart.signal"

    def _shutdown(_signum: int, _frame) -> None:
        nonlocal stop
        stop = True
        logger.info("==========")
        logger.info("收到退出信号，准备关闭所有进程")
        logger.info("==========")

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while not stop:
        logger.info("==========")
        logger.info("启动进程: web-manager & robot-runner")
        logger.info("==========")
        web = mp.Process(target=_run_web, name="web-manager")
        bot = mp.Process(target=run_robot, name="robot-runner")

        web.start()
        bot.start()

        while not stop:
            if restart_signal.exists():
                try:
                    restart_signal.unlink()
                except Exception:
                    pass
                logger.info("==========")
                logger.info("检测到重启请求，准备重启进程")
                logger.info("==========")
                break
            if not web.is_alive() or not bot.is_alive():
                logger.info("==========")
                logger.info("子进程异常退出，准备重启")
                logger.info("==========")
                break
            time.sleep(1)

        for proc in (web, bot):
            if proc.is_alive():
                proc.terminate()
        for proc in (web, bot):
            proc.join(timeout=5)

        if stop:
            break


if __name__ == "__main__":
    main()
