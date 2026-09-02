-- ============================================================
-- FundForge (An AI Agent for fund investment research and portfolio decision support) - Database Schema
-- Version: 1.0
-- Database: PostgreSQL 15+
-- ============================================================

-- 启用 UUID 扩展（可选，目前主键用 BIGSERIAL）
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================
-- 1. 交易日历
-- ============================================================
CREATE TABLE trade_calendar (
    trade_date DATE PRIMARY KEY,
    is_trading_day BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE trade_calendar IS 'A股交易日历，来源 tool_trade_date_hist_sina';

-- ============================================================
-- 2. 基金基本信息
-- ============================================================
CREATE TABLE fund_info (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL UNIQUE,
    fund_name VARCHAR(200) NOT NULL,
    fund_type VARCHAR(50),                   -- 混合型-灵活、股票型、债券型等
    pinyin_abbr VARCHAR(50),                 -- 拼音缩写
    pinyin_full VARCHAR(200),                -- 拼音全称

    -- 详情字段（来自 fund_individual_basic_info_xq）
    fund_company VARCHAR(200),               -- 基金公司
    fund_manager VARCHAR(200),               -- 基金经理（可能多人，逗号分隔）
    fund_size DECIMAL(20, 4),                -- 基金规模（亿元）
    fund_size_date DATE,                     -- 规模统计日期
    establish_date DATE,                     -- 成立日期
    custodian_bank VARCHAR(200),             -- 托管银行
    management_fee_rate DECIMAL(6, 4),       -- 管理费率 %
    custodian_fee_rate DECIMAL(6, 4),        -- 托管费率 %
    benchmark VARCHAR(500),                  -- 业绩基准

    -- 订阅状态
    is_subscribed BOOLEAN NOT NULL DEFAULT TRUE,
    subscribed_at TIMESTAMPTZ,
    unsubscribed_at TIMESTAMPTZ,

    -- 数据抓取状态
    initial_fetch_done BOOLEAN NOT NULL DEFAULT FALSE,
    last_nav_date DATE,                      -- 最新净值日期
    last_fetch_at TIMESTAMPTZ,               -- 最近一次数据抓取时间

    -- 自定义基准指数
    custom_benchmark_code VARCHAR(20),       -- 用户自定义基准指数代码

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fund_info_subscribed ON fund_info(is_subscribed) WHERE is_subscribed = TRUE;
CREATE INDEX idx_fund_info_type ON fund_info(fund_type);

COMMENT ON TABLE fund_info IS '基金基本信息与订阅状态';

-- ============================================================
-- 3. 基金净值历史
-- ============================================================
CREATE TABLE fund_nav (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    nav_date DATE NOT NULL,                  -- 净值发布日期
    unit_nav DECIMAL(12, 4),                 -- 单位净值
    acc_nav DECIMAL(12, 4),                  -- 累计净值
    daily_return DECIMAL(10, 4),             -- 日涨跌幅 %
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),  -- 数据抓取时间

    UNIQUE(fund_code, nav_date)
);

CREATE INDEX idx_fund_nav_code_date ON fund_nav(fund_code, nav_date DESC);

COMMENT ON TABLE fund_nav IS '基金每日净值数据';

-- ============================================================
-- 4. 货币基金数据（万份收益、7日年化）
-- ============================================================
CREATE TABLE fund_money_nav (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    nav_date DATE NOT NULL,
    income_per_ten_thousand DECIMAL(10, 4),   -- 万份收益
    seven_day_yield DECIMAL(10, 4),           -- 7日年化收益率 %
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(fund_code, nav_date)
);

COMMENT ON TABLE fund_money_nav IS '货币基金收益数据';

-- ============================================================
-- 5. 分红记录
-- ============================================================
CREATE TABLE fund_dividend (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    fund_name VARCHAR(200),
    record_date DATE,                        -- 权益登记日
    ex_date DATE,                            -- 除息日
    dividend_per_unit DECIMAL(12, 6),        -- 每份分红（元）
    pay_date DATE,                           -- 发放日
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(fund_code, ex_date, dividend_per_unit)
);

CREATE INDEX idx_fund_dividend_code ON fund_dividend(fund_code);

COMMENT ON TABLE fund_dividend IS '基金分红记录';

-- ============================================================
-- 6. 拆分记录
-- ============================================================
CREATE TABLE fund_split (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    fund_name VARCHAR(200),
    split_date DATE NOT NULL,                -- 拆分折算日
    split_type VARCHAR(50),                  -- 拆分类型
    split_ratio DECIMAL(12, 6),              -- 拆分比例
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(fund_code, split_date)
);

CREATE INDEX idx_fund_split_code ON fund_split(fund_code);

COMMENT ON TABLE fund_split IS '基金拆分记录';

-- ============================================================
-- 7. 基金经理变更日志
-- ============================================================
CREATE TABLE fund_manager_change (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), -- 检测到变更的时间
    previous_manager VARCHAR(200),
    current_manager VARCHAR(200),
    change_date DATE,                        -- 估计变更日期（检测日期）

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_fund_manager_change_code ON fund_manager_change(fund_code);

COMMENT ON TABLE fund_manager_change IS '基金经理变更检测记录';

-- ============================================================
-- 8. 基金持仓（股票）
-- ============================================================
CREATE TABLE fund_holding_stock (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,               -- 报告期（如 2024-06-30）
    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100),
    hold_ratio DECIMAL(8, 4),                -- 占净值比例 %
    hold_shares DECIMAL(20, 2),              -- 持股数（万股）
    hold_value DECIMAL(20, 2),               -- 持股市值（万元）
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(fund_code, report_date, stock_code)
);

