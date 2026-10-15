# 真实运行前环境与资产核验

## 授权、范围与证据

2026-10-15 用户授权在 TODO 下核验评审模型、tokenizer受审映射和客户端显示测点，完成可独立准备；暂不运行真实模型评测或使用真实test。起始Mac代码 `6a92ca3b`，工作区干净，分支 `feat/evaluation-development`。本轮不创建正式eval、claim、exposed或部署receipt，不调用生成/嵌入接口，不启动模型、安装依赖、下载资产、改动TensileAgent或训练机，不push/merge。此次本机核验不刷新训练机2026-10-13的历史环境结论。

模型元数据快照见[机器可读库存](evaluation-readiness-model-inventory-20261015.json)。它只记录当前库存，不是可信部署或模型效果证明。代码提交以 `git log -- docs/results/evaluation-readiness-20261015.md` 追溯。核验由不同scouter分别读取模型/缓存、映射/环境、客户端源码，主Agent汇总；最终独立核查另记。

## 评审模型：库存匹配，tokenizer与部署仍未就绪

本机 `/usr/local/bin/ollama` 和既有服务可用，元数据版本为 `0.33.1`。只请求固定loopback的 `/api/version`、`/api/tags`、`/api/ps`、`/api/show`；未请求generate/chat/embed/pull或启动服务。观察时 `/api/ps` 为空，没有驻留模型。

| 冻结标签 | 当前完整摘要 | show模板SHA256 |
| --- | --- | --- |
| qwen3.5:9b | `6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7` | `b507b9c2f6ca642bffcd06665ea7c91f235fd32daeefdf875a0f938db05fb315` |
| ornith-1.5:9b | `e5df7dcdd8a263994df62d610317e07be0d6af23f96fcbd8543273058fce575e` | `f55f52930aa8bf44ab5cb85f99370fcc3c56e9a85640b812086d5330bce5d86b` |

两标签digest与冻结代码一致，标准Ollama目录中manifest原字节SHA也一致；manifest声明的全部blob均在场且大小相同。随后在55秒限时内完成全部7个唯一blob的流式SHA256复验，耗时6.6秒；摘要、manifest声明大小及前后inode/mtime/size均一致，未哈希项0。详见[blob字节校验](evaluation-readiness-blob-integrity-20261015.json)。初始元数据快照仍保留 `content_rehashed:false`，表示该快照步骤未做整文件哈希；后续字节证据不改写初始观察。show没有提供可用的tokens/merges数组，不能用show结果自行证明GGUF与HF分词等价。

## tokenizer来源、依赖与受审映射

限定检查本仓非数据/非测试源码资产及标准HF缓存，未找到两个批准评审模型对应的完整HF tokenizer与真实受审映射。HF_HOME/HUGGINGFACE_HUB_CACHE/TRANSFORMERS_CACHE未设置。已有Qwen3-VL、MiniCPM系列缓存或本仓MiniCPM tokenizer属于其他模型，不能替代。本结论是已知位置的核验结果，不是全盘不存在证明；Ollama内容寻址blob在场与独立HF tokenizer缺失可同时成立。

本仓Python3.11 `.venv` 缺少 `transformers` 与 `tokenizers` distribution，因此当前解释器不能执行真实tokenizer核验。GPU锁中版本为transformers4.56.1/tokenizers0.22.2，但本轮未安装或证明这些版本支持两批准tokenizer。系统Python3.12另有transformers5.7.0/tokenizers0.22.2，不能默默混用为本项目Python3.11环境。后续须核定独立本地评审环境、来源兼容性并冻结实际库源码字节，不能只抄版本字符串。

现有验证器为[eval_review_deployment.py](../../finetune/eval_review_deployment.py)。每个批准模型都需要：

