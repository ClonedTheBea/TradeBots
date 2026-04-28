"""FastAPI localhost dashboard for TradeBotsAI.

The dashboard is intentionally local-first and paper-only. It wraps existing
CLI functions and captures their console-style output for display in the UI.
"""

from __future__ import annotations

from collections import deque
from contextlib import redirect_stdout
from dataclasses import asdict, dataclass
from datetime import datetime
import io
import os
from pathlib import Path
import subprocess
import sys
import threading
from typing import Any, Callable
from uuid import uuid4

from app.risk import RiskSettings, total_exposure_value
from storage.sqlite_store import SQLiteStore


LOG_LIMIT = 500
DEFAULT_DB_PATH = "tradebots_ai.sqlite"
COMMAND_OUTPUT_LOCK = threading.Lock()


@dataclass(frozen=True)
class SchedulerSettings:
    symbols: str = "AAPL,MSFT,BB"
    interval_minutes: float = 15.0
    confidence_threshold: float = 0.65
    market_hours_only: bool = False
    confirm_paper: bool = False
    top_only: bool = False
    qty: float = 1.0
    timeframe: str = "1Day"
    lookback: int = 180


@dataclass(frozen=True)
class ValidationSettings:
    symbol: str
    timeframe: str = "1Day"
    lookback: int = 365
    trials: int = 100
    train_ratio: float = 0.7


class WebLogBuffer:
    def __init__(self, limit: int = LOG_LIMIT) -> None:
        self._lines: deque[str] = deque(maxlen=limit)
        self._lock = threading.Lock()

    def append(self, message: str) -> None:
        timestamp = datetime.now().isoformat(timespec="seconds")
        safe_message = _redact_secrets(message.rstrip())
        with self._lock:
            for line in safe_message.splitlines() or [""]:
                self._lines.append(f"[{timestamp}] {line}")

    def lines(self) -> list[str]:
        with self._lock:
            return list(self._lines)


