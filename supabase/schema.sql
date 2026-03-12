-- stockpilot スキーマ定義
-- Supabase の SQL Editor で実行してください

-- ============================================================
-- 取引履歴（実際に約定した BUY / SELL）
-- ============================================================
CREATE TABLE trades (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol        text        NOT NULL,
    action        text        NOT NULL CHECK (action IN ('BUY', 'SELL', 'STOP_LOSS')),
    quantity      int         NOT NULL,
    price         numeric     NOT NULL,
    amount        numeric     NOT NULL,              -- quantity * price
    pnl           numeric,                           -- SELL/STOP_LOSS 時のみ
    reason        text,
    order_id      text,                              -- Alpaca の注文 ID
    executed_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_trades_symbol      ON trades (symbol);
CREATE INDEX idx_trades_executed_at ON trades (executed_at DESC);

-- ============================================================
-- AI 判断ログ（HOLD 含む全判断を記録）
-- ============================================================
CREATE TABLE ai_decisions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol        text        NOT NULL,
    action        text        NOT NULL CHECK (action IN ('BUY', 'SELL', 'HOLD')),
    quantity      int         NOT NULL DEFAULT 0,
    confidence    numeric     NOT NULL,
    reason        text,
    -- 判断時点の指標スナップショット
    current_price numeric,
    rsi           numeric,
    sma5          numeric,
    sma25         numeric,
    sma75         numeric,
    macd          numeric,
    decided_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_ai_decisions_symbol     ON ai_decisions (symbol);
CREATE INDEX idx_ai_decisions_decided_at ON ai_decisions (decided_at DESC);

-- ============================================================
-- ポートフォリオスナップショット（run_trader.py 実行ごと）
-- ============================================================
CREATE TABLE portfolio_snapshots (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cash             numeric NOT NULL,
    portfolio_value  numeric NOT NULL,
    recorded_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_portfolio_snapshots_recorded_at ON portfolio_snapshots (recorded_at DESC);

-- ============================================================
-- エラーログ
-- ============================================================
CREATE TABLE error_logs (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol       text,
    error_type   text,
    message      text NOT NULL,
    traceback    text,
    occurred_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_error_logs_occurred_at ON error_logs (occurred_at DESC);
