from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionVerifyResponse(BaseModel):
    authenticated: bool
    username: str


class RiskSignalRequest(BaseModel):
    symbol: str
    strategy_name: str | None = None
    strategy: str | None = None
    trade_type: str | None = None
    direction: str | None = None
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    detected_at: str | None = None
    status: str


class ExecuteSignalRequest(BaseModel):
    symbol: str
    strategy_name: str | None = None
    strategy: str | None = None
    trade_type: str | None = None
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    detected_at: str | None = None
    status: str


class PositionSizeRequest(BaseModel):
    symbol: str
    strategy_name: str | None = None
    strategy: str | None = None
    trade_type: str | None = None
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    detected_at: str | None = None
    status: str = "active"


class BotConfigRequest(BaseModel):
    execution_mode: str | None = None
    auto_trading_enabled: bool | None = None
    risk_per_trade: float | None = None
    leverage_cap: float | None = None
    exposure_cap: float | None = None
    max_open_trades: int | None = None
    max_daily_trades: int | None = None


class WatchdogConfigRequest(BaseModel):
    enabled: bool | None = None
    interval_seconds: int | None = None
    action_mode: str | None = None
    mismatch_tolerance_cycles: int | None = None
    exposure_tolerance_ratio: float | None = None
    pnl_tolerance: float | None = None


class BacktestRequest(BaseModel):
    symbol: str = "BTCUSDT"
    strategy: str = "all"
    trade_type: str = "scalping"
    candle_limit: int = 1000
    candle_offset: int = 0
    risk_amount: float | None = None
    fee_bps: float = 5.5
    min_risk_reward: float | None = None
    max_hold_candles: int | None = None
