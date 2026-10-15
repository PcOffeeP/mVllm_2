<!-- DOCUMENT-CONTRACT
Purpose: 索引 finetune 中的执行器、校验模块与历史入口。
Scope: 文件职责及公开CLI的现行或退役状态。
Must Preserve:
- 业务函数保留与公开CLI可执行性分开说明。
Non-goals:
- 不保存实验质量结论和完整运行参数。
-->

# finetune 脚本

正式编排使用 `python -m versioning train/eval`，参数见 [versioning/SCRIPTS.md](../versioning/SCRIPTS.md)。本目录保留执行器、校验原语及历史业务；文件存在不代表CLI仍可执行。

| 文件 | 作用 |
| --- | --- |
| `train_build_dataset.py` | 公开CLI已停用；build_versioned_datasets供新入口冻结原三折或去重全量开发输入，历史构建函数保留 |
| `train_prepare_run.py` | 公开CLI已停用；版本化prepare/verify/execute函数供新训练入口调用 |
| `holdout_metrics.py` | 复用原Stage D七项冻结门槛与私有指标定义；输出公开二值gate，不读取数据或模型 |
| `eval_holdout.py` | full媒体推理、strict/semantic-holdout独立评分、发包/运行/封存、显式acceptance-owner聚合读取与同身份恢复；逐样本仅存受限目录，公开gate/integrity证据 |
| `train_with_contract.py` | 直接YAML启动CLI已停用；run_training接收新入口已冻结的内存配置 |
| `eval_run.py` | 裸 model-dir CLI 已停用；版本化开发评测冻结/推理/导出，显式 strict-v4.1 或 semantic-v4.1 协议 |
| `eval_semantics.py` | 纯语义提取、已封存盲评导入、GT 子集统计、同组 bootstrap 和逐折开发门；不加载模型或部署低权限评审进程 |
| `eval_review.py` | 独立最终语义门、固定本地评审配置、Mac sandbox 探针及受控 worker/localhost Ollama broker；部署receipt核验及HF exact render/raw generate；缺真实部署/tokenizer凭据时请求前拒绝，ambiguous后禁止自动retry/切模型 |
| `eval_review_deployment.py` | 本地资产/源码/模板/独立受审GGUF↔HF映射和golden核验，生成部署receipt；默认不联网，未来显式仅本地元数据，不生成回答 |
| `eval_audit_readiness.py` | `python -m finetune.eval_audit_readiness [--tokenizer-sources /绝对路径/sources.json] [--template] [--output /路径/新报告.json]`：完全离线盘点批准模型摘要、当前provider源码、已安装tokenizer依赖及显式资产/审计basis字节；不导入/实例化tokenizer、不请求Ollama、不读取评测store/truth、不生成凭据。JSON恒为inventory-only且`ready_for_real_review=false`，草稿模板不可用于生产证明；指定输出仅新建0600文件，缺口不代表评审失败或通过 |
| `eval_performance.py` | 冻结开发性能输入、全请求事件/资源重放、MLflow和manifest；配合versioning/performance_receipts双签名接收/核验；缺真实client/runtimecollector/cleanfinish或synthetic时不能passed |
| `eval_baselines.py` | 仅从开发训练集构造多数类对照及同条件配对报告；不读取 test、不改变绝对质量门 |
| `train_monitor_run.py` | 查看训练进度 |
| `eval_audit_effective_views.py` | 审计模型实际采样帧 |
| `release_validate.py` | 校验冻结数据发布 |
| `train_build_source_aware_dataset.py` | 历史source-aware采样及共享辅助函数，无独立main；新三折不扩大该采样 |
| `v4_1_runtime.py` | 公共校验与运行时模块，不直接执行 |

当前工作树不含 `finetune/archive/`；已移出的历史复现脚本从 Git 历史查询，不作为现行入口。

语义开发配置、来源登记、judge 交接及报告见 [versioning 语义开发协议](../versioning/SCRIPTS.md#语义开发协议)。base/diagnostic 来源由 Registry 核验，不能伪造 train 或借服务 alias 使用。独立评分、受控性能证据及按用途准入已接线；真实评审模型隔离、GPU性能和可信显示端仍未验收；本机合成验证不证明真实模型质量、训练机运行或 E2E 通过。
