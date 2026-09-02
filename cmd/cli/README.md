
## 运行client必备条件
* 启动服务
docker compose up -d

* 编译client
go build -o client .

* 配置
```
配置客户端环境变量，使用localhost通信。（默认为容器内通信）
export COLLECTOR_BASE_URL=http://localhost:8000
export DATABASE_URL="postgres://fundforge:fundforge_dev_password@localhost:5432/fundforge?sslmode=disable"
```

## client支持的操作
* Fund management

| Commands                         | example                          | collector api        | table     |
| -------------------------------- | -------------------------------- | -------------------- | --------- |
| Subscribe to a fund              | ./client fund subscribe 519770   | /api/funds/%s/detail | fund_info |
| Unsubscribe from a fund          | ./client fund unsubscribe 519770 | -                    | fund_info |
| Search funds by code/name/pinyin | ./client fund search 519770      | -                    | fund_info |
| List subscribed funds            | ./client fund list               | -                    | fund_info |


* Data synchronization

| Commands                                        | example                  | collector api                            | table                              |
| ----------------------------------------------- | ------------------------ | ---------------------------------------- | ---------------------------------- |
| Sync trade calendar                             | ./client sync calendar   | /api/trade-calendar                      | trade_calendar                     |
| Sync dividends and splits                       | ./client sync dividends  | /api/funds/dividends,/api/funds/splits   | fund_info,fund_dividend,fund_split |
| Detect fund manager changes                     | ./client sync managers   | /api/funds/%s/detail                     | fund_info                          |
| Fetch historical NAV for a fund                 | ./client sync nav 519770 | /api/funds/%s/nav?indicator=%s&period=%s | fund_info,fund_nav                 |
| Incremental NAV update for all subscribed funds | ./client sync update     | /api/funds/%s/nav?indicator=%s&period=%s | fund_info,fund_nav                 |

* Strategy management

| Commands                  | example                           | collector api | table             |
| ------------------------- | --------------------------------- | ------------- | ----------------- |
| List all strategies       | ./client strategy list            | -             | strategy_template |
| Bind strategy to fund     | ./client strategy bind 1 519770   | -             | strategy_binding  |
| List bindings for a fund  | ./client strategy bindings 519770 | -             | strategy_binding  |
| Unbind strategy from fund | ./client strategy unbind 1 519770 | -             | strategy_binding  |

* Strategy analysis

| Commands                                  | example                            | collector api | table                                                                                             |
| ----------------------------------------- | ---------------------------------- | ------------- | ------------------------------------------------------------------------------------------------- |
| Run analysis on a single fund             | ./client analyze run 519770        | -             | fund_info,fund_nav,benchmark_index,benchmark_index_daily,strategy_binding,strategy_template,alert |
| Compute and display indicators for a fund | ./client analyze indicators 519770 | -             | fund_nav, fund_info,benchmark_index, benchmark_index_daily                                        |
| Run full analysis on all subscribed funds | ./client analyze all               | -             | fund_info,fund_nav,benchmark_index,benchmark_index_daily,strategy_binding,strategy_template,alert |

* Alert management

| Commands           | example                  | collector api | table |
| ------------------ | ------------------------ | ------------- | ----- |
| List active alerts | ./client alert list      | -             | alert |
| Confirm an alert   | ./client alert confirm 1 | -             | alert |
| Ignore an alert    | ./client alert ignore 1  | -             | alert |

* Run database migrations
```
export MIGRATIONS_PATH="file:///a/b/c/migrations"
./client migrate
```