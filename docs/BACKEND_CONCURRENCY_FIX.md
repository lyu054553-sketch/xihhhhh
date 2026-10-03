# `/proposals`、`/work-items` 并发 HTTP 500 修复

日期：2026-10-03。问题来源：[朱的交付清单](https://github.com/lyu054553-sketch/xihhhhh/blob/zmj/docs/ZHU_DELIVERY.md)及其联调记录。修复基于本地 `lanyangyang` 的 `04fb293`；保留该提交已有的幂等键隔离修复。

## 原因与处理

`backend.api` 在模块加载时创建全局 `Store`。所有 FastAPI 同步路由的工作线程共用 `Store.conn`，但原实现没有同步保护。`check_same_thread=False` 只是允许跨线程使用连接，不能代替互斥。在没有写入、重置或浏览器的临时种子库中，仅并发 GET 就能得到错误记录、null JSON 和 `sqlite3.InterfaceError: bad parameter or other API misuse`。因此不应通过前端串行请求、重试、把 null 当空值或隐藏错误处理。

`backend/store.py` 为每个 Store 增加一个 `RLock`，数据库方法通过 `_serialized` 保护整个操作：从 execute、fetch、行转换直到提交及返回结果。多语句写入、重置、种子初始化、关闭连接也使用同一把锁，避免只锁查询却让其他线程插入操作。方法之间会嵌套调用，因此使用可重入锁；不在 API 请求线程间传递锁所有权。

前端仍然并发读取，HTTP/API 契约和数据库结构保持原样，没有新增运行时依赖。以后新增访问连接的方法也应使用此保护；服务代码不要绕过 Store 直接访问 conn。

## 实测

本机 macOS、Python 3.14.7、SQLite 3.53.4；这些结果不冒充原记录的 Windows/Python 3.13.2 环境。

| 检查 | 修复前 | 修复后 |
| --- | --- | --- |
| 独立临时库串行读取 | 45/45 HTTP 200 | 45/45 HTTP 200 |
| 9 线程、150 次并发 GET | 48 次 HTTP 500（proposals 23、work-items 25） | 150/150 HTTP 200 |
| 32 线程、300 次并发 GET | 未额外运行 | 300/300 HTTP 200，JSON 与各接口串行基准完全一致 |
| 后端 unittest 全套 | 未在本轮运行 | 56/56 通过，含新增 2 项并发回归 |
| zmj 实际后端浏览器全套 | 原交付记录 26 通过、1 error | 27/27 通过；原失败的今日待办用例通过 |

浏览器验证使用 `origin/zmj` 的 `f10d900` 文件归档及修复后的 `backend/store.py`，实际 FastAPI、独立临时数据库、随机本地端口、前端代理与 Chromium；没有替换 API 成功响应。上述是本地复验，远程分支与原交付文档没有被改写。

新增 `tests/test_backend_concurrency.py` 检查真实 HTTP 并发响应及内容一致性，并验证 9 个线程使用相同幂等键审批/生成任务最终只有一条审批和一条任务；后者防止退化为只锁 one/rows、仍让写操作交错的实现。

## 复验命令

在修复分支的仓库根目录，用安装了 requirements.txt 及 httpx 的 Python 3.10+ 环境执行：

```bash
python -m unittest tests.test_backend_concurrency -v
python scripts/reproduce_backend_concurrency.py
python scripts/reproduce_backend_concurrency.py --workers 32 --rounds 100
```

复现脚本沿用 zmj 的独立后端脚本，并增加 JSON 内容对照、启动失败日志与有界子进程清理。只创建、关闭和清理自己的服务与临时数据库；测试失败返回非零退出码。

接入 zmj 后，可按该分支 tests/README.md 安装开发依赖和 Chromium，再运行：

```bash
python -m unittest tests.test_frontend_browser -v
```

## 范围

这是当前单连接本地原型的并发正确性修复，同一个 Store 的数据库操作互斥。它不提供跨进程事务或 HTTP 整个响应的统一快照，也不增加服务端 expected_version、身份认证或旧方案失效规则；这些仍是独立后续工作。需要更高数据库吞吐时，应另行设计每请求连接及明确事务边界，不直接去掉此锁。
