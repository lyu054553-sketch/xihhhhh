# zmj 本次验收记录

验收日期：2026-10-02。环境：Windows、Python 3.13.2、Node.js v24.14.0、Chromium。范围为朱负责的前端、合成场景、测试与演示交付；不作为真实模型或生产 ERP 的验收结论。

## 实际执行结果

| 验证 | 结果 |
| --- | --- |
| `node --test tests/test_frontend_api.mjs tests/test_data_center.mjs` | 24 项通过 |
| `unittest discover -s tests -v` 的同参数入口 | 最终一轮 61 项通过，61.002 秒、退出码 0；其中浏览器 17 项、规则与样例 44 项 |
| `python sample-data/generate.py --check` | 固定种子生成包与清单一致 |
| Windows Git 检出后的生成包 | 8 个文件的字节与 SHA-256 保持一致；由 `.gitattributes` 固定生成文件换行 |
| `node --check app.js`、`git diff --check` | 通过 |
| `start.ps1 -Check` | 输出独立 demo 库路径，不创建数据库、不安装依赖、不启动服务 |
| 真实模式启动配置 | 用临时最小快照库验证只读检查，检查前后文件哈希一致；不是实库业务验收 |
| PowerPoint 与 HTML 演示稿 | 8 页、逐页讲稿、形状边界检查通过；HTML 首屏已检查 |

安装与复现命令见[测试说明](../tests/README.md)。每个浏览器用例使用独立服务、临时 SQLite 数据库与随机端口，结束后清理，不复用日常演示库。测试隔离避免不同用例的请求相互污染。

本次使用新工作树的 `.venv` Python，浏览器测试通过 `site.addsitedir` 读取本机已安装的 Playwright，并使用已安装的 Chromium；没有修改原项目的虚拟环境。复现时可按测试说明直接在新 `.venv` 安装开发依赖和浏览器。

本机实际入口为 `unittest.main(module=None, argv=['unittest', 'discover', '-s', 'tests', '-v'])`，测试发现参数与上表一致；外层 `TemporaryDirectory` 提供临时数据库，结束时在 `finally` 中关闭 `backend.api.store`。该环境说明不表示已在新虚拟环境完整安装 `requirements-dev.txt`。

## 已覆盖的交互

- 五个业务入口及规则模式、合成数据标记。
- 反馈原文与返回草稿并列核对，人工确认后更新事实版本。
- 调拨约束错误、输入变更失效、草稿与计算顺序、保存审批、创建执行草稿。
- 接口错误、空列表、延迟响应和快速切换；旧响应不能覆盖当前选择。
- 真实模板下载、多个 CSV 文件的字段校验、错误文件记录；导入后分析快照保持不变。
- 真实模式及缺快照时禁止前端演示重置；本页面详情请求未完成时禁用重置，请求完成后允许重置。
- 390 × 844 的总览、五个入口及数据中心，无整页横向溢出；表格在自身容器内横向滚动。另检查了 1440 像素桌面总览和调拨页面。

## 演示证据

[自动化流程录像](demo-recording/demo-flow.webm)使用真实本地 API 与合成数据，记录调拨测算、人工审批到创建执行草稿；另有[最后一屏截图](demo-recording/demo-flow.png)，尺寸为 1440 × 1000。

这是无旁白的自动化操作实录。五分钟讲解按[演示脚本](DEMO_RUNBOOK.md)和 [PowerPoint](DEMO_SLIDES.pptx)逐页讲稿录制；录像没有证明外部 ERP 已执行或客户已获得收益。

## 尚未通过本次验收的能力

真实模型未接入。[24 条反馈评测语料](../sample-data/feedback-evaluation.json)只完成结构、标注引用与覆盖检查，参考答案待业务复核，模型准确率、人工修改率等指标仍为未测。

联调曾在并行 GET 与演示重置时复现后端 `NoneType` / `InterfaceError`。当前页通过在途请求计数和重置互斥控制本页面时序；不同标签页或客户端的共享连接、事务、重置锁和版本冲突仍需魏处理。独立测试实例不代表这些服务端问题已经解决。

真实模式的服务端重置保护、受控静态资源、鉴权、真实模型、ERP 执行及外部回执仍按[集成说明](FRONTEND_INTEGRATION.md)交接，不包含在上述通过数量的保证中。
