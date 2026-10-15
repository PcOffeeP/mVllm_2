# 独立评分、性能与准入工程接线记录

## 授权与执行边界

2026-10-15 用户授权按 TODO 继续实施独立评分、性能测试和准入绑定的工程接线、合成验证及实时台账维护，明确暂不运行真实模型评测或使用真实 test。起始为 Mac `30e96f97`、工作区干净，沿用 `feat/evaluation-development`。提交通过 `git log -- docs/results/evaluation-independent-performance-admission-20261015.md` 追溯。

本轮测试仅使用临时合成 store、微型文件、合成真值、替身模型与传输。没有 SSH、GPU/真实模型加载、Ollama 推理、真实 test 读取、账户部署、真实性能运行、TensileAgent 跨库写入或 push/merge。系统 sandbox 探针实际运行，但其输入、哨兵和 worker 都是合成测试，不证明评审模型部署完成。

用户另行明确裁决：**新准入统一要求新质量与性能证据；保留既有批准/alias 的读取与幂等恢复。** 因此旧 strict 不能新建晋级，已有批准与 alias 只在原身份、原绑定下恢复，不允许借幂等换模型、换 eval 或新增批准。

## 工程链路

| 环节 | 入口、输入与实现 | 产物及消费者 |
| --- | --- | --- |
| 独立质量协议 | `semantic-holdout-v4.1`；冻结 full 模型、Prompt、无标签媒体、规则、来源组、评审模型及参数 | 仅无标签 input/raw；原 strict 七门保留原义，不解释为新质量资格 |
| 匿名评审准备 | `eval review_prepare`；合成环境运行实际 sandbox 探针与固定 worker | restricted 映射/nonce、匿名包、执行凭据、不可撤销 exposed；供封存与评分校验 |
| 受控评审与封存 | 固定本地 broker、`review_run`/`review_seal`；只发 raw、手册和字段，独立初判及先封存后仲裁 | 不可变调用与尝试链、judge 封存；完成初判不可换，终态不明不重发或切模型 |
| 授权评分 | `eval score`；先验 raw/包/规则/judge/尝试，再授权读取合成真值 | 新最终12门、score commit 与 consumed；普通 MLflow/manifest 仅 gate+integrity，受限聚合须显式 acceptance-owner 授权 |
| 受控性能 | `performance_prepare/validate/serve/run/export`；Registry 数值模型、开发媒体 allowlist、Prompt/变体、TTL/身份/预算 | 自身 loopback 会话、事件与资源序列、重算报告；不能使用 alias、裸路径或 test 绕加载资格 |
| 计时与显示证明 | 首次上传完成至完整自动显示；请求身份、重试、绝对 timeout、阶段/资源/预热策略预冻结 | 保留全部请求分母及失败事实；真实客户端回执与合成证据分开，缺显示端不宣称 E2E |
| 准入与服务 | `model bind-performance` → finalize → scope/manifest → alias/current/approve | 同模型完整/数值身份、权重、Prompt、运行变体的质量与性能复验；批准另行取得，base/诊断不能晋级生产 |
| 备份恢复 | backup catalog 包含公开/私有 evaluation workspace 与授权事实 | owner-only 恢复、受控位置 receipt、同 raw/claim/exposed/consumed；不重推理、不重置消费 |

本表是工程入口与交接索引；准确参数以 [versioning/SCRIPTS.md](../../versioning/SCRIPTS.md) 和 [模型工作流](../model-workflow.md) 为准。

## 关键验收边界

