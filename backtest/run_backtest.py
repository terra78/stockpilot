#!/usr/bin/env python3
"""バックテスト実行スクリプト

使い方:
    # ルールベース（API不要・高速）
    python backtest/run_backtest.py --symbol AAPL --start 2024-01-01 --end 2024-12-31 --no-ai

    # Claude AI判断（ANTHROPIC_API_KEY 必須）
    python backtest/run_backtest.py --symbol AAPL --start 2024-01-01 --end 2024-12-31

    # 複数銘柄
    python backtest/run_backtest.py --symbol AAPL MSFT NVDA --start 2024-06-01 --end 2024-12-31 --capital 700
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # GUIなし環境でも動作
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from dotenv import load_dotenv

# プロジェクトルートを sys.path に追加
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env", override=True)

from src.ai.judge import AIJudge, SimpleJudge
from src.data.fetcher import calculate_indicators, fetch_historical_data, get_prompt_data
from src.risk.manager import RiskManager


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------

class Portfolio:
    """シミュレーション用ポートフォリオ。"""

    def __init__(self, initial_cash: float) -> None:
        self.cash = initial_cash
        self.initial_cash = initial_cash
        self.positions: dict[str, dict] = {}  # {symbol: {quantity, avg_price}}
        self.trades: list[dict] = []
        self.daily_records: list[dict] = []

    def value(self, prices: dict[str, float]) -> float:
        """現在の総評価額（現金 + 全ポジション）を返す。"""
        total = self.cash
        for symbol, pos in self.positions.items():
            if symbol in prices:
                total += pos["quantity"] * prices[symbol]
        return total

    def buy(self, symbol: str, quantity: int, price: float, date, reason: str) -> bool:
        """指定株数を成行買いでシミュレート。資金不足なら数量を調整。"""
        cost = quantity * price
        if cost > self.cash:
            quantity = int(self.cash / price)
            cost = quantity * price
        if quantity <= 0:
            return False

        self.cash -= cost
        if symbol in self.positions:
            old = self.positions[symbol]
            total_qty = old["quantity"] + quantity
            self.positions[symbol] = {
                "quantity": total_qty,
                "avg_price": (old["quantity"] * old["avg_price"] + cost) / total_qty,
            }
        else:
            self.positions[symbol] = {"quantity": quantity, "avg_price": price}

        self.trades.append(
            {
                "date": date,
                "symbol": symbol,
                "action": "BUY",
                "quantity": quantity,
                "price": price,
                "amount": cost,
                "pnl": None,
                "reason": reason,
            }
        )
        return True

    def sell(self, symbol: str, quantity: int, price: float, date, reason: str) -> bool:
        """指定株数を成行売りでシミュレート。"""
        if symbol not in self.positions:
            return False
        pos = self.positions[symbol]
        quantity = min(quantity, pos["quantity"])
        if quantity <= 0:
            return False

        proceeds = quantity * price
        pnl = (price - pos["avg_price"]) * quantity
        self.cash += proceeds

        if quantity >= pos["quantity"]:
            del self.positions[symbol]
        else:
            self.positions[symbol]["quantity"] -= quantity

        self.trades.append(
            {
                "date": date,
                "symbol": symbol,
                "action": "SELL",
                "quantity": quantity,
                "price": price,
                "amount": proceeds,
                "pnl": pnl,
                "reason": reason,
            }
        )
        return True


# ---------------------------------------------------------------------------
# メトリクス計算
# ---------------------------------------------------------------------------

def calculate_metrics(portfolio: Portfolio) -> dict:
    """バックテスト結果のパフォーマンス指標を計算する。"""
    if not portfolio.daily_records:
        return {}

    values = [r["portfolio_value"] for r in portfolio.daily_records]
    dates = [r["date"] for r in portfolio.daily_records]
    returns = pd.Series(values).pct_change().dropna()

    total_return = (values[-1] - portfolio.initial_cash) / portfolio.initial_cash * 100

    # 最大ドローダウン
    peak = pd.Series(values).cummax()
    drawdown = (pd.Series(values) - peak) / peak * 100
    max_drawdown = float(drawdown.min())

    # シャープレシオ（年率化, リスクフリーレート=0）
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0.0

    # 勝率
    sell_trades = [t for t in portfolio.trades if t["action"] == "SELL" and t["pnl"] is not None]
    win_rate = (
        sum(1 for t in sell_trades if t["pnl"] > 0) / len(sell_trades) * 100
        if sell_trades
        else 0.0
    )

    # 年率換算
    days = (dates[-1] - dates[0]).days
    annual_return = ((1 + total_return / 100) ** (365 / days) - 1) * 100 if days > 0 else 0.0

    return {
        "initial_value": portfolio.initial_cash,
        "final_value": values[-1],
        "total_return": total_return,
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe_ratio": sharpe,
        "win_rate": win_rate,
        "total_trades": len(portfolio.trades),
        "sell_trades": len(sell_trades),
    }


# ---------------------------------------------------------------------------
# グラフ出力
# ---------------------------------------------------------------------------

def plot_results(
    portfolio: "Portfolio",
    all_data: dict,
    args: argparse.Namespace,
    metrics: dict,
    output_dir: Path,
    timestamp: str,
) -> Path:
    """バックテスト結果をマルチパネルチャートとして保存する。

    上段：株価推移 + BUY/SELL マーカー
    中段：ポートフォリオ評価額推移
    下段：ドローダウン
    """
    symbols = args.symbol
    n_symbols = len(symbols)

    # ---- 図の構成 ----
    # 銘柄ごとに株価パネル 1 枚 + ポートフォリオ 1 枚 + ドローダウン 1 枚
    n_rows = n_symbols + 2
    fig, axes = plt.subplots(
        n_rows, 1,
        figsize=(14, 4 * n_rows),
        sharex=False,
        gridspec_kw={"hspace": 0.45},
    )
    if n_rows == 1:
        axes = [axes]

    fig.suptitle(
        f"Backtest: {', '.join(symbols)}  "
        f"{args.start} – {args.end}\n"
        f"Return: {metrics.get('total_return', 0):+.2f}%  "
        f"Sharpe: {metrics.get('sharpe_ratio', 0):.2f}  "
        f"MaxDD: {metrics.get('max_drawdown', 0):.2f}%  "
        f"WinRate: {metrics.get('win_rate', 0):.1f}%",
        fontsize=11,
        y=1.01,
    )

    # ---- 各銘柄の株価チャート ----
    for idx, symbol in enumerate(symbols):
        ax = axes[idx]
        df = all_data[symbol]
        # 指定開始日以降のみ描画
        df_plot = df[df.index >= args.start].copy()

        ax.plot(df_plot.index, df_plot["close"], color="#1f77b4", linewidth=1.2, label="Close")

        # SMA
        if "sma25" in df_plot.columns:
            ax.plot(df_plot.index, df_plot["sma25"], color="orange", linewidth=0.8,
                    linestyle="--", label="SMA25")
        if "sma75" in df_plot.columns:
            ax.plot(df_plot.index, df_plot["sma75"], color="gray", linewidth=0.8,
                    linestyle=":", label="SMA75")

        # BUY / SELL / STOP_LOSS マーカー
        symbol_trades = [t for t in portfolio.trades if t["symbol"] == symbol]
        buy_dates  = [t["date"] for t in symbol_trades if t["action"] == "BUY"]
        buy_prices = [t["price"] for t in symbol_trades if t["action"] == "BUY"]
        sell_dates  = [t["date"] for t in symbol_trades if t["action"] in ("SELL",)]
        sell_prices = [t["price"] for t in symbol_trades if t["action"] in ("SELL",)]
        # ストップロス（reason に「ストップロス」を含む SELL）
        sl_dates  = [t["date"] for t in symbol_trades
                     if t["action"] == "SELL" and "ストップロス" in (t.get("reason") or "")]
        sl_prices = [t["price"] for t in symbol_trades
                     if t["action"] == "SELL" and "ストップロス" in (t.get("reason") or "")]

        if buy_dates:
            ax.scatter(buy_dates, buy_prices, marker="^", color="green",
                       zorder=5, s=60, label=f"BUY ({len(buy_dates)})")
        if sell_dates:
            ax.scatter(sell_dates, sell_prices, marker="v", color="red",
                       zorder=5, s=60, label=f"SELL ({len(sell_dates)})")
        if sl_dates:
            ax.scatter(sl_dates, sl_prices, marker="x", color="darkred",
                       zorder=6, s=80, label=f"StopLoss ({len(sl_dates)})")

        ax.set_title(f"{symbol} Price", fontsize=10)
        ax.set_ylabel("Price (USD)")
        ax.legend(fontsize=7, loc="upper left", ncol=4)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator())
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
        ax.grid(True, alpha=0.3)

    # ---- ポートフォリオ評価額 ----
    ax_pf = axes[n_symbols]
    daily_df = pd.DataFrame(portfolio.daily_records)
    if not daily_df.empty:
        ax_pf.plot(daily_df["date"], daily_df["portfolio_value"],
                   color="#2ca02c", linewidth=1.4, label="Portfolio Value")
        ax_pf.axhline(portfolio.initial_cash, color="gray", linewidth=0.8,
                      linestyle="--", label=f"Initial ${portfolio.initial_cash:,.0f}")
        ax_pf.fill_between(
            daily_df["date"],
            portfolio.initial_cash,
            daily_df["portfolio_value"],
            where=daily_df["portfolio_value"] >= portfolio.initial_cash,
            alpha=0.15, color="green",
        )
        ax_pf.fill_between(
            daily_df["date"],
            portfolio.initial_cash,
            daily_df["portfolio_value"],
            where=daily_df["portfolio_value"] < portfolio.initial_cash,
            alpha=0.15, color="red",
        )
    ax_pf.set_title("Portfolio Value", fontsize=10)
    ax_pf.set_ylabel("Value (USD)")
    ax_pf.legend(fontsize=8, loc="upper left")
    ax_pf.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_pf.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax_pf.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_pf.grid(True, alpha=0.3)

    # ---- ドローダウン ----
    ax_dd = axes[n_symbols + 1]
    if not daily_df.empty:
        values = daily_df["portfolio_value"].values
        peak = pd.Series(values).cummax()
        drawdown = (pd.Series(values) - peak) / peak * 100
        ax_dd.fill_between(daily_df["date"], drawdown, 0, color="red", alpha=0.4)
        ax_dd.plot(daily_df["date"], drawdown, color="darkred", linewidth=0.8)
        ax_dd.axhline(0, color="gray", linewidth=0.6)
    ax_dd.set_title("Drawdown", fontsize=10)
    ax_dd.set_ylabel("Drawdown (%)")
    ax_dd.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_dd.xaxis.set_major_locator(mdates.MonthLocator())
    plt.setp(ax_dd.xaxis.get_majorticklabels(), rotation=30, ha="right", fontsize=8)
    ax_dd.grid(True, alpha=0.3)

    # ---- 保存 ----
    chart_file = output_dir / f"chart_{timestamp}.png"
    fig.savefig(chart_file, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return chart_file


# ---------------------------------------------------------------------------
# バックテスト本体
# ---------------------------------------------------------------------------

def run_backtest(args: argparse.Namespace) -> None:
    print(f"\n{'='*60}")
    print("バックテスト開始")
    print(f"銘柄:     {', '.join(args.symbol)}")
    print(f"期間:     {args.start} 〜 {args.end}")
    print(f"初期資金: ${args.capital:.2f}")
    print(f"モード:   {'ルールベース (--no-ai)' if args.no_ai else 'Claude AI'}")
    print(f"{'='*60}\n")

    # --- データ取得（指標計算に必要な分だけ前倒し） ---
    start_buffer = (
        pd.to_datetime(args.start) - pd.DateOffset(days=120)
    ).strftime("%Y-%m-%d")

    all_data: dict[str, pd.DataFrame] = {}
    for symbol in args.symbol:
        print(f"📊 {symbol} のデータを取得中...")
        df = fetch_historical_data(symbol, start_buffer, args.end)
        df = calculate_indicators(df)
        all_data[symbol] = df
        print(f"   {len(df)}日分取得完了（{df.index[0].date()} 〜 {df.index[-1].date()}）")

    # 取引対象日（指定開始日以降の実際の取引日）
    all_dates = sorted(
        set(date for df in all_data.values() for date in df[df.index >= args.start].index)
    )
    if not all_dates:
        print("エラー: 指定期間のデータがありません")
        return

    # --- 初期化 ---
    portfolio = Portfolio(args.capital)
    risk_manager = RiskManager(
        max_position_ratio=float(os.getenv("MAX_POSITION_RATIO", 0.2)),
        stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", 0.03)),
        max_daily_loss_usd=float(os.getenv("MAX_DAILY_LOSS_USD", 21.0)),
    )
    judge = SimpleJudge() if args.no_ai else AIJudge()

    print(f"\n📅 {len(all_dates)}営業日分をシミュレーション中...\n")

    for i, date in enumerate(all_dates):
        # 当日の終値を取得
        prices: dict[str, float] = {}
        for symbol in args.symbol:
            df = all_data[symbol]
            if date in df.index:
                prices[symbol] = float(df.loc[date, "close"])

        daily_start_value = portfolio.value(prices)

        for symbol in args.symbol:
            if symbol not in prices:
                continue
            current_price = prices[symbol]
            position = portfolio.positions.get(symbol, {"quantity": 0, "avg_price": 0.0})

            # 1. ストップロスチェック（自動損切り）
            if position["quantity"] > 0 and risk_manager.should_stop_loss(
                position["avg_price"], current_price
            ):
                portfolio.sell(
                    symbol, position["quantity"], current_price, date, "ストップロス自動損切り"
                )
                print(f"  🛑 {date.date()} {symbol} ストップロス @ ${current_price:.2f}")
                continue

            # 2. 日次損失上限チェック
            if risk_manager.is_daily_loss_exceeded(portfolio.value(prices) - daily_start_value):
                continue

            # 3. データ整形 → AI判断
            market_data = get_prompt_data(all_data[symbol], date)
            if market_data is None:
                continue  # 指標計算に必要なデータが不足

            portfolio_value = portfolio.value(prices)
            decision = judge.get_decision(
                symbol, market_data, position, portfolio.cash, risk_manager.config_dict()
            )

            action = decision.get("action", "HOLD")
            reason = decision.get("reason", "")
            confidence = decision.get("confidence", 0.0)

            # 4. 注文実行
            if action == "BUY" and confidence >= 0.6:
                max_qty = risk_manager.max_buy_quantity(current_price, portfolio_value)
                # 少額資金でも1株は購入できるよう保証（現金が足りる場合）
                if max_qty == 0 and portfolio.cash >= current_price:
                    max_qty = 1
                qty = min(decision.get("quantity", 1), max_qty)
                if qty > 0 and portfolio.buy(symbol, qty, current_price, date, reason):
                    print(
                        f"  🟢 {date.date()} {symbol} BUY  {qty:3d}株 @ ${current_price:.2f}"
                        f" | {reason}"
                    )

            elif action == "SELL" and position["quantity"] > 0:
                qty = min(decision.get("quantity", position["quantity"]), position["quantity"])
                if portfolio.sell(symbol, qty, current_price, date, reason):
                    pnl = portfolio.trades[-1]["pnl"]
                    print(
                        f"  🔴 {date.date()} {symbol} SELL {qty:3d}株 @ ${current_price:.2f}"
                        f" | PnL: ${pnl:+.2f} | {reason}"
                    )

        # 日次記録
        portfolio.daily_records.append(
            {
                "date": date,
                "portfolio_value": portfolio.value(prices),
                "cash": portfolio.cash,
            }
        )

        # 進捗表示（20日ごと）
        if (i + 1) % 20 == 0:
            current_value = portfolio.value(prices)
            ret = (current_value - portfolio.initial_cash) / portfolio.initial_cash * 100
            print(f"\n  [{i+1}/{len(all_dates)}] {date.date()} 評価額: ${current_value:.2f} ({ret:+.1f}%)\n")

    # --- 未決済ポジションを最終日終値で強制決済 ---
    final_prices = {
        symbol: float(all_data[symbol].iloc[-1]["close"])
        for symbol in args.symbol
        if symbol in all_data
    }
    for symbol, pos in list(portfolio.positions.items()):
        if pos["quantity"] > 0 and symbol in final_prices:
            portfolio.sell(
                symbol,
                pos["quantity"],
                final_prices[symbol],
                all_dates[-1],
                "バックテスト終了・強制決済",
            )

    # --- 結果表示 ---
    metrics = calculate_metrics(portfolio)
    print(f"\n{'='*60}")
    print("バックテスト結果")
    print(f"{'='*60}")
    print(f"初期資金:         ${metrics['initial_value']:>10.2f}")
    print(f"最終評価額:       ${metrics['final_value']:>10.2f}")
    print(f"トータルリターン: {metrics['total_return']:>+10.2f}%")
    print(f"年率換算:         {metrics['annual_return']:>+10.2f}%")
    print(f"最大ドローダウン: {metrics['max_drawdown']:>10.2f}%")
    print(f"シャープレシオ:   {metrics['sharpe_ratio']:>10.2f}")
    print(f"勝率:             {metrics['win_rate']:>10.1f}%")
    print(f"総取引数:         {metrics['total_trades']:>10}回 (売: {metrics['sell_trades']}回)")
    print(f"{'='*60}\n")

    # --- 結果保存 ---
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    trades_df = pd.DataFrame(portfolio.trades)
    trades_file = output_dir / f"trades_{timestamp}.csv"
    trades_df.to_csv(trades_file, index=False, encoding="utf-8-sig")

    daily_df = pd.DataFrame(portfolio.daily_records)
    daily_file = output_dir / f"daily_{timestamp}.csv"
    daily_df.to_csv(daily_file, index=False, encoding="utf-8-sig")

    chart_file = plot_results(portfolio, all_data, args, metrics, output_dir, timestamp)

    print(f"✅ 結果を保存しました:")
    print(f"   取引履歴: {trades_file}")
    print(f"   日次記録: {daily_file}")
    print(f"   チャート: {chart_file}")


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="AI株トレードバックテスト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--symbol", nargs="+", default=["AAPL"], help="銘柄コード（複数可）")
    parser.add_argument("--start", default="2024-01-01", help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", default="2024-12-31", help="終了日 YYYY-MM-DD")
    parser.add_argument("--capital", type=float, default=700.0, help="初期資金（USD）")
    parser.add_argument(
        "--no-ai", action="store_true", help="Claude APIを使わずルールベースで実行"
    )
    parser.add_argument("--output", default="backtest/results", help="結果出力ディレクトリ")
    return parser.parse_args()


if __name__ == "__main__":
    run_backtest(parse_args())
