import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file()


@dataclass(frozen=True)
class Settings:
    app_name: str = "FastAPI Backend"
    app_env: str = os.getenv("APP_ENV", "development").strip().lower()
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./app.db").strip()
    admin_username: str = os.getenv("ADMIN_USERNAME", "")
    admin_password_hash: str = os.getenv("ADMIN_PASSWORD_HASH", "")
    session_secret: str = os.getenv("SESSION_SECRET", "")
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
    login_max_attempts: int = int(os.getenv("LOGIN_MAX_ATTEMPTS", "5"))
    login_window_seconds: int = int(os.getenv("LOGIN_WINDOW_SECONDS", "900"))
    login_block_seconds: int = int(os.getenv("LOGIN_BLOCK_SECONDS", "900"))
    frontend_url: str = os.getenv("FRONTEND_URL", "http://127.0.0.1:3000")
    bybit_demo_base_url: str = os.getenv("BYBIT_DEMO_BASE_URL", "https://api-demo.bybit.com")
    bybit_demo_api_key: str = os.getenv("BYBIT_DEMO_API_KEY", "")
    bybit_demo_api_secret: str = os.getenv("BYBIT_DEMO_API_SECRET", "")
    bybit_live_base_url: str = os.getenv("BYBIT_LIVE_BASE_URL", "https://api.bybit.com")
    bybit_live_api_key: str = os.getenv("BYBIT_LIVE_API_KEY", "")
    bybit_live_api_secret: str = os.getenv("BYBIT_LIVE_API_SECRET", "")
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    bot_scan_interval_seconds: int = int(os.getenv("BOT_SCAN_INTERVAL_SECONDS", "30"))
    execution_taker_fee_bps: float = float(os.getenv("EXECUTION_TAKER_FEE_BPS", "5.5"))
    execution_slippage_bps: float = float(os.getenv("EXECUTION_SLIPPAGE_BPS", "2.0"))
    execution_risk_headroom_ratio: float = float(os.getenv("EXECUTION_RISK_HEADROOM_RATIO", "0.90"))
    scanner_universe_limit: int = int(
        os.getenv(
            "SCANNER_UNIVERSE_LIMIT",
            "12" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "30",
        )
    )
    intraday_trend_candle_limit: int = int(
        os.getenv(
            "INTRADAY_TREND_CANDLE_LIMIT",
            "80" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "250",
        )
    )
    intraday_setup_candle_limit: int = int(
        os.getenv(
            "INTRADAY_SETUP_CANDLE_LIMIT",
            "90" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "250",
        )
    )
    scalping_setup_candle_limit: int = int(
        os.getenv(
            "SCALPING_SETUP_CANDLE_LIMIT",
            "90" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "250",
        )
    )
    scalping_trigger_candle_limit: int = int(
        os.getenv(
            "SCALPING_TRIGGER_CANDLE_LIMIT",
            "60" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "250",
        )
    )


settings = Settings()