1. 明确HF来源与固定revision；独立、无symlink、仅包含批准tokenizer文件的平面本地目录；完整文件SHA256与大小。
2. 当前provider实现SHA、实际transformers/tokenizers版本及源码摘要、对应GGUF digest、show模板摘要。
3. 独立审计者提供的映射JSON、带时区审阅时间、具名来源、可读basis及独立GGUF counter的名称/版本/源码SHA；不是自行填写 `equivalent: true`。
4. 实际special-token行为、关闭thinking的HF raw模板渲染与 `add_special_tokens: false`；由独立GGUF counter获得的固定golden messages、完整token IDs及rendered prompt摘要。现有验证器再以冻结HF tokenizer逐条匹配。

本轮不能生成审计者身份、GGUF token IDs、真实等价结论或部署receipt。独立审计的真实性是明确的信任输入，完整性验证不替代独立审计。

## 客户端显示测点：后端已有接收，候选客户端尚无贯通

只读检查 `/Users/pcoffeep/AgentPlayground/active-projects/TensileAgent` 候选仓，分支 `codex/competition-demo-chat-mock`，HEAD `86e50c6544d0e92a9141bde6d16525c36d11ee8f`；有未跟踪 `tmp/`，未读取其内容。遵守其AGENTS，未写入该仓或启动应用。该候选分支不自动代表未来冻结部署版本。

当前普通上传在 `web/src/api.ts:161`；服务端任务创建在 `agent/web_api.py:721`；模型调用和transport retry在 `agent/inference.py:489`；EventSource与结果state更新在 `web/src/api.ts:196`、`web/src/hooks/useAgentTaskEvents.ts:105`，最终展示在 `web/src/components/FinalResultPanel.tsx:39`。服务端 `finished_at` 和前端收到event均不是已完成DOM显示的测点。现有源码没有贯通性能请求ID/上传nonce、客户端upload→render单调ns时钟或Ed25519回执。

沿用已确认的单次视觉自动结果口径；普通Agent多轮任务、多次VLM调用和人工/评测Agent恢复成本分开，不把内部模型response ID或整Agent任务完成冒充同一性能请求。

### 可直接交接的客户端验收清单