- 新独立质量门：状态 macro recall≥0.70、四状态各 recall≥0.60、joint≥0.60、机制 macro F1≥0.60、位置 macro F1≥0.70，未夹紧/视频异常各自 P/R≥0.60。缺类、未完成评审不通过；原始严格合法率仍独立报告。
- sandbox 使用内核限制及实际读写、网络、工具、凭据环境探针。包只读、结果仅自身可写；调用者布尔值或 chmod 不作为真实隔离证明。初次受限启动失败后收紧运行时白名单完成合成探针，未因此放开 HOME 或项目目录。
- 真实 broker 的模型/本地 tokenizer/部署证明须核定。HF固定模板以关闭思考的参数渲染，精确计数后同一字节发送至Ollama raw generate，不再由服务二次套模板。GGUF与HF等价性依赖未来独立审计者提供的受审映射、审计依据和golden cases；代码核对模型digest、完整本地资产、库/源码、模板、特殊token及样例绑定，不把两个哈希视为完整tokenizer等价证明。缺资产或漂移拒真实执行。终态不明的超时持久化 started/ambiguous，禁止继续切换模型或自动重发；不停止共享 Ollama。
- 性能规格、300/600/660秒、预算和100次/30分钟规则沿确认方案；重试不重置起点、失败或分母。完成后空闲观察不能补足连续处理时长。资源增长策略必须执行前明确冻结，不替用户新增业务阈值。
- 质量实际 runtime attestation 和性能实际加载配置必须同一；4bit 分开核 storage 与 compute dtype、NF4、double quant及resampler排除模块/dtype六项，不用配置字符串代替实际模型检查。真实环境结果仍未取得。
- 后端已提供可信显示回执接收接口：冻结客户端/测点/服务源码与公钥、会话与时钟策略，客户端签名绑定首次upload、nonce、raw/四字段输出digest；服务签名完整原始ledger。还须实际runtime collector资格和clean finish，OOM及终态不明的线程超时阻止继续接新请求或宣称合格，不冒称线程/GPU已终止。外部客户端实际实现与部署仍是跨仓库/现场依赖，不能用backend时标、合成签名或手工passed自述替代。
- 预热必须事前冻结显式 `warmup.request_ids`，完成后才开始formal；formal之后不能新增预热、改分类或换ID隐藏失败。持续增长策略包括明确算法，实际观测缺失不通过。
- 异根位置 receipt 只允许核定 catalog 与输入下的受控存储映射，不修改冻结 input、claim、raw、judge 或历史 profile。原 profile 仅核历史证明，不代表新路径隔离；历史已 exposed worker 不重跑。外部基座和媒体依赖仍须真实字节验签。
- MLflow client 按自身 tracking URI 的权威 artifact URI 操作，避免同 run ID 的全局缓存把恢复结果写回旧 store，不全局修改其他在用 store。
- 旧 `512cc8b4` strict 与 `30e96f97` strict/semantic 开发对象的兼容只接受已核旧源摘要到准确当前适配摘要；未来未审代码和其他依赖漂移仍拒绝。开发 passed 不能当独立质量。

## 合成验证与独立复核

以下均在Mac本机使用合成输入，分执行者独立运行；不合并为一轮测试通过数量。所有Python命令使用仓库 `.venv/bin/python -m pytest`。

| 最终验证范围 | 实际结果 | 日志与来源 |
| --- | --- | --- |
| 新独立评分/部署/runtime/隔离33项＋旧holdout110项 | 143 passed，71.40s，退出0 | 实现者 `/tmp/mvllm-c-final-complete.log` |
| 性能计时、实际loader替身、双签名、预热/增长/超时保护 | 61 passed，6.15s，退出0 | 实现者 `/tmp/mvllm-perf-source-pair-20261015`；包含实际两侧input builder的帧源码pin结构检查；独立reviewer另61 passed/2.36s |
| 真实git-show旧30e适配及新CLI | 6 passed，8.49s，退出0 | 实现者 `/tmp/mvllm-e-admission-final-frozen.log` |
| 准入/异根恢复/服务/开发联合 | 77 passed，89.08s，退出0 | tester `/tmp/mvllm-cde-tester-verified-20261015.log`；54＋9＋14项 |
| C总deadline增量＋兼容/CLI | 41 passed，29.61s，退出0 | 实现者 `/tmp/mvllm-c-deadline-final.log`；35＋6项 |
| 独立reviewer新C最终 | 35 passed，20.50s，退出0 | reviewer `/tmp/mvllm-review-c-deadline-final-20261015` |
| 独立reviewer准入/恢复/兼容/CLI/服务 | 69 passed，37.01s，退出0 | reviewer独立运行restore＋compatibility＋CLI＋server |
| 既有Registry/materialize | 修复后158 passed，123.04s，退出0 | tester `/tmp/mvllm-legacy-fixed.nPOh6M/pytest.log` |
| 既有manifest/model_registry | 204项通过，来自此前342 passed/20 failed轮次 | tester `/tmp/mvllm-legacy-regressions.Ram1T0/pytest.log`；失败均为相邻旧记录None兼容缺陷，修复后上行158项验证 |
| 既有CLI | 57 passed，1.81s，退出0 | tester `/tmp/mvllm-legacy-cli.ZEvPVb/pytest.log` |

