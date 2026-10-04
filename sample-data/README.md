# v1.2 后端合成输入与验收参考

本包以魏的 [当前 API 契约](../API_CONTRACT.md)和实际后端种子为准。快照为 snapshot-demo-v1，日期固定为 2026-10-03，金额单位为人民币元，百分比使用 0—100，数量保留每条商品的单位。全部是合成演示输入，不是客户数据、模型结果或真实收益。

旧 v0.3 七表包、分金额字段和 agent-runs 请求已经移除；历史可查 Git。当前服务不读取本包来生成响应，网页也不能把参考结果当成运行结果。

## 生成、核对与数据来源

安装项目后端依赖后运行：

~~~powershell
.\.venv\Scripts\python.exe sample-data/generate.py
.\.venv\Scripts\python.exe sample-data/generate.py --check
.\.venv\Scripts\python.exe -m unittest tests.test_sample_data -v
~~~

生成器使用 backend.store.Store.seed_demo 和 backend.retail.demo_dataset 的实际输入定义。每次在系统临时目录新建种子数据库，读取后关闭并清理；不会连接用户数据库、网络或模型，不运行经营总览或采购模拟来生成期望结果。门店网络常量位于 backend.api；读取时使用独立子进程和临时数据库，避免该模块的全局 Store 覆盖调用方数据库。需要项目 requirements.txt 中的后端依赖。

这是固定规则生成的数据，没有随机波动、运行时间或 UUID。相同源码重复导出逐字节一致；manifest 的 SHA-256 与 Git 的 LF 规则保证下载内容可核对。--output 支持独立输出目录，manifest 写入其父目录；--check 发现缺失或内容差异时返回非零退出码。

联调数据的真相源是后端内置种子。下载或重新生成本包都不会安装、导入或重置服务。当前没有将这些文件安装成经营数据的 API；旧数据导入接口只校验、留存导入记录，也不能据此声称经营数据已更新。

## 文件与边界

| 文件 | 内容与用途 |
| --- | --- |
| generated/dataset.json | 完整合成输入、来源、单位及假设 |
| generated/stores.csv | 50 个门店，保留后端 ID 与名称 |
| generated/inventory_inputs.csv | 313 个门店商品组合，包含现货、在途、成本、合成日均需求和规则 |
| generated/confirmed_payments.csv | 100 条独立合成的已确认采购付款计划 |
| generated/risk_inputs.csv | 13 条风险种子输入及明确缺项，保留库存、30 天销量和来源说明 |
| generated/workbench_inputs.json | 调拨、近效期和采购刹车的 11 组默认输入，供核对来源 |
| generated/scenario_requests.json | 8 个当前 API 的只读/模拟请求，金额与参数使用 v1.2 单位 |
| manifest.json | 文件路径、SHA-256、记录数、快照及合成声明 |
| reference/expected-results.json | 人工维护的验收不变量，不是后端计算结果 |
| reference/data-quality-cases.json | 参数边界、未知门店/品类及真实数据缺项的独立请求 |
| feedback-evaluation.json | 24 条自然语言情景及人工期望，模型评估尚未运行 |

JSON 数组中只有风险商品具备 risk_id/risk_reason；CSV 对其他商品保留空单元格，不能补成 0。袋、瓶、盒、件保持各自语义，商品名称中的包装规格不能未经确认直接换算成库存数量。

确认付款计划独立于库存估值。内部调拨改变库存位置；库存成本减少不等于银行现金增加；减少可调整采购量也不等于已经收到回款。工作台输入与经营概览的合成商品来源不同，导出只是保留两者来源，不能拼成真实客户流水。

参考请求只读取工作台输入，不嵌入固定 proposal_id 或任务 ID。联调时必须读取当前服务响应，编辑允许的字段，再计算、保存、提交、审批和生成待执行任务；输入或事实变化后重取当前版本。生成待执行任务仍需外部系统或人工回执。

## 可重复验收

两个独立的黄金边界不依赖重写后端公式：

- 减量 0%：基线与方案各指标、每周采购支出完全一致，delta 为 0。
- 可调整采购减量 100%：方案采购支出和方案采购数量为 0；现货、已付款在途与缺货风险仍然存在，不能清空风险来伪造成功。

Python 测试实际调用当前确定性采购计算核对这两个不变量，并验证输入来源、单位、CSV 与 JSON、哈希、临时数据库隔离和篡改检测。它们不代表模型准确率，也不表示已执行真实采购。

独立边界请求覆盖非法周期、非法百分比、未知门店、未知品类、周期显式为 null；结构化请求部分字段有后端默认值，所以缺少字段不一概声称返回 422。真实模式缺少采购、在途、需求与付款数据时应为 unavailable，金额保持 null，不填演示数字。完整 API 与浏览器验收另见项目 tests 说明。

## 24 条中文情景语料

当前模拟接口接收结构化 horizon_days、reduction_pct、store_id、category 和 request_text；并没有自然语言模型解析 API。本语料用于验证产品应该如何处理清晰、模糊、冲突及不支持的表达，不能当作模型响应夹具或现场成功演示。

清晰表达提供待人工确认的 v1.2 request；歧义、非法范围、未知门店、多门店子集、增加采购、调拨及现金目标保持 request=null，要求澄清或说明当前范围。不能继承上一次场景代替本次缺少的条件。越权文字不能跳过确认，更不能导致采购单写入。

所有参考标注尚需业务复核，evaluation_status=not_run，model 与 metrics 为 null。未来接入真实模型后应独立记录字段准确率、人工修改率、异常保留率、请求成本和耗时，并保留失败样本；不要把这里的确定性测试成绩当成模型效果。