现有权威接口：[performance.py](../../versioning/performance.py)、[performance_receipts.py](../../versioning/performance_receipts.py)、[模型工作流](../model-workflow.md#7-服务配置启动与真实媒体检查)。以下仅整理既有契约，不授权跨库实施或改变协议。

| 环节 | 必须由未来客户端/部署提供 | 后端消费者 |
| --- | --- | --- |
| prepare前 | 精确client/instrumentation/server源码摘要、不同的client/server Ed25519公钥、session_id、client_id与固定clock protocol；真实私钥不入库/不打包网页 | 冻结 `client_attestation_policy`；`validate_policy` |
| 单次上传完成 | 保持一个原始 `x-performance-request-id` 与 `x-performance-upload-nonce`，带 `x-performance-session`；同一客户端单调ns起点，不用服务ISO时间替代 | 受控 `/v1` 模型请求及原始recorder |
| backend完成 | GET `/v1/performance/backend-receipt/{request_id}`，核服务签名、session/plan/request/nonce/challenge/output绑定 | `make_backend_receipt` / `verify_document` |
| 完整自动显示后 | 以同一时钟记录完整结果实际render终点；客户端签名绑定原backend receipt及输出摘要，不在仅收到HTTP/event时先签；POST `/v1/performance/display-receipt` 的既定envelope | `verify_display_receipt`；原始请求分母与display时刻 |
| retry/重连/失败 | 原ID/nonce/起点及失败事实保留，不能换ID或改预热分类隐藏失败；跨请求单调时钟不能回退 | recorder、首个回执锁、warmup.request_ids与clock校验 |
| 正常结束 | POST `/v1/performance/finish`；保留服务完整签名ledger；错误/超时/OOM或未知终态如实记录 | clean finish和全门重算、`performance_run/export` |

待实施部分包括专用单次视觉显示测点、真实上传完成与DOM commit语义、跨transport/UI原ID传递、签名组件及密钥保管、版本化配置和部署资产。本轮不选定新的密钥托管架构，也不在未授权的TensileAgent分支上改代码。字段与JSON严格集合以验证器为准，不用手写示例回执替代签名证明。

## 本轮独立准备与验证

已新增[离线盘点工具](../../finetune/eval_audit_readiness.py)，仅检查显式本地资产及安装依赖字节，不调用Ollama、不加载tokenizer、不读store/truth。实际运行结果与空白草稿见[离线库存及草稿](evaluation-readiness-offline-20261015.json)：transformers/tokenizers均缺失，真实来源尚未提供，`inventory_only=true`、`deployment_proof=false`、`ready_for_real_review=false`。该工具即使所有库存静态字段匹配，也不作真实准入决定。

```sh
.venv/bin/python -m finetune.eval_audit_readiness --template --output /absolute/new-readiness.json
.venv/bin/python -m finetune.eval_audit_readiness --tokenizer-sources /absolute/sources.json --output /absolute/new-inventory.json
```

`--output`只能创建不存在的文件、权限0600，拒绝覆盖与符号链接；无该参数则stdout输出。草稿位于输出JSON的 `templates.tokenizer_sources` 与 `templates.equivalence_audits`；前者必须单独取出、补齐并通过真实来源核定后，才能作为sources输入，整个库存报告不是合法sources。未知路径/revision/library/auditor/time/basis/golden均null或空，生产校验拒绝。

工具只报告审计声明、静态结构与字节是否匹配，不能认证审计者或GGUFcounter、执行golden或生成部署receipt。现场元数据快照、离线缺包/来源草稿及客户端交接清单均已完成；新增38项合成测试覆盖默认无网络/模型导入/数据访问、显式资产字节漂移、额外文件先拒绝不读取、symlink/输出不覆写/0600、空白草稿生产拒绝，以及审计静态结构/声明/时间/精确binding和sources权限错误。审计静态通过仍不认证真实性、不运行golden。

- 实现者最终：`.venv/bin/python -m pytest -q tests/test_eval_audit_readiness.py --basetemp=/private/tmp/mvllm-readiness-staticfinal-20261015-$$`，38 passed，0.11秒，退出0。
- 主Agent最终：同一文件，`--basetemp=/private/tmp/mvllm-readiness-root-static-final-20261015`，38 passed，0.10秒，退出0；compileall及diff-check通过。
- 独立核查发现并修复盘点漏报的P2：旧实现仅回显部分audit声明，非法协议/角色/时间/counter、额外binding字段及sources0666可能不列缺口；现为明确 `audit_static_schema_valid=false` 与对应blockers，不改生产validator。早期13项通过不能当作修复后38项结果。

独立reviewer最终结论：**通过，限本轮环境/资产核验与离线准备，无剩余可执行问题**。独立38项测试0.10秒、退出0，无warning；原P2反例回验已明确报错。独立只读复核loopback元数据、HF已知目录与依赖、候选客户端源码/分支；再次限时流式核验7个blob共13,145,288,368字节，6.573秒内全部digest/大小/stat稳定匹配。未加载模型或执行真实评测。报告及交接按实际代码核对入口—输入—输出—消费者。

174个相对链接/锚点与37个唯一任务标识检查通过。本轮首轮独立13项测试通过时出现旧pytest临时目录清理warning，最终指定新basetemp的38项无该warning，未另行执行旧临时目录清理或读取其内容。

## 下一步与限制

先提供/核定批准模型对应的HF来源与revision、独立受审映射和本地评审环境，再补真实metadata/tokenizer/隔离核验；已有 `review_verify` 要求先有合法冻结eval及来源，不能为了准备而创建空正式记录。客户端按上表在获得跨库实施授权后接线、审阅、冻结版本，再申请真实受控运行。本轮不解除HOLDOUT-BUILD、MODEL-QUALITY或真实GPU/E2E缺口，不重用真实test。
