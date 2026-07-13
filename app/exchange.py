import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import settings


class ExchangeError(Exception):
    pass


@dataclass
class BybitClient:
    base_url: str
    api_key: str
    api_secret: str
    mode: str = "demo"
    recv_window: str = "20000"
    timeout: int = 10

    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def get_status(self) -> dict[str, Any]:
        reachable, error = self.safe_ping()
        return {
            "mode": self.mode,
            "demo_only": self.mode == "demo",
            "base_url": self.base_url,
            "api_keys_present": self.has_credentials(),
            "reachable": reachable,
            "error": error,
        }

    def safe_ping(self) -> tuple[bool, str | None]:
        try:
            self._public_get("/v5/market/time")
            return True, None
        except ExchangeError as exc:
            return False, str(exc)

    def safe_fetch_wallet_balance(self) -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            return True, self.fetch_wallet_balance(), None
        except ExchangeError as exc:
            return False, None, str(exc)

    def safe_fetch_positions(self, category: str = "linear", settle_coin: str = "USDT") -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            return True, self.fetch_positions(category=category, settle_coin=settle_coin), None
        except ExchangeError as exc:
            return False, [], str(exc)

    def safe_fetch_open_orders(self, category: str = "linear", settle_coin: str = "USDT") -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            return True, self.fetch_open_orders(category=category, settle_coin=settle_coin), None
        except ExchangeError as exc:
            return False, [], str(exc)

    def safe_fetch_order_by_link_id(
        self,
        symbol: str,
        order_link_id: str,
        category: str = "linear",
    ) -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            return True, self.fetch_order_by_link_id(symbol=symbol, order_link_id=order_link_id, category=category), None
        except ExchangeError as exc:
            return False, None, str(exc)

    def safe_fetch_symbol_info(self, category: str = "linear", symbol: str | None = None) -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            return True, self.fetch_symbol_info(category=category, symbol=symbol), None
        except ExchangeError as exc:
            return False, [], str(exc)

    def safe_fetch_market_tickers(self, category: str = "linear") -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            return True, self.fetch_market_tickers(category=category), None
        except ExchangeError as exc:
            return False, [], str(exc)

    def safe_fetch_orderbook(self, symbol: str, category: str = "linear", limit: int = 25) -> tuple[bool, dict[str, list[dict[str, Any]]] | None, str | None]:
        try:
            return True, self.fetch_orderbook(symbol=symbol, category=category, limit=limit), None
        except ExchangeError as exc:
            return False, None, str(exc)

    def safe_fetch_recent_candles(
        self,
        symbol: str,
        interval: str,
        category: str = "linear",
        limit: int = 200,
    ) -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            return True, self.fetch_recent_candles(symbol=symbol, interval=interval, category=category, limit=limit), None
        except ExchangeError as exc:
            return False, [], str(exc)

    def safe_set_leverage(self, symbol: str, leverage: float, category: str = "linear") -> tuple[bool, dict[str, Any] | None, str | None]:
        try:
            return True, self.set_leverage(symbol=symbol, leverage=leverage, category=category), None
        except ExchangeError as exc:
            return False, None, str(exc)

    def fetch_wallet_balance(self, account_type: str = "UNIFIED") -> dict[str, Any]:
        payload = self._private_get("/v5/account/wallet-balance", {"accountType": account_type})
        items = payload.get("list", [])
        return items[0] if items else {}

    def fetch_positions(self, category: str = "linear", settle_coin: str = "USDT") -> list[dict[str, Any]]:
        payload = self._private_get("/v5/position/list", {"category": category, "settleCoin": settle_coin})
        return payload.get("list", [])

    def fetch_open_orders(self, category: str = "linear", settle_coin: str = "USDT") -> list[dict[str, Any]]:
        payload = self._private_get(
            "/v5/order/realtime",
            {"category": category, "settleCoin": settle_coin, "openOnly": "0", "limit": "50"},
        )
        return payload.get("list", [])

    def fetch_order_by_link_id(self, symbol: str, order_link_id: str, category: str = "linear") -> dict[str, Any] | None:
        payload = self._private_get(
            "/v5/order/realtime",
            {
                "category": category,
                "symbol": symbol,
                "orderLinkId": order_link_id,
                "openOnly": "2",
                "limit": "1",
            },
        )
        items = payload.get("list", [])
        return items[0] if items else None

    def fetch_symbol_info(self, category: str = "linear", symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {"category": category}
        if symbol:
            params["symbol"] = symbol
        payload = self._public_get("/v5/market/instruments-info", params)

        results: list[dict[str, Any]] = []
        for item in payload.get("list", []):
            price_filter = item.get("priceFilter", {})
            lot_size_filter = item.get("lotSizeFilter", {})
            results.append(
                {
                    "symbol": item.get("symbol"),
                    "category": category,
                    "tickSize": price_filter.get("tickSize"),
                    "qtyStep": lot_size_filter.get("qtyStep"),
                    "minOrderQty": lot_size_filter.get("minOrderQty"),
                    "minNotionalValue": lot_size_filter.get("minNotionalValue"),
                }
            )
        return results

    def fetch_recent_candles(self, symbol: str, interval: str, category: str = "linear", limit: int = 200) -> list[dict[str, Any]]:
        payload = self._public_get(
            "/v5/market/kline",
            {"category": category, "symbol": symbol, "interval": interval, "limit": str(limit)},
        )

        candles: list[dict[str, Any]] = []
        for item in reversed(payload.get("list", [])):
            candles.append(
                {
                    "timestamp": datetime.fromtimestamp(int(item[0]) / 1000, tz=UTC).isoformat(),
                    "open": item[1],
                    "high": item[2],
                    "low": item[3],
                    "close": item[4],
                    "volume": item[5],
                    "turnover": item[6],
                }
            )
        return candles

    def fetch_market_tickers(self, category: str = "linear") -> list[dict[str, Any]]:
        payload = self._public_get("/v5/market/tickers", {"category": category})
        return payload.get("list", [])

    def fetch_orderbook(self, symbol: str, category: str = "linear", limit: int = 25) -> dict[str, list[dict[str, Any]]]:
        payload = self._public_get(
            "/v5/market/orderbook",
            {"category": category, "symbol": symbol, "limit": str(limit)},
        )
        return {
            "bids": [{"price": item[0], "size": item[1]} for item in payload.get("b", [])],
            "asks": [{"price": item[0], "size": item[1]} for item in payload.get("a", [])],
        }

    def set_leverage(self, symbol: str, leverage: float, category: str = "linear") -> dict[str, Any]:
        normalized = _format_leverage(leverage)
        return self._private_post(
            "/v5/position/set-leverage",
            {
                "category": category,
                "symbol": symbol,
                "buyLeverage": normalized,
                "sellLeverage": normalized,
            },
        )

    def place_market_order(
        self,
        symbol: str,
        side: str,
        qty: str,
        category: str = "linear",
        order_link_id: str | None = None,
    ) -> dict[str, Any]:
        return self._private_post(
            "/v5/order/create",
            {
                "category": category,
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": qty,
                "positionIdx": 0,
                "orderLinkId": order_link_id or f"demo-{symbol.lower()}-{secrets.token_hex(6)}",
            },
        )

    def close_position_market(self, symbol: str, side: str, qty: str, category: str = "linear") -> dict[str, Any]:
        return self._private_post(
            "/v5/order/create",
            {
                "category": category,
                "symbol": symbol,
                "side": side,
                "orderType": "Market",
                "qty": qty,
                "reduceOnly": True,
                "positionIdx": 0,
                "orderLinkId": f"close-{symbol.lower()}-{secrets.token_hex(6)}",
            },
        )

    def set_trading_stop(
        self,
        symbol: str,
        take_profit: str,
        stop_loss: str,
        category: str = "linear",
    ) -> dict[str, Any]:
        return self._private_post(
            "/v5/position/trading-stop",
            {
                "category": category,
                "symbol": symbol,
                "takeProfit": take_profit,
                "stopLoss": stop_loss,
                "tpTriggerBy": "MarkPrice",
                "slTriggerBy": "MarkPrice",
                "tpslMode": "Full",
                "positionIdx": 0,
            },
        )

    def normalize_price(self, value: float, tick_size: str) -> str:
        return _format_decimal(value=value, step=tick_size)

    def normalize_quantity(self, value: float, qty_step: str) -> str:
        return _format_decimal(value=value, step=qty_step)

    def _public_get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        return self._request(path=path, params=params or {}, authenticated=False)

    def _private_get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if not self.has_credentials():
            raise ExchangeError(f"Bybit {self.mode} API credentials are not configured")
        return self._request(path=path, params=params, authenticated=True)

    def _private_post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self.has_credentials():
            raise ExchangeError(f"Bybit {self.mode} API credentials are not configured")
        return self._request(path=path, params={}, authenticated=True, method="POST", body=body)

    def _request(
        self,
        path: str,
        params: dict[str, str],
        authenticated: bool,
        method: str = "GET",
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        query = urlencode(sorted(params.items()))
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}"

        headers = {"Accept": "application/json"}
        request_body: bytes | None = None
        if authenticated:
            timestamp = str(int(time.time() * 1000))
            body_string = json.dumps(body or {}, separators=(",", ":"))
            signature_source = query if method == "GET" else body_string
            signature_payload = f"{timestamp}{self.api_key}{self.recv_window}{signature_source}"
            signature = hmac.new(
                self.api_secret.encode("utf-8"),
                signature_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            headers.update(
                {
                    "X-BAPI-API-KEY": self.api_key,
                    "X-BAPI-TIMESTAMP": timestamp,
                    "X-BAPI-RECV-WINDOW": self.recv_window,
                    "X-BAPI-SIGN": signature,
                }
            )
            if method == "POST":
                headers["Content-Type"] = "application/json"
                request_body = body_string.encode("utf-8")

        request = Request(url, data=request_body, headers=headers, method=method)

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body_text = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ExchangeError(f"HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise ExchangeError(f"Network error: {exc.reason}") from exc
        except TimeoutError as exc:
            raise ExchangeError("Request timed out") from exc

        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise ExchangeError("Invalid JSON response from exchange") from exc

        if payload.get("retCode") != 0:
            raise ExchangeError(payload.get("retMsg", "Exchange request failed"))

        return payload.get("result", {})


BybitDemoClient = BybitClient


def get_exchange_client(execution_mode: str = "demo") -> BybitClient:
    if execution_mode == "live":
        return BybitClient(
            base_url=settings.bybit_live_base_url.rstrip("/"),
            api_key=settings.bybit_live_api_key,
            api_secret=settings.bybit_live_api_secret,
            mode="live",
        )

    return BybitClient(
        base_url=settings.bybit_demo_base_url.rstrip("/"),
        api_key=settings.bybit_demo_api_key,
        api_secret=settings.bybit_demo_api_secret,
        mode="demo",
    )


def get_exchange_status_summary() -> dict[str, Any]:
    demo_client = get_exchange_client("demo")
    live_client = get_exchange_client("live")
    return {"mode": demo_client.mode, "demo": demo_client.get_status(), "live": live_client.get_status()}


def _format_decimal(value: float, step: str) -> str:
    decimal_value = Decimal(str(value))
    decimal_step = Decimal(step)
    normalized = decimal_value.quantize(decimal_step, rounding=ROUND_DOWN)
    if decimal_step != 0:
        normalized = normalized - (normalized % decimal_step)
    return format(normalized.normalize(), "f")


def _format_leverage(value: float) -> str:
    decimal_value = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    return format(decimal_value.normalize(), "f")
