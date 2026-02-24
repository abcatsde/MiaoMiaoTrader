from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from Monitoring import MonitoringClient
import logging
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
CONFIG_DIR = ROOT_DIR / "config"
APP_CONFIG_PATH = CONFIG_DIR / "app.json"
LLM_CONFIG_PATH = CONFIG_DIR / "llm.json"
OKX_CONFIG_PATH = CONFIG_DIR / "okx.json"
TOKEN_PATH = CONFIG_DIR / "web_token.txt"
RESTART_SIGNAL_PATH = CONFIG_DIR / "restart.signal"


class LLMProviderItem(BaseModel):
    name: str
    endpoint: str | None = None
    api_key: str | None = None
    model: str | None = None
    enabled: bool = True
    weight: int = 1


class TradingPreferences(BaseModel):
    timeframe: str = "15m"
    max_pairs: int = 2
    max_timeframes: int = 2
    margin_mode: str = "isolated"  # isolated or cross
    universe: dict[str, bool] = Field(
        default_factory=lambda: {"mainstream": True, "alt": False}
    )
    horizon: dict[str, bool] = Field(
        default_factory=lambda: {"scalp": False, "intraday": True, "swing": False}
    )
    market: dict[str, bool] = Field(
        default_factory=lambda: {"spot": True, "derivatives": False}
    )


class OKXConfigModel(BaseModel):
    api_key: str | None = None
    api_secret: str | None = None
    passphrase: str | None = None
    base_url: str = "https://www.okx.com"
    trade_mode: str = "real"  # real or demo
    we_enabled: bool = False
    ws_enabled: bool | None = None
    ws_url: str = "wss://ws.okx.com:8443/ws/v5/business"
    ws_channels: list[str] = Field(default_factory=lambda: ["deposit-info", "withdrawal-info"])


class AppConfig(BaseModel):
    llm_providers: List[LLMProviderItem] = Field(default_factory=list)
    log_llm_provider: LLMProviderItem | None = None
    llm_timeout_sec: int = 30
    trading_preferences: TradingPreferences = Field(default_factory=TradingPreferences)
    okx: OKXConfigModel = Field(default_factory=OKXConfigModel)
    task_goal: str | None = None
    task_context: str | None = None
    loop_interval_sec: int = 60
    web_port: int = 8088
    log_lang: str = "zh"


class UiConfig(BaseModel):
    log_lang: str = "zh"


@dataclass
class TokenState:
    token: str


app = FastAPI(title="MiaoMiaoTrader Web Manager")
CONFIG_DIR.mkdir(parents=True, exist_ok=True)
if TOKEN_PATH.exists():
    TOKEN_STATE = TokenState(token=TOKEN_PATH.read_text(encoding="utf-8").strip())
else:
    token = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(token, encoding="utf-8")
    TOKEN_STATE = TokenState(token=token)
logger = logging.getLogger(__name__)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "templates")), name="static")


@app.on_event("startup")
def _print_token() -> None:
    logger.info("==========================================")
    logger.info("WebManager Access token: %s", TOKEN_STATE.token)
    logger.info("==========================================")


def _load_config() -> AppConfig:
    app_data = {}
    llm_data = {}
    okx_data = {}
    if APP_CONFIG_PATH.exists():
        app_data = json.loads(APP_CONFIG_PATH.read_text(encoding="utf-8"))
    if LLM_CONFIG_PATH.exists():
        llm_data = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    if OKX_CONFIG_PATH.exists():
        okx_data = json.loads(OKX_CONFIG_PATH.read_text(encoding="utf-8"))

    data = {
        **app_data,
        "llm_providers": llm_data.get("llm_providers", app_data.get("llm_providers", [])),
        "log_llm_provider": llm_data.get("log_llm_provider", app_data.get("log_llm_provider")),
        "okx": okx_data.get("okx", app_data.get("okx", {})),
    }
    return AppConfig.model_validate(data)


def _save_config(config: AppConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    APP_CONFIG_PATH.write_text(
        json.dumps(
            {
                "trading_preferences": config.trading_preferences.model_dump(),
                "task_goal": config.task_goal,
                "task_context": config.task_context,
                "loop_interval_sec": config.loop_interval_sec,
                "llm_timeout_sec": config.llm_timeout_sec,
                "log_lang": config.log_lang,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    LLM_CONFIG_PATH.write_text(
        json.dumps(
            {
                "llm_providers": [p.model_dump() for p in config.llm_providers],
                "log_llm_provider": config.log_llm_provider.model_dump() if config.log_llm_provider else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    OKX_CONFIG_PATH.write_text(
        json.dumps({"okx": config.okx.model_dump()}, indent=2),
        encoding="utf-8",
    )


def _require_token(x_access_token: str | None) -> None:
    if not x_access_token or x_access_token != TOKEN_STATE.token:
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return FileResponse(str(BASE_DIR / "templates" / "index.html"))


@app.get("/stats", response_class=HTMLResponse)
def stats_page() -> str:
    return FileResponse(str(BASE_DIR / "templates" / "stats.html"))


@app.get("/llm", response_class=HTMLResponse)
def llm_page() -> str:
    return FileResponse(str(BASE_DIR / "templates" / "llm.html"))


@app.get("/advanced", response_class=HTMLResponse)
def advanced_page() -> str:
    return FileResponse(str(BASE_DIR / "templates" / "advanced.html"))


@app.get("/api/config")
def get_config(x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    config = _load_config()
    return JSONResponse(content=config.model_dump())


@app.get("/api/ui")
def get_ui_config(x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    config = _load_config()
    return JSONResponse(content=UiConfig(log_lang=config.log_lang).model_dump())


@app.post("/api/ui")
def set_ui_config(payload: Dict[str, Any], x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    ui = UiConfig.model_validate(payload)
    config = _load_config()
    config.log_lang = ui.log_lang
    _save_config(config)
    return JSONResponse(content={"ok": True})


@app.post("/api/config")
def set_config(payload: Dict[str, Any], x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    config = AppConfig.model_validate(payload)
    _save_config(config)
    return JSONResponse(content={"ok": True})


@app.post("/api/restart")
def restart_app(x_access_token: str | None = Header(default=None)) -> JSONResponse:
  _require_token(x_access_token)
  if os.environ.get("WEBMANAGER_ALLOW_RESTART", "1") != "1":
    raise HTTPException(status_code=403, detail="Restart disabled")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    RESTART_SIGNAL_PATH.write_text("restart", encoding="utf-8")
    return JSONResponse(content={"ok": True, "message": "重启已请求，服务将由主进程重启"})


@app.get("/api/health")
def health() -> JSONResponse:
    return JSONResponse(content={"ok": True})


@app.get("/api/stats")
def stats(x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    monitoring = MonitoringClient()
    return JSONResponse(content=monitoring.get_stats())


@app.get("/api/events")
def events(limit: int = 50, x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    monitoring = MonitoringClient()
    return JSONResponse(content={"events": monitoring.get_recent_events(limit=limit)})


@app.get("/api/alerts")
def alerts(limit: int = 20, x_access_token: str | None = Header(default=None)) -> JSONResponse:
    _require_token(x_access_token)
    monitoring = MonitoringClient()
    return JSONResponse(content={"alerts": monitoring.get_recent_alerts(limit=limit)})
