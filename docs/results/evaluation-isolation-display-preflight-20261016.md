# 评审隔离与客户端显示测点运行前接线

## 授权与范围

2026-10-16用户要求按TODO推进评审隔离部署和客户端显示测点的运行前准备，先完成不依赖真实模型的核验与接线，实时更新TODO；禁止真实模型评测及真实test。起始Mac `ae4ccd15`、`feat/evaluation-development`、工作区干净。

本轮不创建正式eval/claim、不调用真实模型或启动Ollama、不部署真实账户或密钥、不改训练机及候选TensileAgent仓。合成软件检查和当前内核canary验证分别记录，不替代真实模型质量、GPU/E2E或独立账户部署证明。

## 评审隔离预检

既有 `finetune.eval_review.probe_review_isolation` 和 `prepare_isolated_actor_requests` 已实现受限worker，但正式评审入口依赖冻结eval/预测并会写exposed事实，不能拿来做无正式评测的准备。本轮复用这两个函数，新增独立显式预检入口，保持既有worker/profile和冻结provider字节不变。

入口为 `python -m finetune.eval_audit_isolation --run-probes --output /绝对路径/新报告.json`，无flag只显示帮助。只创建新普通0600输出，拒绝覆盖/symlink；报告绑定入口/worker/profile/解释器与sandbox字节。本机实际[预检报告](evaluation-review-isolation-preflight-20261016.json)记录8项内核canary全部通过，三个actor各生成2条匿名合成请求，包未改且各自输出只读，无broker调用。实现者实际CLI命令为 `.venv/bin/python -m finetune.eval_audit_isolation --run-probes --output docs/results/evaluation-review-isolation-preflight-20261016.json`，退出0，输出0600。输出必须明确synthetic、没有真实模型部署证明；失败非零，不生成成功凭据，不能导入为生产receipt。临时输入仅公开合成匿名回答，GT/凭据/peer canary均为临时文本。新增保护29项；实现者与既有holdout semantic/semantics联合运行92 passed（17.08秒、退出0），出现299条既有pytest临时目录清理warning，独立reviewer指定新basetemp分两组复跑：新29＋semantics28共57 passed（0.32秒）、holdout semantic35 passed（17.06秒），合计92项，均退出0且无warning。独立实际CLI再跑通过，8项canary/三actor/内容seal/0600均匹配；同路径覆盖退出1且原报告不变。

## 客户端回执桥接

本轮遵循既有 `versioning.performance_receipts` 协议和 `versioning.performance` receiver，补客户端薄适配：稳定请求ID/32-byte nonce/header、显式上传完成的单调ns起点、原身份重试、服务器backend签名校验、完整自动输出及显式显示完成回调、客户端注入签名器、严格回执envelope与finish。网络transport和签名器均显式注入，不决定真实密钥托管方式。

适配回调不能证明页面实际提交DOM。[候选客户端源码盘点](evaluation-client-source-inventory-20261016.json)记录6个实际tracked文件摘要、Git前后身份与只读边界。候选TensileAgent只读复核为 `codex/competition-demo-chat-mock@86e50c6544d0e92a9141bde6d16525c36d11ee8f`，仅未跟踪tmp未读；普通Agent任务包含多轮模型调用，其task_completed或SSE接收不能替代单次视觉自动请求的完整显示测点。当前不将普通Agent结果冒作正式性能样本。

模块为 `versioning.performance_client.PerformanceClientBridge`。调用方提供已有冻结plan、session token及signer/transport；`begin_request`分配身份，`request_headers`供原上传/重试复用，真实上传完成事件才调用`upload_complete`；完整raw到达后`receive_output`取并验服务器回执；外部显示完成回调确认相同raw与完整自动字段后`display_complete`封存签名，`submit_receipt`提交严格`{receipt: ...}`，全部处理后`finish`。签名失败重试保留首次显示时刻，transport失败保留原身份和失败台账；所有时间来自同一注入单调ns时钟，跨请求不回退。[合成闭环记录](evaluation-display-client-preflight-20261016.json)实际使用现有ControlledPerformanceSession ASGI receiver、stub loader/adapter、常量`b"media"`和仅测试内存中的临时Ed25519双密钥，走通上传header→backend签名验证→显式显示回调→客户端签名→服务回执核验→finish，无网络listener或模型。结果仍为synthetic，`e2e_verified=false`、`dom_render_verified=false`。

实现者执行 `.venv/bin/python -m pytest -q tests/test_performance_client.py tests/test_eval_performance.py --basetemp <新临时目录/work>`：新增47＋既有61共108 passed，2.66秒，退出0，stderr为空。早期新增caller-plan快照测试误改了服务重验共用fixture，曾1 failed/107 passed；改用独立caller-plan副本后两轮108通过，未改变生产门。覆盖早签/早提交、完整绑定与签名漂移、原文/字段、重试/失败分母、时钟倒退、签名失败保首次显示时刻及重复回执。独立reviewer以新basetemp另跑相同两文件：108 passed，2.75秒，退出0且无warning。

## 收尾检查

独立审查通过，无剩余可执行问题。reviewer另核isolation内容seal及全部源码/runtime绑定、client源摘要、候选外仓6个文件size/SHA/HEAD与tracked clean，均匹配；仅限本轮模型无关准备。223个本地链接/锚点、37个唯一任务ID、compileall及 `git diff --check` 通过；同次提交版本用 `git log -- finetune/eval_audit_isolation.py versioning/performance_client.py` 追溯。

## 当前限制及下一步

[项目TODO](../project-todo.md)是唯一台账。评审侧仍须核真实部署、独立上下文/账户边界及实际元数据；客户端仍须在适用跨库授权下把单次视觉请求、上传event与最终DOM测点接入，配置并冻结真实签名组件及源码版本，再取得适用真实运行授权。原生arm64服务、真实模型效果、真实客户端显示、GPU性能均未在本轮验证；C/D/E及MODEL-QUALITY不因准备完成关闭。
