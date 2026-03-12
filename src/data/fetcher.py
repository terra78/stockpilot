"""市場データ取得・テクニカル指標計算モジュール

バックテスト用にyfinanceから過去データを取得する。
本番環境ではAlpaca Market Data APIに切り替える想定。
"""

import numpy as np
import pandas as pd
import yfinance as yf


def fetch_historical_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """yfinanceで過去のOHLCVデータを取得する。

    Args:
        symbol: 銘柄コード（例: "AAPL"）
        start_date: 開始日 "YYYY-MM-DD"
        end_date: 終了日 "YYYY-MM-DD"

    Returns:
        columns=[open, high, low, close, volume] の DataFrame（index=date）
    """
    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start_date, end=end_date, auto_adjust=True)
    if df.empty:
        raise ValueError(f"{symbol}: データが取得できませんでした（期間: {start_date}〜{end_date}）")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["Open", "High", "Low", "Close", "Volume"]].rename(columns=str.lower)


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """テクニカル指標を計算してDataFrameに追加する。

    追加される列:
        sma5, sma25, sma75          - 単純移動平均
        rsi                         - RSI(14)
        macd, macd_signal, macd_hist - MACD(12/26/9)
        bb_upper, bb_mid, bb_lower  - ボリンジャーバンド(20)
    """
    df = df.copy()

    # 移動平均線
    df["sma5"] = df["close"].rolling(5).mean()
    df["sma25"] = df["close"].rolling(25).mean()
    df["sma75"] = df["close"].rolling(75).mean()

    # RSI (14期間)
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # MACD (12/26 EMA + 9期間シグナル)
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # ボリンジャーバンド (20期間 ±2σ)
    sma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    df["bb_upper"] = sma20 + 2 * std20
    df["bb_lower"] = sma20 - 2 * std20
    df["bb_mid"] = sma20

    return df


def get_prompt_data(df: pd.DataFrame, date, lookback: int = 30) -> dict | None:
    """指定日時点で利用可能なデータをClaude用プロンプト形式に整形する。

    Args:
        df: calculate_indicators() 適用済みの DataFrame
        date: 基準日（この日以前のデータのみ使用 → 未来情報漏洩防止）
        lookback: OHLCVとして渡す直近日数

    Returns:
        プロンプト用データ dict。指標計算に必要な最小データ数（75日）を
        下回る場合は None を返す。
    """
    df_available = df[df.index <= date]
    if len(df_available) < 75:  # SMA75が計算できる最小データ数
        return None

    recent = df_available.tail(lookback)
    latest = df_available.iloc[-1]

    def safe_float(val: float, default: float = 0.0) -> float:
        return float(val) if not np.isnan(val) else default

    return {
        "recent_ohlcv": recent[["open", "high", "low", "close", "volume"]].round(2).to_string(),
        "current_price": safe_float(latest["close"]),
        "sma5": safe_float(latest["sma5"]),
        "sma25": safe_float(latest["sma25"]),
        "sma75": safe_float(latest["sma75"]),
        "rsi": safe_float(latest["rsi"], default=50.0),
        "macd": safe_float(latest["macd"]),
        "macd_signal": safe_float(latest["macd_signal"]),
        "bb_upper": safe_float(latest["bb_upper"]),
        "bb_mid": safe_float(latest["bb_mid"]),
        "bb_lower": safe_float(latest["bb_lower"]),
    }
