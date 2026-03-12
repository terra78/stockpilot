# 🤖 AI全自動株取引システム — Claude Code 引き継ぎ資料

> このファイルはClaude Codeがプロジェクトの文脈を把握するための設計書です。
> リポジトリルートに `CLAUDE.md` として配置してください。

---

## プロジェクト概要

| 項目 | 内容 |
|------|------|
| **プロジェクト名** | stockpilot（仮） |
| **目的** | Claude APIを使ったAI自律判断による米国株全自動売買システム |
| **対象市場** | 米国株（NYSE / NASDAQ） |
| **取引スタイル** | AIに判断を委ねる（テクニカル＋センチメント分析） |
| **初期運用資金** | 約10万円（JPY） |
| **開発フェーズ** | Phase 1：ペーパートレード検証中 |

---

## 使用技術・サービス

### ブローカー
- **Alpaca Markets**（https://alpaca.markets）
  - 米国株ゼロコミッション
  - Paper Trading API（仮想売買）完備
  - 日本居住者対応済み

### AI判断エンジン
- **Anthropic Claude API**（`claude-sonnet-4-20250514`）
  - 1回の判断コスト目安：約0.3〜1円
  - 月間API費用目安：¥500〜2,000

### インフラ
- **サーバー**：Render 無料枠 or GitHub Actions（cron）
- **DB / ログ**：Supabase 無料枠（PostgreSQL）
- **言語**：Python 3.11+

---

## システムアーキテクチャ

```
┌─────────────────────────────────────────────────────┐
│                   スケジューラー                        │
│         GitHub Actions cron / Render cron job        │
└────────────────────┬────────────────────────────────┘
                     │ 15分ごと（市場開場中）
                     ▼
┌─────────────────────────────────────────────────────┐
│              価格・指標データ取得                        │
│         Alpaca Market Data API (無料)                │
│   取得内容：OHLCV・移動平均・RSI・出来高・最新ニュース    │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│                AI判断エンジン                           │
│              Claude API (Sonnet)                     │
│  入力：市場データ＋ポジション状況＋リスク設定             │
│  出力：BUY / SELL / HOLD ＋ 株数 ＋ 理由               │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│               注文実行 / ポジション管理                  │
│          Alpaca Trading API (Paper / Live)           │
│   成行注文・指値注文・損切りストップロス自動設定           │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│              ログ・パフォーマンス記録                    │
│                 Supabase (PostgreSQL)                │
│   取引履歴・損益・AI判断根拠・エラーログ                  │
└─────────────────────────────────────────────────────┘
```

---

## 月間コスト試算

| 項目 | 月額 |
|------|------|
| Claude Code（開発用） | $20 ≈ ¥3,000 |
| Anthropic API（AI判断） | ¥500〜2,000 |
| Alpaca API | 無料 |
| Render / GitHub Actions | 無料 |
| Supabase | 無料 |
| **合計** | **¥3,500〜5,000** |

---

## ディレクトリ構成（予定）

```
stockpilot/
├── CLAUDE.md              # この引き継ぎ資料
├── README.md
├── .env.example           # 環境変数テンプレート
├── requirements.txt
│
├── src/
│   ├── data/
│   │   └── fetcher.py     # Alpaca市場データ取得
│   ├── ai/
│   │   └── judge.py       # Claude APIによる判断ロジック
│   ├── trading/
│   │   └── executor.py    # Alpaca注文実行
│   ├── risk/
│   │   └── manager.py     # リスク管理・損切り設定
│   └── logger/
│       └── recorder.py    # Supabaseへのログ記録
│
├── backtest/
│   └── run_backtest.py    # バックテスト実行スクリプト
│
├── tests/
│   └── test_*.py
│
└── .github/
    └── workflows/
        └── trader.yml     # GitHub Actions cron設定
```

---

## 環境変数

`.env` に以下を設定（本番運用時は GitHub Secrets / Render Env Vars）

```env
# Alpaca
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets  # Paperの場合

# Anthropic
ANTHROPIC_API_KEY=your_key

# Supabase
SUPABASE_URL=your_url
SUPABASE_KEY=your_key

# リスク設定
MAX_POSITION_RATIO=0.2      # 1銘柄に資金の最大20%まで
MAX_DAILY_LOSS_JPY=3000     # 1日の最大損失額（円）
STOP_LOSS_PERCENT=0.03      # 3%下落で損切り
```

---

## 開発フェーズ

### ✅ Phase 0：設計・準備（完了）
- [x] システム設計・技術選定
- [x] Alpaca口座開設
- [x] Anthropic APIキー取得

### 🔄 Phase 1：ペーパートレード（現在）
- [ ] バックテストスクリプト実装
- [ ] Alpaca Paper APIとの接続確認
- [ ] Claude APIによる判断ロジック実装
- [ ] Supabaseへのログ記録実装
- [ ] GitHub Actionsでの自動実行設定
- [ ] 3ヶ月間のペーパートレード検証

### ⏳ Phase 2：本番移行（検証後）
- [ ] Paper → Live APIへの切り替え
- [ ] LINE/メールアラート実装
- [ ] モニタリングダッシュボード

---

## AIプロンプト設計方針

Claude APIへの判断依頼では以下の情報をコンテキストとして渡す：

```
- 直近30日のOHLCV
- テクニカル指標（移動平均5/25/75・RSI・MACD・ボリンジャーバンド）
- 現在のポジション状況・含み損益
- 利用可能な資金残高
- 最新ニュース（センチメント）
- リスク設定（最大ポジションサイズ・損切りライン）
```

出力はJSON形式で受け取る：
```json
{
  "action": "BUY | SELL | HOLD",
  "symbol": "AAPL",
  "quantity": 5,
  "reason": "判断根拠（ログ用）",
  "confidence": 0.75
}
```

---

## 注意事項・制約

- **必ずペーパートレードで3ヶ月以上検証してから本番移行する**
- AIの判断は完全ではなく、損失が発生する可能性がある
- 米国株市場時間：日本時間 23:30〜6:00（冬時間）/ 22:30〜5:00（夏時間）
- Alpaca無料枠のAPIレート制限に注意（200 req/min）
- 個人情報・APIキーは絶対にコミットしない

---

## 参考リンク

- [Alpaca APIドキュメント](https://docs.alpaca.markets/)
- [Anthropic APIドキュメント](https://docs.anthropic.com/)
- [Supabase ドキュメント](https://supabase.com/docs)
