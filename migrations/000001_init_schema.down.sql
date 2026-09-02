-- Rollback: drop all tables in reverse dependency order

DROP TABLE IF EXISTS portfolio_holding CASCADE;
DROP TABLE IF EXISTS portfolio CASCADE;
DROP TABLE IF EXISTS alert CASCADE;
DROP TABLE IF EXISTS strategy_binding CASCADE;
DROP TABLE IF EXISTS strategy_template CASCADE;
DROP TABLE IF EXISTS benchmark_index_daily CASCADE;
DROP TABLE IF EXISTS benchmark_index CASCADE;
DROP TABLE IF EXISTS fund_holding_bond CASCADE;
DROP TABLE IF EXISTS fund_holding_stock CASCADE;
DROP TABLE IF EXISTS fund_manager_change CASCADE;
DROP TABLE IF EXISTS fund_split CASCADE;
DROP TABLE IF EXISTS fund_dividend CASCADE;
DROP TABLE IF EXISTS fund_money_nav CASCADE;
DROP TABLE IF EXISTS fund_nav CASCADE;
DROP TABLE IF EXISTS fund_info CASCADE;
DROP TABLE IF EXISTS trade_calendar CASCADE;
