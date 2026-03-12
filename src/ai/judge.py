"""Claude APIによる売買判断モジュール

AIJudge   : Claude APIを呼び出してBUY/SELL/HOLDを判断する
SimpleJudge: APIなしのルールベース判断（--no-ai オプション用）
"""

import json
import os
import re

import anthropic

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

_SYSTEM_PROMPT = """あなたはプロフェッショナルな米国株式トレーダーです。
提供されたテクニカル分析データをもとに売買判断を行い、
必ず以下のJSON形式のみで返答してください（他のテキストは不要）。

{
  "action": "BUY" | "SELL" | "HOLD",
  "symbol": "銘柄コード",
  "quantity": 整数（BUY/SELLの株数。HOLDは0）,
  "reason": "判断根拠（日本語50字以内）",
  "confidence": 0.0〜1.0
}

判断ルール:
- 確信度0.6未満はHOLDを推奨
- SMA・RSI・MACDを総合的に判断する
- ポジションなしでSELLは不要"""


def _build_prompt(
    symbol: str,
    market_data: dict,
    position: dict,
    available_cash: float,
    risk_config: dict,
) -> str:
    qty = position.get("quantity", 0)
    avg_price = position.get("avg_price", 0.0)
    unrealized_pnl = (market_data["current_price"] - avg_price) * qty if qty > 0 else 0.0

    return f"""## 銘柄: {symbol}

## 直近30日のOHLCV
{market_data["recent_ohlcv"]}

## テクニカル指標（本日終値時点）
- 現在値:         ${market_data["current_price"]:.2f}
- SMA5/25/75:    ${market_data["sma5"]:.2f} / ${market_data["sma25"]:.2f} / ${market_data["sma75"]:.2f}
- RSI(14):       {market_data["rsi"]:.1f}
- MACD/Signal:   {market_data["macd"]:.4f} / {market_data["macd_signal"]:.4f}
- BB上/中/下:    ${market_data["bb_upper"]:.2f} / ${market_data["bb_mid"]:.2f} / ${market_data["bb_lower"]:.2f}

## 現在のポジション
- 保有株数:     {qty}株
- 平均取得単価: ${avg_price:.2f}
- 含み損益:     ${unrealized_pnl:.2f}

## 利用可能資金: ${available_cash:.2f}
## リスク設定: 最大{risk_config["max_position_ratio"] * 100:.0f}%投資 / 損切り{risk_config["stop_loss_percent"] * 100:.0f}%

売買判断をJSONで返してください。"""


class AIJudge:
    """Claude APIを使用した売買判断エンジン。"""

    def __init__(self) -> None:
        self.client = anthropic.Anthropic()

    def get_decision(
        self,
        symbol: str,
        market_data: dict,
        position: dict,
        available_cash: float,
        risk_config: dict,
    ) -> dict:
        """Claude APIに問い合わせて売買判断を返す。

        API呼び出し失敗やJSONパース失敗時はHOLDにフォールバックする。
        """
        prompt = _build_prompt(symbol, market_data, position, available_cash, risk_config)
        try:
            message = self.client.messages.create(
                model=MODEL,
                max_tokens=256,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = message.content[0].text.strip()
            # JSON部分のみ抽出（```json ... ``` ブロック対応）
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group()
            return json.loads(text)
        except (json.JSONDecodeError, anthropic.APIError, Exception) as e:
            return {
                "action": "HOLD",
                "symbol": symbol,
                "quantity": 0,
                "reason": f"APIエラー: {str(e)[:40]}",
                "confidence": 0.0,
            }


class SimpleJudge:
    """Claude APIを使わないルールベース判断（テスト・コスト節約用）。

    ゴールデンクロス/デッドクロス + RSIフィルターを使う。
    """

    def get_decision(
        self,
        symbol: str,
        market_data: dict,
        position: dict,
        available_cash: float,
        risk_config: dict,
    ) -> dict:
        price = market_data["current_price"]
        rsi = market_data["rsi"]
        sma5 = market_data["sma5"]
        sma25 = market_data["sma25"]
        qty = position.get("quantity", 0)

        # BUY条件: ゴールデンクロス & RSIが買われすぎでない & ノーポジ
        if sma5 > sma25 and rsi < 70 and qty == 0:
            max_invest = available_cash * risk_config["max_position_ratio"]
            buy_qty = max(1, int(max_invest / price))
            return {
                "action": "BUY",
                "symbol": symbol,
                "quantity": buy_qty,
                "reason": f"SMAゴールデンクロス・RSI={rsi:.0f}",
                "confidence": 0.65,
            }

        # SELL条件: デッドクロス or RSI過買い & ポジションあり
        if (sma5 < sma25 or rsi > 80) and qty > 0:
            return {
                "action": "SELL",
                "symbol": symbol,
                "quantity": qty,
                "reason": f"SMAデッドクロスまたはRSI過買い={rsi:.0f}",
                "confidence": 0.65,
            }

        return {
            "action": "HOLD",
            "symbol": symbol,
            "quantity": 0,
            "reason": "様子見",
            "confidence": 0.5,
        }