相邻eval首轮为368 passed/7 failed/1 skipped（190.16s，退出1，主Agent `/tmp/mvllm-cde-adjacent-final.log`）：7失败均为旧strict首次晋级测试与用户新准入裁决冲突，已转交按真实历史已有绑定/alias恢复迁移，保留原字节篡改与CLI备份断言，迁移后 `tests/test_eval_run.py` 全文件47 passed/1 skipped（54.70s，退出0，tester `/tmp/mvllm-legacy-evalrun-fixed.vVUGlK/pytest.log`），包含新增evaluation_workspace的备份原字节断言。其余四文件的通过证据来自前述主线程首轮，不宣称另行重跑。C每次判读120秒已统一为涵盖metadata、prompt处理和生成的单一monotonic总deadline；守护I/O超时不假称后端终止，持久ambiguous阻止后续调用。

本轮预读已发现并修复：开发 passed 误入 quality、synthetic 质量资格遗漏、实际 loader/V4.1 contract 绑定、full artifact 路径、串行终结状态、重试绝对起点、连续处理时长、加载失败清理、4bit compute/storage、私有目录权限、历史 alias 查询、异根 profile/媒体定位及 MLflow artifact cache。后续还处理实际runtime采集、tokenizer计数/受审等价映射、双签名接收、OOM可观测性、线程终态不明、预热分母及跨质量/性能视频加载器摘要一致性。以上均以修复后专项证据为准。早期D＋service联合出现两项fixture缺新增量化字段的失败，更新实际resampler属性后最终服务专项及独立E集已通过；早期源码并行变更造成的pin漂移亦不计作最终通过。


实际可复跑的测试组如下（各组结果见上表；仅合成夹具）：

```sh
.venv/bin/python -m pytest -q tests/test_eval_holdout.py tests/test_eval_holdout_semantic.py tests/versioning/test_holdout.py tests/test_holdout_metrics.py
.venv/bin/python -m pytest -q tests/test_eval_holdout_semantic.py tests/test_eval_admission_cli.py tests/test_eval_admission_compatibility.py
.venv/bin/python -m pytest -q tests/test_eval_performance.py
.venv/bin/python -m pytest -q tests/test_eval_admission_restore.py tests/test_eval_admission_server.py tests/test_eval_development_wiring.py
.venv/bin/python -m pytest -q tests/test_eval_run.py tests/versioning/test_mlflow_eval.py tests/test_eval_semantics.py tests/test_eval_baselines.py tests/test_model_sources.py
```

独立reviewer结论：**通过，限C/D/E工程接线与合成范围，无剩余可执行问题**。独立核对三组最终35/61/69项、准确适配SHA及八份文档入口—输入—产物—消费者链路。`compileall`、`git diff --check`、163个相对链接/锚点与37个唯一任务标识检查通过。临时日志路径用于本机追溯；持久证据为本文的命令、范围、结果、修复与限制，源码及提交由Git追溯。

## 台账交接

唯一状态入口是 [项目 TODO](../project-todo.md)。本轮工程完成不自动关闭真实独立测试、真实性能、真实隔离/模型部署、完整生产服务或大型灾难恢复验收；MODEL-DIAG、HOLDOUT-BUILD、FINAL-TRAIN 和 MODEL-QUALITY 保持各自条件。