class DashboardState:
    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.logs = WebLogBuffer()
        self._lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._scheduler_thread: threading.Thread | None = None
        self.scheduler_settings = SchedulerSettings()
        self.jobs: dict[str, dict[str, Any]] = {}

    def scheduler_running(self) -> bool:
        thread = self._scheduler_thread
        return thread is not None and thread.is_alive()

    def start_scheduler(self, settings: SchedulerSettings) -> tuple[bool, str]:
        with self._lock:
            if self.scheduler_running():
                return False, "Scheduler is already running."
            self.scheduler_settings = settings
            self._stop_event.clear()
            self._scheduler_thread = threading.Thread(
                target=self._scheduler_loop,
                args=(settings,),
                name="tradebots-web-scheduler",
                daemon=True,
            )
            self._scheduler_thread.start()
        self.logs.append("Scheduler start requested from web UI.")
        return True, "Scheduler started."

    def stop_scheduler(self) -> tuple[bool, str]:
        with self._lock:
            if not self.scheduler_running():
                self._stop_event.set()
                return False, "Scheduler is not running."
            self._stop_event.set()
        self.logs.append("Scheduler stop requested from web UI.")
        return True, "Scheduler stop requested."

    def run_one_scan(self, settings: SchedulerSettings) -> None:
        self.scheduler_settings = settings
        self.logs.append("One scan requested from web UI.")
        _capture_command_output(
            self.logs,
            "one scan",
            _run_scheduler_cycle,
            settings,
            self.db_path,
        )

    def _scheduler_loop(self, settings: SchedulerSettings) -> None:
        self.logs.append(
            "Scheduler loop started "
            f"symbols={settings.symbols} interval={settings.interval_minutes:g}m "
            f"mode={'confirmed paper' if settings.confirm_paper else 'dry run'}."
        )
        try:
            while not self._stop_event.is_set():
                _capture_command_output(
                    self.logs,
                    "scheduler cycle",
                    _run_scheduler_cycle,
                    settings,
                    self.db_path,
                )
                wait_seconds = max(settings.interval_minutes, 0.01) * 60
                if self._stop_event.wait(wait_seconds):
                    break
        finally:
            self.logs.append("Scheduler loop stopped.")

    def start_validation(self, settings: ValidationSettings) -> dict[str, Any]:
        with self._job_lock:
            if self._validation_running_locked():
                return {
                    "started": False,
                    "message": "Validation already running.",
                    "job_id": self._running_validation_id_locked(),
                }
            job_id = uuid4().hex
            job = {
                "job_id": job_id,
                "job_type": "validation",
                "status": "running",
                "started_at": datetime.now().isoformat(timespec="seconds"),
                "completed_at": None,
                "output": "",
                "recent_logs": [],
                "error": None,
                "settings": asdict(settings),
            }
            self.jobs[job_id] = job
        thread = threading.Thread(
            target=self._validation_worker,
            args=(job_id, settings),
            name=f"tradebots-validation-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return {"started": True, "job_id": job_id, "status": "running"}

    def job_statuses(self) -> list[dict[str, Any]]:
        with self._job_lock:
            return [dict(job) for job in sorted(self.jobs.values(), key=lambda item: item["started_at"], reverse=True)]

    def _validation_worker(self, job_id: str, settings: ValidationSettings) -> None:
        self._append_job_log(job_id, f"Starting validation for {settings.symbol}...")
        if self.scheduler_running():
            self._append_job_log(
                job_id,
                "Scheduler is running; validation will continue independently. Watch Alpaca rate limits.",
            )
        self._append_job_log(job_id, "Fetching candles...")
        self._append_job_log(job_id, f"Running Optuna trials: {settings.trials}")
        try:
            exit_code = _run_validation_command(
                settings,
                self.db_path,
                lambda line: self._append_job_log(job_id, line),
            )
            params = _get_params(self.db_path, settings.symbol, settings.timeframe)
            status = params.get("promotion_status") or "unknown"
            reasons = params.get("rejection_reasons") or []
            self._append_job_log(job_id, f"Promotion result: {status}")
            if reasons:
                self._append_job_log(job_id, "Rejection reasons: " + "; ".join(reasons))
            self._finish_job(job_id, "completed" if exit_code == 0 else "failed", None if exit_code == 0 else f"exit code {exit_code}")
        except Exception as exc:
            self._append_job_log(job_id, f"Validation failed: {exc}")
            self._finish_job(job_id, "failed", str(exc))

    def _append_job_log(self, job_id: str, message: str) -> None:
        self.logs.append(message)
        with self._job_lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            safe_message = _redact_secrets(message.rstrip())
            recent_logs = list(job.get("recent_logs") or [])
            for line in safe_message.splitlines() or [""]:
                recent_logs.append(line)
            job["recent_logs"] = recent_logs[-100:]
            job["output"] = "\n".join(recent_logs)

    def _finish_job(self, job_id: str, status: str, error: str | None) -> None:
        with self._job_lock:
            job = self.jobs.get(job_id)
            if job is None:
                return
            job["status"] = status
            job["completed_at"] = datetime.now().isoformat(timespec="seconds")
            job["error"] = error
        self.logs.append(f"Validation job {job_id} {status}.")

    def _validation_running_locked(self) -> bool:
        return any(job["job_type"] == "validation" and job["status"] == "running" for job in self.jobs.values())

    def _running_validation_id_locked(self) -> str | None:
        for job in self.jobs.values():
            if job["job_type"] == "validation" and job["status"] == "running":
                return str(job["job_id"])
        return None


def create_app(db_path: str = DEFAULT_DB_PATH):
    try:
        from fastapi import FastAPI, Request
        from fastapi.responses import HTMLResponse
        from fastapi.staticfiles import StaticFiles
        from fastapi.templating import Jinja2Templates
    except ImportError as exc:  # pragma: no cover - exercised by CLI guard.
        raise RuntimeError("FastAPI dashboard dependencies are not installed.") from exc

    globals()["Request"] = Request
    state = DashboardState(db_path=db_path)
    app = FastAPI(title="TradeBotsAI Dashboard")
    app.state.dashboard = state

    root = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=root / "static"), name="static")
    templates = Jinja2Templates(directory=str(root / "templates"))

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"settings": state.scheduler_settings},
        )

    @app.get("/api/status")
    def api_status() -> dict[str, Any]:
        return build_status(state)

    @app.get("/api/logs")
    def api_logs() -> dict[str, list[str]]:
        return {"logs": state.logs.lines()}

    @app.get("/api/jobs")
    def api_jobs() -> dict[str, list[dict[str, Any]]]:
        return {"jobs": state.job_statuses()}

    @app.post("/api/scheduler/start")
    async def api_start_scheduler(request: Request) -> dict[str, Any]:
        settings = _settings_from_payload(await request.json())
        started, message = state.start_scheduler(settings)
        return {"ok": started, "message": message, "running": state.scheduler_running()}

    @app.post("/api/scheduler/stop")
    def api_stop_scheduler() -> dict[str, Any]:
        stopped, message = state.stop_scheduler()
        return {"ok": stopped, "message": message, "running": state.scheduler_running()}

    @app.post("/api/scan")
    async def api_scan(request: Request) -> dict[str, Any]:
        settings = _settings_from_payload(await request.json())
        thread = threading.Thread(
            target=state.run_one_scan,
            args=(settings,),
            name=f"tradebots-web-scan-{uuid4().hex[:8]}",
            daemon=True,
        )
        thread.start()
        return {"ok": True, "message": "One scan started."}

    @app.post("/api/validate")
    async def api_validate(request: Request) -> dict[str, Any]:
        payload = await request.json()
        symbol = str(payload.get("symbol") or "").strip().upper()
        if not symbol:
            return {"ok": False, "message": "Symbol is required."}
        result = state.start_validation(
            ValidationSettings(
                symbol=symbol,
                timeframe=str(payload.get("timeframe") or "1Day"),
                lookback=int(payload.get("lookback") or 365),
                trials=int(payload.get("trials") or 100),
                train_ratio=float(payload.get("train_ratio") or 0.7),
            )
        )
        return result

    @app.get("/api/parameters")
    def api_parameters(symbol: str, timeframe: str = "1Day") -> dict[str, Any]:
        return _get_params(state.db_path, symbol, timeframe)

    @app.get("/api/reports")
    def api_reports(last: int = 20) -> dict[str, Any]:
        return build_reports(state.db_path, last)

    return app


