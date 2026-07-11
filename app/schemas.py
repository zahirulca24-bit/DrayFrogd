from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


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
