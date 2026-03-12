"""Alpaca API 注文実行モジュール

Paper / Live 両対応。環境変数 ALPACA_BASE_URL で切り替える。
  Paper: https://paper-api.alpaca.markets
  Live:  https://api.alpaca.markets
"""

import os
from typing import Optional

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.models import Position, Order


def _is_paper() -> bool:
    base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    return "paper" in base_url


class AlpacaExecutor:
    """Alpaca API を使った注文実行クライアント。

    Args:
        api_key:    ALPACA_API_KEY（省略時は環境変数から取得）
        secret_key: ALPACA_SECRET_KEY（省略時は環境変数から取得）
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.paper = _is_paper()
        self.client = TradingClient(
            api_key=self.api_key,
            secret_key=self.secret_key,
            paper=self.paper,
        )

    # ------------------------------------------------------------------
    # アカウント情報
    # ------------------------------------------------------------------

    def get_account(self) -> dict:
        """アカウント情報を返す（残高・買付余力・ポートフォリオ評価額）。"""
        acct = self.client.get_account()
        return {
            "status": acct.status,
            "cash": float(acct.cash),
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "equity": float(acct.equity),
            "paper": self.paper,
        }

    # ------------------------------------------------------------------
    # ポジション管理
    # ------------------------------------------------------------------

    def get_positions(self) -> list[dict]:
        """全保有ポジションを返す。"""
        positions = self.client.get_all_positions()
        return [_format_position(p) for p in positions]

    def get_position(self, symbol: str) -> Optional[dict]:
        """指定銘柄のポジションを返す。保有なしの場合は None。"""
        try:
            pos = self.client.get_open_position(symbol)
            return _format_position(pos)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 注文
    # ------------------------------------------------------------------

    def market_buy(self, symbol: str, qty: int, reason: str = "") -> dict:
        """成行買い注文を発注する。"""
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(req)
        return _format_order(order, reason)

    def market_sell(self, symbol: str, qty: int, reason: str = "") -> dict:
        """成行売り注文を発注する。"""
        req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
        )
        order = self.client.submit_order(req)
        return _format_order(order, reason)

    def limit_buy(self, symbol: str, qty: int, limit_price: float, reason: str = "") -> dict:
        """指値買い注文を発注する。"""
        req = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=TimeInForce.DAY,
            limit_price=round(limit_price, 2),
        )
        order = self.client.submit_order(req)
        return _format_order(order, reason)

    def close_position(self, symbol: str) -> dict:
        """指定銘柄のポジションを全決済する。"""
        order = self.client.close_position(symbol)
        return _format_order(order, "ポジション全決済")

    def cancel_all_orders(self) -> int:
        """全未約定注文をキャンセルし、キャンセルした件数を返す。"""
        cancelled = self.client.cancel_orders()
        return len(cancelled)

    def get_open_orders(self) -> list[dict]:
        """未約定の注文一覧を返す。"""
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = self.client.get_orders(req)
        return [_format_order(o) for o in orders]


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------

def _format_position(pos: Position) -> dict:
    return {
        "symbol": pos.symbol,
        "quantity": int(float(pos.qty)),
        "avg_price": float(pos.avg_entry_price),
        "current_price": float(pos.current_price) if pos.current_price else None,
        "market_value": float(pos.market_value) if pos.market_value else None,
        "unrealized_pnl": float(pos.unrealized_pl) if pos.unrealized_pl else None,
        "unrealized_pnl_pct": float(pos.unrealized_plpc) if pos.unrealized_plpc else None,
    }


def _format_order(order: Order, reason: str = "") -> dict:
    return {
        "id": str(order.id),
        "symbol": order.symbol,
        "side": order.side.value,
        "qty": float(order.qty) if order.qty else None,
        "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
        "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        "status": order.status.value,
        "reason": reason,
    }