CREATE INDEX idx_fund_holding_stock_code ON fund_holding_stock(fund_code, report_date);

COMMENT ON TABLE fund_holding_stock IS '基金股票持仓（季频）';

-- ============================================================
-- 9. 基金持仓（债券）
-- ============================================================
CREATE TABLE fund_holding_bond (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    report_date DATE NOT NULL,
    bond_code VARCHAR(20) NOT NULL,
    bond_name VARCHAR(200),
    hold_ratio DECIMAL(8, 4),                -- 占净值比例 %
    hold_value DECIMAL(20, 2),               -- 持仓市值（万元）
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(fund_code, report_date, bond_code)
);

CREATE INDEX idx_fund_holding_bond_code ON fund_holding_bond(fund_code, report_date);

COMMENT ON TABLE fund_holding_bond IS '基金债券持仓（季频）';

-- ============================================================
-- 10. 基准指数
-- ============================================================
CREATE TABLE benchmark_index (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL UNIQUE,
    index_name VARCHAR(200) NOT NULL,
    applicable_fund_types TEXT[],             -- 适用的基金类型数组
    is_default BOOLEAN NOT NULL DEFAULT FALSE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE benchmark_index IS '基准指数信息';

-- 预置基准指数
INSERT INTO benchmark_index (index_code, index_name, applicable_fund_types, is_default) VALUES
    ('000300', '沪深300', ARRAY['股票型', '混合型-偏股', '混合型-灵活'], TRUE),
    ('000905', '中证500', ARRAY['股票型'], FALSE),
    ('000012', '中证全债', ARRAY['债券型', '债券型-混合一级', '债券型-混合二级'], TRUE),
    ('399006', '创业板指', ARRAY['股票型'], FALSE);

-- ============================================================
-- 11. 基准指数每日数据
-- ============================================================
CREATE TABLE benchmark_index_daily (
    id BIGSERIAL PRIMARY KEY,
    index_code VARCHAR(20) NOT NULL,
    trade_date DATE NOT NULL,
    close_price DECIMAL(12, 4) NOT NULL,     -- 收盘价/点位
    daily_return DECIMAL(10, 4),             -- 日涨跌幅 %
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(index_code, trade_date)
);

CREATE INDEX idx_benchmark_daily_code_date ON benchmark_index_daily(index_code, trade_date DESC);

COMMENT ON TABLE benchmark_index_daily IS '基准指数每日行情';

-- ============================================================
-- 12. 策略模板
-- ============================================================
CREATE TABLE strategy_template (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning'
        CHECK (severity IN ('info', 'warning', 'critical')),

    -- 策略条件（JSONB 存储）
    -- 格式: {"logic": "AND"|"OR", "conditions": [{"indicator": "max_drawdown_1y", "operator": "<=", "threshold": -15}, ...]}
    conditions JSONB NOT NULL,

    cooldown_days INT NOT NULL DEFAULT 7,    -- 冷却期（天）
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    is_preset BOOLEAN NOT NULL DEFAULT FALSE, -- 是否系统预置

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE strategy_template IS '策略模板';

-- 预置策略
INSERT INTO strategy_template (name, description, severity, conditions, cooldown_days, is_preset) VALUES
    ('回撤告警', '近1年最大回撤超过阈值', 'critical',
     '{"logic": "AND", "conditions": [{"indicator": "max_drawdown_1y", "operator": "<=", "threshold": -15}]}',
     7, TRUE),
    ('规模萎缩', '最新规模较上季度下降超过阈值', 'warning',
     '{"logic": "AND", "conditions": [{"indicator": "size_change_quarterly_pct", "operator": "<=", "threshold": -20}]}',
     30, TRUE),
    ('基金经理变更', '检测到基金经理发生变更', 'critical',
     '{"logic": "AND", "conditions": [{"indicator": "manager_changed", "operator": "==", "threshold": true}]}',
     365, TRUE),
    ('波动率过高', '年化波动率超过阈值', 'warning',
     '{"logic": "AND", "conditions": [{"indicator": "annual_volatility", "operator": ">=", "threshold": 30}]}',
     14, TRUE),
    ('高风险复合', '回撤大且波动率高', 'critical',
     '{"logic": "AND", "conditions": [{"indicator": "max_drawdown_1y", "operator": "<=", "threshold": -15}, {"indicator": "annual_volatility", "operator": ">=", "threshold": 25}]}',
     7, TRUE);

-- ============================================================
-- 13. 策略-基金绑定
-- ============================================================
CREATE TABLE strategy_binding (
    id BIGSERIAL PRIMARY KEY,
    strategy_id BIGINT NOT NULL REFERENCES strategy_template(id) ON DELETE CASCADE,
    fund_code VARCHAR(10) NOT NULL,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(strategy_id, fund_code)
);

CREATE INDEX idx_strategy_binding_fund ON strategy_binding(fund_code);

COMMENT ON TABLE strategy_binding IS '策略模板与基金的绑定关系';

-- ============================================================
-- 14. 告警记录
-- ============================================================
CREATE TABLE alert (
    id BIGSERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    strategy_id BIGINT NOT NULL REFERENCES strategy_template(id),

    -- 告警状态机: triggered -> confirmed -> recovered
    --                      -> ignored
    status VARCHAR(20) NOT NULL DEFAULT 'triggered'
        CHECK (status IN ('triggered', 'confirmed', 'ignored', 'recovered')),
    severity VARCHAR(20) NOT NULL DEFAULT 'warning'
        CHECK (severity IN ('info', 'warning', 'critical')),

    -- 触发详情
    data_date DATE NOT NULL,                 -- 分析数据截止日期
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recovered_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ,

    -- 指标快照（触发时的实际指标值）
    indicator_snapshot JSONB,
    -- 例: {"max_drawdown_1y": -18.5, "annual_volatility": 28.3}

    -- 策略条件快照（防止策略修改后无法追溯）
    condition_snapshot JSONB,

    message TEXT,                             -- 生成的告警消息文本

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alert_fund_status ON alert(fund_code, status);
CREATE INDEX idx_alert_triggered_at ON alert(triggered_at DESC);
CREATE INDEX idx_alert_strategy_fund ON alert(strategy_id, fund_code, triggered_at DESC);

COMMENT ON TABLE alert IS '策略告警记录（含状态机）';

-- ============================================================
-- 15. 虚拟组合（预留）
-- ============================================================
CREATE TABLE portfolio (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    benchmark_code VARCHAR(20),              -- 组合基准指数

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE portfolio IS '虚拟持仓组合（预留）';

-- ============================================================
-- 17. 组合持仓（预留）
-- ============================================================
CREATE TABLE portfolio_holding (
    id BIGSERIAL PRIMARY KEY,
    portfolio_id BIGINT NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    fund_code VARCHAR(10) NOT NULL,
    shares DECIMAL(20, 4),                   -- 持有份额
    cost_price DECIMAL(12, 4),               -- 成本价（单位净值）
    added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(portfolio_id, fund_code)
);

COMMENT ON TABLE portfolio_holding IS '组合持仓明细（预留）';

