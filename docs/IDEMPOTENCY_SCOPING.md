# 幂等键作用域修复说明

> 本文保留原幂等作用域修复的历史记录，54 项结果及下文“本批未完成”只对应当时批次，不代表当前代码。后续已增加事务、版本冲突检查和 32 并发防重验证，见 [后端交付](backend/DELIVERY_20261003.md) 与 [审查修复](backend/REVIEW_FIXES_20261003.md)。可信身份仍未实现；A0 身份契约在单独的 codex/a0-auth-boundary 分支，不在 lanyangyang 当前源码包内。

## 问题

审批、执行任务的幂等键由客户端通过 `Idempotency-Key` 请求头提供，而表上的 `UNIQUE` 约束是全局的，
查询又只按键匹配。结果是：租户 B 使用与租户 A 相同的键，会拿到 A 的审批或执行记录，也可能占用 A 的键。

## 修复内容（仅限 `backend/store.py`）

- `Store._scoped_idem()`：落库前把 `[租户, 操作类型, 方案 id, 客户端键]` 编码为 JSON 数组。
  租户和客户端键是自由文本，可含分隔符，JSON 编码保证字段边界无歧义（有专门测试）。
- `approve()` / `execute()` 查询幂等记录时增加 `AND tenant_id=?`。
- `execute()` 更新方案状态时增加 `AND tenant_id=?`（纵深防御，方案 id 本身全局唯一，无法单独触发）。
- 未修改表结构，未删除或重置任何数据。

## 兼容性变化：旧格式幂等键

已有数据库里，用旧格式（裸客户端键，或 `approve|<方案>|<版本>`）存下的键，不会被新查询命中。
后果：对一个**已经**审批或已生成任务的方案，用旧键重试时，不会返回旧记录，
而是走正常状态检查，收到“方案已不在待审批状态”之类的错误；不会重复创建记录。
旧记录原样保留。仅有演示数据的环境不受影响；若存在真实数据，需知晓此行为。

## 本批未完成

- **可信身份**：审批人仍落到默认的 `demo-user`，租户仍来自请求头，见 `docs/A0_AUTH_CONTRACT.md`。
- **请求内容冲突检查**：同一键对应不同请求内容时尚未拒绝，目前只按租户、操作、方案隔离。
- **并发防重**：未验证。现有“先查询、再插入”在并发下仍可能竞态，仅靠全局 `UNIQUE` 兜底（冲突时会报错而非返回旧结果）。

## 开发依赖与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt httpx
.venv/bin/python -m unittest discover -s tests -t .
```

系统 Python 若未装 `fastapi`、`openpyxl`，`test_retail`、`test_workbenches` 会因导入失败报错，与本次改动无关。
`httpx` 为 FastAPI `TestClient` 所需，未列入 `requirements.txt`。

## 本次测试结果（2026-10-03）

- 新增 `tests/test_idempotency_isolation.py`：6 项。修复前 4 项失败（含 1 项编码歧义），修复后全部通过。
- 全量回归：54 项，全部通过，0 失败，0 报错。