def _run_validation_command(
    settings: ValidationSettings,
    db_path: str,
    on_line: Callable[[str], None],
) -> int:
    command = [
        sys.executable,
        "-m",
        "app.main",
        "validate-symbol",
        "--symbol",
        settings.symbol,
        "--timeframe",
        settings.timeframe,
        "--lookback",
        str(settings.lookback),
        "--train-ratio",
        str(settings.train_ratio),
        "--trials",
        str(settings.trials),
        "--db",
        db_path,
    ]
    project_root = Path(__file__).resolve().parents[1]
    process = subprocess.Popen(
        command,
        cwd=str(project_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert process.stdout is not None
    for line in process.stdout:
        stripped = line.rstrip()
        if stripped:
            on_line(stripped)
    return process.wait()


def build_status(state: DashboardState) -> dict[str, Any]:
    risk_settings = RiskSettings()
    with SQLiteStore(state.db_path) as store:
        store.initialize()
        latest_signals = _latest_signals(store)
        open_positions = store.get_open_positions()
        daily_pnl = store.get_daily_realized_pnl()
        cooldown_symbols = sorted(store.get_symbols_in_cooldown(risk_settings.cooldown_minutes_after_loss))
    exposure_value = total_exposure_value(open_positions)
    exposure_pct = (exposure_value / max(risk_settings.account_value, 1.0)) * 100
    return {
        "scheduler": {
            "running": state.scheduler_running(),
            "settings": asdict(state.scheduler_settings),
        },
        "latest_signals": latest_signals,
        "open_positions": open_positions,
        "risk": {
            "open_position_count": len(open_positions),
            "exposure_value": round(exposure_value, 2),
            "exposure_pct": round(exposure_pct, 2),
            "daily_realized_pnl": round(daily_pnl, 2),
            "cooldown_symbols": cooldown_symbols,
        },
    }


def build_reports(db_path: str, last: int = 20) -> dict[str, Any]:
    from app.main import _build_performance_report

    risk_settings = RiskSettings()
    with SQLiteStore(db_path) as store:
        store.initialize()
        trades = store.get_completed_trades(limit=last)
        open_positions = store.get_open_positions()
        daily_pnl = store.get_daily_realized_pnl()
        cooldown_symbols = sorted(store.get_symbols_in_cooldown(risk_settings.cooldown_minutes_after_loss))
    exposure_value = total_exposure_value(open_positions)
    exposure_pct = (exposure_value / max(risk_settings.account_value, 1.0)) * 100
    return {
        "performance_report": _build_performance_report(trades),
        "risk_status": {
            "open_positions": open_positions,
            "exposure_value": round(exposure_value, 2),
            "exposure_pct": round(exposure_pct, 2),
            "daily_realized_pnl": round(daily_pnl, 2),
            "cooldown_symbols": cooldown_symbols,
        },
        "recent_completed_trades": trades,
    }


def _run_scheduler_cycle(settings: SchedulerSettings, db_path: str) -> int:
    from app.main import run_scheduler

    return run_scheduler(
        settings.symbols,
        settings.interval_minutes,
        settings.confidence_threshold,
        settings.qty,
        settings.timeframe,
        settings.lookback,
        settings.confirm_paper,
        settings.top_only,
        settings.market_hours_only,
        RiskSettings(),
        db_path,
        max_cycles=1,
    )


def _capture_command_output(
    logs: WebLogBuffer,
    label: str,
    func: Callable[..., int],
    *args: Any,
    **kwargs: Any,
) -> tuple[int, str]:
    output = io.StringIO()
    try:
        with COMMAND_OUTPUT_LOCK:
            with redirect_stdout(output):
                exit_code = func(*args, **kwargs)
    except Exception as exc:
        exit_code = 1
        print(f"{label} failed: {exc}", file=output)
    text = output.getvalue().strip()
    if text:
        logs.append(f"{label} output:")
        logs.append(text)
    logs.append(f"{label} finished with exit code {exit_code}.")
    return exit_code, text


def _settings_from_payload(payload: dict[str, Any]) -> SchedulerSettings:
    return SchedulerSettings(
        symbols=str(payload.get("symbols") or "AAPL,MSFT,BB"),
        interval_minutes=float(payload.get("interval_minutes") or 15),
        confidence_threshold=float(payload.get("confidence_threshold") or 0.65),
        market_hours_only=bool(payload.get("market_hours_only")),
        confirm_paper=bool(payload.get("confirm_paper")),
        top_only=bool(payload.get("top_only")),
        qty=float(payload.get("qty") or 1),
        timeframe=str(payload.get("timeframe") or "1Day"),
        lookback=int(payload.get("lookback") or 180),
    )


def _latest_signals(store: SQLiteStore, limit: int = 10) -> list[dict[str, Any]]:
    rows = store._conn().execute(
        """
        SELECT symbol, timestamp, action, confidence, score, close_price, reason, created_at
        FROM signals
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [
        {
            "symbol": row[0],
            "timestamp": row[1],
            "action": row[2],
            "confidence": row[3],
            "score": row[4],
            "close_price": row[5],
            "reason": row[6],
            "created_at": row[7],
        }
        for row in rows
    ]


def _get_params(db_path: str, symbol: str, timeframe: str) -> dict[str, Any]:
    normalized_symbol = str(symbol or "").strip().upper()
    with SQLiteStore(db_path) as store:
        store.initialize()
        active = store.get_active_strategy_parameters(normalized_symbol, timeframe) if normalized_symbol else None
        latest = store.get_latest_strategy_parameters(normalized_symbol, timeframe) if normalized_symbol else None
    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "active": active,
        "latest_candidate": latest,
        "promotion_status": (latest or {}).get("promotion_status"),
        "rejection_reasons": (latest or {}).get("rejection_reasons") or [],
    }


def _redact_secrets(message: str) -> str:
    redacted = message
    secret_keys = (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "MARKETSTACK_API_KEY",
    )
    for key in secret_keys:
        value = os.getenv(key) or _env_file_value(key)
        if value:
            redacted = redacted.replace(value, "[redacted]")
    return redacted


def _env_file_value(key: str, env_path: str = ".env") -> str | None:
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                env_key, value = stripped.split("=", 1)
                if env_key.strip() == key:
                    return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None
