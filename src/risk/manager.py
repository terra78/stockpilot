"""リスク管理モジュール

ポジションサイズの上限計算・ストップロス判定・日次損失上限チェックを担う。
"""


class RiskManager:
    """リスク管理クラス。

    Args:
        max_position_ratio: 1銘柄への最大投資比率（デフォルト: 20%）
        stop_loss_percent:  ストップロスの下落率しきい値（デフォルト: 3%）
        max_daily_loss_usd: 1日の最大損失額（USD, デフォルト: $21 ≈ ¥3,000）
    """

    def __init__(
        self,
        max_position_ratio: float = 0.2,
        stop_loss_percent: float = 0.03,
        max_daily_loss_usd: float = 21.0,
    ) -> None:
        self.max_position_ratio = max_position_ratio
        self.stop_loss_percent = stop_loss_percent
        self.max_daily_loss_usd = max_daily_loss_usd

    def max_buy_quantity(self, price: float, portfolio_value: float) -> int:
        """購入可能な最大株数を返す（1銘柄投資上限を超えないよう制限）。"""
        if price <= 0:
            return 0
        return int(portfolio_value * self.max_position_ratio / price)

    def should_stop_loss(self, entry_price: float, current_price: float) -> bool:
        """ストップロスを発動すべきか判定する。

        entry_price から stop_loss_percent 以上下落していれば True。
        """
        if entry_price <= 0:
            return False
        loss_ratio = (entry_price - current_price) / entry_price
        return loss_ratio >= self.stop_loss_percent

    def is_daily_loss_exceeded(self, daily_pnl: float) -> bool:
        """当日の損失が上限を超えているか判定する。"""
        return daily_pnl <= -self.max_daily_loss_usd

    def config_dict(self) -> dict:
        """Claude プロンプト用のリスク設定 dict を返す。"""
        return {
            "max_position_ratio": self.max_position_ratio,
            "stop_loss_percent": self.stop_loss_percent,
        }
