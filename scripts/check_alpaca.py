#!/usr/bin/env python3
"""Alpaca Paper API 接続確認スクリプト

使い方:
    python scripts/check_alpaca.py          # 接続・残高確認のみ
    python scripts/check_alpaca.py --order  # テスト注文も実行（Paper のみ）
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.trading.executor import AlpacaExecutor


def check_connection(executor: AlpacaExecutor) -> bool:
    """接続・アカウント情報の確認。"""
    print("\n── 1. アカウント情報 ─────────────────────────")
    try:
        acct = executor.get_account()
        mode = "📄 Paper Trading" if acct["paper"] else "💰 Live Trading"
        print(f"  モード:           {mode}")
        print(f"  ステータス:       {acct['status']}")
        print(f"  現金残高:         ${acct['cash']:,.2f}")
        print(f"  買付余力:         ${acct['buying_power']:,.2f}")
        print(f"  ポートフォリオ:   ${acct['portfolio_value']:,.2f}")
        return True
    except Exception as e:
        print(f"  ❌ 接続エラー: {e}")
        return False


def check_positions(executor: AlpacaExecutor) -> None:
    """保有ポジションの確認。"""
    print("\n── 2. 保有ポジション ─────────────────────────")
    try:
        positions = executor.get_positions()
        if not positions:
            print("  (保有なし)")
        else:
            for pos in positions:
                pnl = pos["unrealized_pnl"] or 0
                print(
                    f"  {pos['symbol']:6s}  {pos['quantity']:4d}株"
                    f"  取得単価: ${pos['avg_price']:.2f}"
                    f"  現在値: ${pos['current_price']:.2f}"
                    f"  含み損益: ${pnl:+.2f}"
                )
    except Exception as e:
        print(f"  ❌ エラー: {e}")


def check_orders(executor: AlpacaExecutor) -> None:
    """未約定注文の確認。"""
    print("\n── 3. 未約定注文 ──────────────────────────────")
    try:
        orders = executor.get_open_orders()
        if not orders:
            print("  (未約定注文なし)")
        else:
            for o in orders:
                print(f"  {o['symbol']}  {o['side'].upper()}  {o['qty']}株  [{o['status']}]")
    except Exception as e:
        print(f"  ❌ エラー: {e}")


def run_test_order(executor: AlpacaExecutor) -> None:
    """テスト注文（Paper のみ）: AAPL 1株買い → 即キャンセル。"""
    print("\n── 4. テスト注文 ──────────────────────────────")

    if not executor.paper:
        print("  ⚠️  Live モードではテスト注文をスキップします")
        return

    print("  AAPL 1株 成行買い注文を発注...")
    try:
        order = executor.market_buy("AAPL", 1, reason="接続テスト")
        print(f"  ✅ 注文受付: ID={order['id'][:8]}...  ステータス={order['status']}")

        # 即キャンセル
        cancelled = executor.cancel_all_orders()
        print(f"  🗑️  注文キャンセル: {cancelled}件")
    except Exception as e:
        print(f"  ❌ 注文エラー: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpaca API 接続確認")
    parser.add_argument("--order", action="store_true", help="テスト注文を実行（Paper のみ）")
    args = parser.parse_args()

    print("=" * 50)
    print("Alpaca API 接続確認")
    print("=" * 50)

    executor = AlpacaExecutor()

    ok = check_connection(executor)
    if not ok:
        print("\n❌ 接続失敗。.env の ALPACA_API_KEY / ALPACA_SECRET_KEY を確認してください")
        sys.exit(1)

    check_positions(executor)
    check_orders(executor)

    if args.order:
        run_test_order(executor)

    print("\n✅ 接続確認完了\n")


if __name__ == "__main__":
    main()
