#!/usr/bin/env python3
"""本番(Paper)取引実行スクリプト

GitHub Actions の workflow_dispatch から呼び出される。
外部 cron サービスが GitHub API 経由で 15 分ごとに起動する。
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True)

from src.ai.judge import AIJudge
from src.data.fetcher import calculate_indicators, fetch_historical_data, get_prompt_data
from src.risk.manager import RiskManager
from src.trading.executor import AlpacaExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

SYMBOLS = [s.strip() for s in os.getenv("TRADE_SYMBOLS", "AAPL").split(",")]


def run() -> None:
    log.info("=" * 50)
    log.info("取引サイクル開始")
    log.info(f"対象銘柄: {SYMBOLS}")

    executor = AlpacaExecutor()
    risk_manager = RiskManager(
        max_position_ratio=float(os.getenv("MAX_POSITION_RATIO", 0.2)),
        stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", 0.03)),
        max_daily_loss_usd=float(os.getenv("MAX_DAILY_LOSS_USD", 21.0)),
    )
    judge = AIJudge()

    # 市場オープンチェック
    clock = executor.client.get_clock()
    if not clock.is_open:
        next_open = clock.next_open.strftime("%Y-%m-%d %H:%M %Z")
        log.info(f"市場クローズ中 - スキップ（次回オープン: {next_open}）")
        return

    # アカウント情報
    acct = executor.get_account()
    log.info(
        f"現金: ${acct['cash']:,.2f}  "
        f"買付余力: ${acct['buying_power']:,.2f}  "
        f"ポートフォリオ: ${acct['portfolio_value']:,.2f}"
    )

    portfolio_value = acct["portfolio_value"]
    available_cash = acct["cash"]
    today = datetime.now().strftime("%Y-%m-%d")
    data_start = (datetime.now() - timedelta(days=150)).strftime("%Y-%m-%d")

    for symbol in SYMBOLS:
        log.info(f"--- {symbol} ---")
        try:
            # データ取得・指標計算（直近150日）
            df = fetch_historical_data(symbol, data_start, today)
            df = calculate_indicators(df)

            market_data = get_prompt_data(df, df.index[-1])
            if market_data is None:
                log.warning(f"{symbol}: データ不足 - スキップ")
                continue

            log.info(
                f"  現在値: ${market_data['current_price']:.2f}  "
                f"RSI: {market_data['rsi']:.1f}  "
                f"SMA5/25: ${market_data['sma5']:.2f}/${market_data['sma25']:.2f}"
            )

            # 現在ポジション取得
            pos = executor.get_position(symbol)
            position = {"quantity": 0, "avg_price": 0.0}
            if pos:
                position = {"quantity": pos["quantity"], "avg_price": pos["avg_price"]}
                log.info(
                    f"  保有: {pos['quantity']}株 @ ${pos['avg_price']:.2f}  "
                    f"含み損益: ${pos['unrealized_pnl']:+.2f}"
                )

            # ストップロスチェック
            if position["quantity"] > 0 and risk_manager.should_stop_loss(
                position["avg_price"], market_data["current_price"]
            ):
                log.warning(f"  🛑 ストップロス発動 @ ${market_data['current_price']:.2f}")
                order = executor.close_position(symbol)
                log.info(f"  全決済 注文ID: {order['id'][:8]}...")
                continue

            # AI 判断
            decision = judge.get_decision(
                symbol, market_data, position,
                available_cash, risk_manager.config_dict(),
            )
            action = decision.get("action", "HOLD")
            reason = decision.get("reason", "")
            confidence = decision.get("confidence", 0.0)
            log.info(f"  AI判断: {action}  確信度: {confidence:.2f}  理由: {reason}")

            # 注文実行
            if action == "BUY" and confidence >= 0.6:
                max_qty = risk_manager.max_buy_quantity(
                    market_data["current_price"], portfolio_value
                )
                if max_qty == 0 and available_cash >= market_data["current_price"]:
                    max_qty = 1
                qty = min(decision.get("quantity", 1), max_qty)
                if qty > 0:
                    order = executor.market_buy(symbol, qty, reason)
                    log.info(
                        f"  🟢 BUY {qty}株  "
                        f"注文ID: {order['id'][:8]}...  "
                        f"ステータス: {order['status']}"
                    )
                    available_cash -= qty * market_data["current_price"]

            elif action == "SELL" and position["quantity"] > 0:
                qty = min(
                    decision.get("quantity", position["quantity"]),
                    position["quantity"],
                )
                if qty > 0:
                    order = executor.market_sell(symbol, qty, reason)
                    log.info(
                        f"  🔴 SELL {qty}株  "
                        f"注文ID: {order['id'][:8]}...  "
                        f"ステータス: {order['status']}"
                    )

        except Exception as e:
            log.error(f"  ❌ {symbol} 処理エラー: {e}", exc_info=True)

    log.info("取引サイクル終了")
    log.info("=" * 50)


if __name__ == "__main__":
    run()
