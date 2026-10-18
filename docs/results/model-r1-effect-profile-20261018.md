# R1 模型效果档案：v4.1-agent-pipeline-fold0-r1

档案日期：2026-10-18
档案对象：`v4.1-agent-pipeline-fold0-r1`
档案范围：仓库内可核查的该模型训练记录、评测记录、验收与冒烟记录，以及 R2 数据版本与提示版本现状。
写法约定：本文只做事实归集与边界说明。每个数字后附来源文件与字段路径。仓库内找不到证据的位置写「未找到」，不用推测填充。

> **标签存疑（2026-10-18）**：抽样发现部分「已断裂」样本首帧无可见分离，比例高且分散；标签由 `event_time` 几何规则推出、非视觉判据。此处数字仅表示与这批标签的一致程度，**不得作为模型能力结论**。本条注覆盖全文涉及「已断裂」的结论。

## 1. 模型身份

### 1.1 注册身份

来源：`pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json`

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 模型名 | `v4.1-agent-pipeline-fold0-r1` | `model_name` |
| 协议版本 | `v4.1` | `protocol_version` |
| 核心用途 | `agent-pipeline` | `core_purpose` |
| 训练范围 | `fold0` | `training_scope` |
| 轮次 | 1 | `round` |
| 生命周期状态 | `current` | `lifecycle_status` |
| 发布类型 | `milestone` | `release_type` |
| 质量层级 | `intermediate_development_model` | `quality_tier` |
| 全量数据终版 | false | `full_data_final` |
| 生产批准 | false | `production_approved` |
| 契约版本 | `tensile-vlm/v4.1` | `contract.version` |
| 契约 SHA-256 | `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab` | `contract.sha256` |
| 来源实验 ID | `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3` | `origin.experiment_id` |
| 来源数据发布 | `v4.1.0-ecb5aeb9657c` | `origin.release_id` |
| 折 | 0 | `origin.fold` |
| 随机种子 | 3407 | `origin.seed` |
| 训练变体 | `coverage-first` | `origin.training_variant` |
| 优化器步数 | 1125 | `origin.optimizer_steps` |
| adapter 聚合 SHA-256 | `74842170d69a5a17f466a9f560db27cdc1aafde83730b71807d2996471d43aa7` | `artifacts.adapter.aggregate_sha256` |
| merged 聚合 SHA-256 | `1f75e4f91db487273588c1e1c8bf867b20acdfc565c191d914915b366c4c1b1c` | `artifacts.merged.aggregate_sha256` |
| merged 分片数 | 10 | `artifacts.merged.expected_safetensors_shards` |

登记的已知限制：`single_fold_only`、`not_full_data_final`、`not_production_approved`、`quality_gates_not_passed`（字段 `limitations`）。

### 1.2 训练记录

来源：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/training_run_manifest.json`

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 实际优化器步数 | 1125 | `actual_optimizer_steps` |
| 预期优化器步数 | 1125 | `expected_optimizer_steps` |
| 训练轮数 | 3.0 | `epochs` |
| 训练耗时（秒） | 16797.2917 | `train_runtime_seconds` |
| 最佳指标 | 0.054742854088544846 | `best_metric` |
| 最佳 checkpoint | `../LlamaFactory/saves/minicpmv4_5/lora/sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407/checkpoint-250` | `best_model_checkpoint` |
| 完成时间 | 2026-07-27T08:15:59+08:00 | `completed_at` |
| 训练代码提交 | `f54d9ca617e455454f28e31ae058eda2dfdb5ec7` | `training_code_commit` |
| 运行清单路径 | `finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/run_manifest.json` | `run_manifest.path` |
| 运行清单 SHA-256 | `b911c6a0e295c0dc99565f5a27082820bc5ba8542c11c0c1a5c5f06069ebd866` | `run_manifest.sha256` |
| 采样 ID | `source-aware-3k-2a84e8b6cfc3` | `sampling_id` |
| 采样序列 SHA-256 | `2e5c9d6894b115d94d0a085cf7f4c643b65482bb63b253b45a34a116dec1ba9c` | `sampling_sequence_sha256` |

训练产物文件哈希（字段组 `files.*`）：

| 文件 | SHA-256 | 字节数 |
| --- | --- | --- |
| adapter_model | `9e7941c994faa5a4beb5277258290a740b412e0aeda78ca8000adfddc2d67064` | 460430776 |
| adapter_config | `d7dadf6efeed393a9379a14aadb29edddc3ee56261e758cba8e5177306493c0a` | 1123 |
| train_config | `036c9c69f9d79ca837214f1a796d426f7ac7dec1078c11055eed25a866ad8bd9` | 1535 |
| trainer_state | `6855109d36b2cb3981f4560e4e1e91e1e72a4184fb541fd7c924f0217368d10b` | 43857 |
| trainer_log | `68cdfb6847c13014eb75f7d1650aff1a57389585ec41f599a789bf6bb9cd95fa` | 46969 |
| train_results | `89bf51381e28f4905caf45c476ed3ac0554f4db407890a4af7df79d06cf90c7c` | 207 |

adapter 覆盖范围（字段组 `adapter_coverage`）：目标模块数 11；视觉权重计入（`visual` true），视觉权重张量数 324；resampler 已保存（`resampler_saved` true），resampler 权重张量数 13。

### 1.3 adapter 与 checkpoint-250 的关系

这一节是本档案的关键纠正点，写法从严。

可核查的记录事实只有一条：`best_model_checkpoint` 指向 `checkpoint-250`（`training_run_manifest.json` 的 `best_model_checkpoint` 字段）。

仓库内**未找到** `checkpoint-250` 的 `adapter_model.safetensors` 的 SHA-256 记录。`9e7941c994faa5a4beb5277258290a740b412e0aeda78ca8000adfddc2d67064` 这一条哈希是训练输出根 adapter 的哈希，出现在以下四个位置：

- `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/training_run_manifest.json` 第 22 行（字段 `files.adapter_model.sha256`）
- `finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json` 第 60 行
- `docs/results/remote-base-integrity-20261016.json` 第 581 行与第 1148 行

因此「根 adapter 与 `checkpoint-250` 字节相同」这一断言在仓库内没有哈希证据支撑，不得写入结论。仓库内曾有同一次运行（`run_id` 为 `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`）的 concise-cv 三折报告记录「最终 adapter 均与各自最佳 checkpoint 权重 SHA-256 一致」，那是另一个实验口径的记录，不能搬用于此。

可写的旁证只有大小与修改时间，且必须标明是旁证：`docs/results/model-inventory-audit-20260831/remote_snapshot.json` 记录下列三个路径的 `bytes` 均为 460430776：

- `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/adapter_model.safetensors`
- `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/checkpoint-250/adapter_model.safetensors`
- `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/checkpoint-1125/adapter_model.safetensors`

同一快照记录的 `mtime_ns`：根 adapter 为 1785111359186057389，`checkpoint-1125` 为 1785111356998054611，`checkpoint-250` 为 1785098315160646857。该快照只记大小与修改时间，不记 SHA-256。

结论写法：`best_global_step` = 250 是记录事实；「根 adapter 与 checkpoint-250 字节相同」在仓库内未找到哈希证据，字节大小相同不构成等价证明。

### 1.4 基座身份

来源：`docs/results/model-gate-baseline-20260914.md` 第 2 节；`docs/project-todo.md`「本轮输入核验（2026-10-16）」条。

- 基座目录 `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`，模型 MiniCPM-V-4.5。
- 本轮 4 个 safetensors 分片在场，四片权重合计 17,391,890,184 字节。
- 前轮流式 SHA256 与分片结构核验：849 个 tensor 与索引一致，内容清单摘要 `2ffb284ff1a0db561633e91c768c1a9732b33838147113004966c1ff112faa21`。
- 官方 HF 固定 revision `daef484c35ec93210ec93c5e901f8f3e9b78ee34`，完整 23 个 tree 对象 Gitblob 核验通过。
- 未闭合点：本地 `modeling_minicpmv.py` 多一处 `self.post_init()`，与官方来源不同。因此不能把本地目录登记为「未经修改的官方快照」。

### 1.5 训练用 Prompt 的分层

要分三层看，不能合并。

第一层，契约内联正文。历史契约的正文与当前工作区契约的正文不同，两者不能互相替代。

历史契约 `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`（角色：training contract）的正文取自 git 对象 `97d36a90003957be3c13b5dbfc017452a308e54d:pipeline/contracts/tensile_vlm_v4_1.json`，文件 SHA-256 `583201775f33c2b413b9bc1491054ab66d787942ece9c88b8537b1fbacebf20a`，7747 字节。`analysis` 正文实测值：

| 字段 | 字符数 | 字节数 | SHA-256 |
| --- | --- | --- | --- |
| `analysis.system_prompt` | 74 | 210 | `b64660279c93e5dfe943a1233870a5a12fc3bab5438644a6dc4fe0e0a34eab3e` |
| `analysis.user_prompt` | 504 | 1066 | `adef9ae94a15fb56e125cb72fbd50c6de95e7df694d72cecde4b7bf674aff562` |
| `analysis.retry_prompt` | 121 | 191 | `54e0677ed9127d35bd71d76b9e599b5942d6d2a8432f9efcbf61f8e20699ba62` |

这段正文**不等于**当前工作区 `3798f00c…` 契约的 `analysis` 正文。当前契约 `pipeline/contracts/tensile_vlm_v4_1.json` 的文件 SHA-256 为 `9fa15b4a267c295727a9a99240b629b65a78508dcd5cc44887168d1878581331`（8149 字节），其 `analysis` 正文为 system 99 字符 / 285 字节、user 666 字符 / 1360 字节、retry 132 字符 / 224 字节，是后续修订版。

`pipeline/contracts/tensile_vlm_v4_1_prompt_clarified.json` 的 `base_contract_hash` 虽写着 `47e393…`，但该文件的 `analysis` 段正文是当前修订版（system 与 `prompt-v4.1-r2.yaml` 同文），不能当作历史契约正文使用。

此处只能写「契约内联正文」，不能声称「训练时实际喂入的就是这段」。

第二层，训练时实际喂入的 Prompt 文本。**仍未证实**。`docs/project-todo.md`「开发输入现场（2026-10-16）」条记载：原冻结目录两份摘要不在场，实际训练 Prompt 未证，不以当前 active YAML 替代。

第三层，现存三份 legacy Prompt 文件。仅供辨析，均不可当作训练输入证据：

- `pipeline/prompt_registry/v4.1-fixed-full-fields-initial-v1/prompt.yaml`（长 system、短 user 的写法）
- `records/prompts/prompt-v4.1-r1.yaml`
- `records/prompts/prompt-v4.1-r2.yaml`

## 2. 评测矩阵

矩阵共 8 行。第 1 至 6 行的样本都是同一批 425 条 fold 0 validation（`v4.1.0-ecb5aeb9657c` 数据发布），第 7 行是另一批 299 条密封独立测试，第 8 行没有数值指标。

### 2.0 概览

| 行 | 记录类型 | 样本集 | 样本数 | 契约身份 | 输入链路 |
| --- | --- | --- | --- | --- | --- |
| 1 | 开发侧评测汇总 | 425 条 fold 0 validation | 425 | `47e393…`（training contract） | 改动前开发侧管线，单组时间融合，1 组 = 64 token |
| 2 | 开发侧评测汇总 | 同一批 425 条 | 425 | `3798f00c…`（runtime contract） | 同上 |
| 3 | Stage B 中间模型验收门 | 同一批 425 条 | 425 | 两个契约同时登记 | 同上 |
| 4 | Canary 门报告 | 同一批 425 条 | 425 | `47e393…`（training contract） | 同上 |
| 5 | 双 seed 稳定性绝对表现快照 | 同一批 425 条 | 425 | `3798f00c…`（runtime contract） | 同上 |
| 6 | 双 seed 稳定性契约不一致判定 | 同一批 425 条 | 425 | seed3407 为 `47e393…`，seed3411 与 seed3413 为 `3798f00c…` | 同上 |
| 7 | Stage D 密封独立测试公开门 | 299 条密封测试 | 299 | `3798f00c…`（runtime contract，见 `run_identity.json`） | 未找到该次运行的抽帧分组与 token 记录 |
| 8 | 服务冒烟与 Agent 联调冒烟 | 无 | 无 | `3798f00c…` | 服务侧链路，详见 2.8 |

### 2.1 行 1：开发侧 425 条，training contract

记录路径：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/fold0/evaluation_summary.json`

样本集：`v4.1.0-ecb5aeb9657c` release 的 fold 0 validation，425 条（字段 `release_id`、`fold`、`sample_count`）。

契约：`47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`（字段 `contract_hash`），角色为 training contract，即数据发布内联契约。

输入链路：改动前管线，单组时间融合（1 组 = 64 token）。来源 `docs/project-todo.md`「开发评测侧对齐训练/服务」条，原文「改动前返回 `[[0]*n]`，是单组时间融合，1 组等于 64 token」，并注明「旧的 425 与 1,581 指标全部产自改动前管线，与新管线不可直接比较」。

| 指标 | 数值 | 字段路径 |
| --- | --- | --- |
| 样本数 | 425 | `sample_count` |
| 严格合法条数 | 423 | `strict_valid_count` |
| 严格合法率 | 0.995294 | `strict_valid_rate` |
| 四字段 joint 正确率 | 0.400 | `metrics.joint_correct_rate` |
| clip_state 正确率 | 0.470588 | `metrics.clip_state_correct_rate` |
| fracture_mechanism 正确率 | 0.56 | `metrics.fracture_mechanism_correct_rate` |
| fracture_site 正确率 | 0.597647 | `metrics.fracture_site_correct_rate` |
| special_case 正确率 | 0.995294 | `metrics.special_case_correct_rate` |
| 运行失败数 | 0 | `runtime_failure_count` |
| 预测分布 `__invalid__` | 2 | `prediction_clip_state_distribution.__invalid__` |

分状态召回（由 `clip_state_confusion` 对角线除以 `target_clip_state_distribution` 计算，并与 `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_canary_gate_report.json` 的 `metrics.clip_state_recall` 逐项一致）：

| 真值状态 | 计算式 | 值 | 字段路径 |
| --- | --- | --- | --- |
| 临界未断裂 | 28/57 | 0.491228 | `clip_state_confusion["临界未断裂"]["临界未断裂"]` ÷ `target_clip_state_distribution["临界未断裂"]` |
| 发生断裂 | 38/144 | 0.263889 | `clip_state_confusion["发生断裂"]["发生断裂"]` ÷ `target_clip_state_distribution["发生断裂"]` |
| 已断裂 | 5/33 | 0.151515 | `clip_state_confusion["已断裂"]["已断裂"]` ÷ `target_clip_state_distribution["已断裂"]` |
| 未断裂 | 129/191 | 0.675393 | `clip_state_confusion["未断裂"]["未断裂"]` ÷ `target_clip_state_distribution["未断裂"]` |

逐样本记录：SHA-256 `4c8ea6c3bc77bc9aa05681d8f7033cacd72da541209750ffdc8b2959ced715a5`，字节数 411826，见 `finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json` 的 `evidence.evaluation_records`。该 `evaluation_records.jsonl` 本身不在本仓库内。

### 2.2 行 2：开发侧 425 条，runtime contract

记录路径：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_runtime_contract_3798/fold0/evaluation_summary.json`

样本集：与行 1 同一批 425 条，`model_dir` 字段的合并目录路径与行 1 完全相同。

契约：`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`（字段 `contract_hash`），角色为 runtime contract。

输入链路：改动前管线，单组时间融合（1 组 = 64 token），同 2.1。

| 指标 | 数值 | 字段路径 |
| --- | --- | --- |
| 样本数 | 425 | `sample_count` |
| 严格合法条数 | 425 | `strict_valid_count` |
| 严格合法率 | 1 | `strict_valid_rate` |
| 四字段 joint 正确率 | 0.411765 | `metrics.joint_correct_rate` |
| clip_state 正确率 | 0.56 | `metrics.clip_state_correct_rate` |
| fracture_mechanism 正确率 | 0.458824 | `metrics.fracture_mechanism_correct_rate` |
| fracture_site 正确率 | 0.548235 | `metrics.fracture_site_correct_rate` |
| special_case 正确率 | 1 | `metrics.special_case_correct_rate` |
| 运行失败数 | 0 | `runtime_failure_count` |
| 预测分布 `未断裂` | 270/425 = 0.635294 | `prediction_clip_state_distribution["未断裂"]` ÷ `sample_count` |

分状态召回（由 `clip_state_confusion` 对角线除以 `target_clip_state_distribution` 计算）：

| 真值状态 | 计算式 | 值 | 字段路径 |
| --- | --- | --- | --- |
| 临界未断裂 | 13/57 | 0.228070 | `clip_state_confusion["临界未断裂"]["临界未断裂"]` ÷ `target_clip_state_distribution["临界未断裂"]` |
| 发生断裂 | 66/144 | 0.458333 | `clip_state_confusion["发生断裂"]["发生断裂"]` ÷ `target_clip_state_distribution["发生断裂"]` |
| 已断裂 | 0/33 | 0 | `clip_state_confusion["已断裂"]["已断裂"]` ÷ `target_clip_state_distribution["已断裂"]` |
| 未断裂 | 159/191 | 0.832461 | `clip_state_confusion["未断裂"]["未断裂"]` ÷ `target_clip_state_distribution["未断裂"]` |

条件指标（只统计真值非空的样本）：fracture_mechanism 11.26%，fracture_site 28.63%。来源 `docs/reports/2026-07-30-current-release-model-sealed-test-performance-report.md` 第 6 节表。该组数字来自受限逐样本记录的条件统计，不在本仓库的评测汇总字段里。

同报告第 6 节另记 clip_state 准确率 0.56、`已断裂` 召回 0，与上表一致。

### 2.3 行 3：Stage B 中间模型验收门

记录路径：`docs/results/v4_1_stage_b_intermediate/acceptance_summary.json`

该行聚合的是行 1 的同一批 425 条。

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 验收 ID | `stage-b-intermediate-8e1fdb09f8e6` | `acceptance_id` |
| 决定 ID | `stage-b-intermediate-user-accepted-20260727` | `decision_id` |
| 状态 | `accepted_as_intermediate_with_known_limits` | `status` |
| 验收代码提交 | `2d049afa3133845939f7fa7782bd58e4d9c2757f` | `acceptance_code_commit` |
| 实际优化器步数 | 1125 | `artifact_gate.actual_optimizer_steps` |
| 评测样本数 | 425 | `artifact_gate.evaluation_sample_count` |
| 严格合法率 | 0.995294 | `artifact_gate.strict_valid_rate` |
| 运行失败数 | 0 | `artifact_gate.runtime_failure_count` |
| 视觉权重张量数 | 324 | `artifact_gate.visual_weight_count` |
| resampler 权重张量数 | 13 | `artifact_gate.resampler_weight_count` |
| 原 Stage B 性能门 | false | `quality_gate.original_stage_b_performance_gate_passed` |
| leave-one-source-out 门 | false | `quality_gate.leave_one_source_out_gate_passed` |
| training contract | `47e393…` | `training_contract_hash` |
| runtime contract | `3798f00c…` | `runtime_contract_hash` |
| Stage C 追加训练授权 | false | `authorization_scope.stage_c_additional_training` |
| Stage D 独立模型验收授权 | false | `authorization_scope.stage_d_independent_model_acceptance` |
| 生产别名授权 | false | `authorization_scope.production_alias` |
| 密封标签读取 | false | `sealed_labels_read` |

均值来源明细：`finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json`。其中 `evaluation.metrics` 与行 1 同值（`evaluation.metrics.joint_correct_rate` 0.4 等），`models.adapter.files` 记录 adapter 全量文件哈希，`evidence.failed_quality_gate_report.sha256` 为 `f7b1ae6c41c85ab3e9ae01b87c8a78349bec255ac639254640526232b3655a71`。

### 2.4 行 4：Canary 门报告

记录路径：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_canary_gate_report.json`

同一批 425 条，契约 `47e393…`（training contract）。

| 指标 | 数值 | 字段路径 |
| --- | --- | --- |
| 运行 ID | `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3` | `run_id` |
| 随机种子 | 3407 | `seed` |
| 逐样本记录 SHA-256 | `4c8ea6c3bc77bc9aa05681d8f7033cacd72da541209750ffdc8b2959ced715a5` | `records_sha256` |
| 样本数 | 425 | `metrics.sample_count` |
| 三态断裂 macro recall | 0.302211 | `metrics.fracture_three_state_macro_recall` |
| 四状态 macro recall | 0.395506 | `metrics.four_state_macro_recall` |
| `已断裂` 召回 | 0.151515 | `metrics.已断裂_recall` |
| `未断裂` 召回 | 0.675393 | `metrics.未断裂_recall` |
| 四字段 joint 正确率 | 0.4 | `metrics.joint_correct_rate` |
| 严格合法率 | 0.995294 | `metrics.strict_valid_rate` |
| 运行失败数 | 0 | `metrics.runtime_failure_count` |

绝对门判定（字段组 `absolute_gates.*`）：

| 门 | 阈值 | 判定 | 字段路径 |
| --- | --- | --- | --- |
| 三态断裂 macro recall | 0.3272 | false | `absolute_gates.fracture_three_state_macro_recall` |
| 四状态 macro recall | 0.4382 | false | `absolute_gates.four_state_macro_recall` |
| `已断裂` 召回 | 0.2015 | false | `absolute_gates.已断裂_recall` |
| `未断裂` 召回 | 0.751 | false | `absolute_gates.未断裂_recall` |
| 四字段 joint 正确率 | 0.4112 | false | `absolute_gates.joint_correct_rate` |
| 严格合法率 | 1.0 | false | `absolute_gates.strict_valid_rate` |
| 运行失败数 | 0 | true | `absolute_gates.runtime_failure_count` |

整体 `passed` 为 false，`next_action` 为 `freeze_failure_and_continue_development_only_attribution`。

该报告内含一个对照基线，属于**另一个模型**，不得与本模型数字混列：

| 对照基线项目 | 值 | 字段路径 |
| --- | --- | --- |
| 基线运行 ID | `v4_1_0_760050fad303_20260724_visual` | `baseline.run_id` |
| 样本数 | 425 | `baseline.metrics.sample_count` |
| 严格合法率 | 0.981176 | `baseline.metrics.strict_valid_rate` |
| 四字段 joint 正确率 | 0.421176 | `baseline.metrics.joint_correct_rate` |
| 三态断裂 macro recall | 0.277235 | `baseline.metrics.fracture_three_state_macro_recall` |
| 四状态 macro recall | 0.408188 | `baseline.metrics.four_state_macro_recall` |

该报告还含 29 个来源视频的 `source_error_analysis` 与 `leave_one_source_out` 明细。

### 2.5 行 5：双 seed 稳定性绝对表现快照

记录路径：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/dual_seed_stability/absolute_performance_snapshot.json`

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 模式 | `record_only` | `mode` |
| 身份已修正 | true | `identity_corrected` |
| 评分器身份 | 含 `runtime_contract:3798f00c…` | `scorer_identity` |
| 历史参考 fracture_recall | 0.5 | `historical_reference.fracture_recall` |
| 严格合法率（seed 3407） | 1 | `seeds.3407.strict_valid_rate` |
| fracture F1（seed 3407） | 0.5490196078431373 | `seeds.3407.fracture_f1` |
| fracture recall（seed 3407） | 0.4745762711864407 | `seeds.3407.fracture_recall` |
| non-fracture recall（seed 3407） | 0.8185483870967742 | `seeds.3407.non_fracture_recall` |
| macro F1（seed 3407） | 0.647671568627451 | `seeds.3407.macro_f1` |

`seeds.3407` 指 R1。同一文件的 `seeds.3411` 与 `seeds.3413` 是另外两个模型，本档案不复述其数值，也不把三者并列比较。

同一路径下还有一份同名文件，两份数值不同，不能混用：

| 位置 | `scorer_identity` 中的契约 | `seeds.3407` fracture_f1 | fracture_recall | macro_f1 | non_fracture_recall | strict_valid_rate |
| --- | --- | --- | --- | --- | --- | --- |
| `dual_seed_stability/absolute_performance_snapshot.json` | `runtime_contract:3798f00c…` | 0.5490196078431373 | 0.4745762711864407 | 0.647671568627451 | 0.8185483870967742 | 1 |
| `dual_seed_stability/invalidated_contract_mismatch/absolute_performance_snapshot.json` | `contract:47e393…` | 0.5311475409836065 | 0.4576271186440678 | 0.6357395163481568 | 0.8104838709677419 | 0.9952941176470588 |

本行引用的数值取上一行（顶层，`3798f00c…` 契约）。两份是不同契约下的两份记录，不可互相替代。

### 2.6 行 6：双 seed 稳定性契约不一致，判定作废

记录路径：`finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/dual_seed_stability/invalidated_contract_mismatch/final_stability_disposition.json`

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 状态 | `integrity_blocked` | `status` |
| 原因 | `evaluation_contract_hash_mismatch` | `reason` |
| 阻断时间 | 2026-07-28T10:18:19+08:00 | `blocked_at` |
| 是否继续交叉验证 | false | `continue_to_crossval` |
| seed3407 契约 | `47e393…` | `identities.seed3407.contract_hash` |
| seed3411 契约 | `3798f00c…` | `identities.seed3411.contract_hash` |
| seed3413 契约 | `3798f00c…` | `identities.seed3413.contract_hash` |
| 三者数据发布 / 折 / 样本数 | `v4.1.0-ecb5aeb9657c` / 0 / 425 | `identities.*.release_id`、`.fold`、`.sample_count` |
| 作废的比较输出 | `primary_stability_comparison.json`、`relative_stability_gate.json`、`fallback_stability_comparison.json`、`final_stability_disposition.json` | `invalidated_comparison_outputs` |
| 解除条件 | `maintainer decision and identity-correct evidence; seed3407 must not be retrained` | `required_resolution` |

同目录的 `absolute_performance_snapshot.json` 也在作废清单的语境下使用。它的 `scorer_identity` 为 `…;contract:47e393…`，`seeds.3407` 为 fracture_f1 0.5311475409836065、fracture_recall 0.4576271186440678、macro_f1 0.6357395163481568、non_fracture_recall 0.8104838709677419、strict_valid_rate 0.9952941176470588。注意 `dual_seed_stability/` 顶层另有一份同名快照（见 2.5），其 `scorer_identity` 为 `…;runtime_contract:3798f00c…`，`seeds.3407` 数值与本节不同。两份记录对应不同契约，不可混用。

### 2.7 行 7：Stage D 密封独立测试 299 条

轻量门记录路径：`docs/results/v4_1_stage_d_sealed_test_release/public_gate_summary.json`

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 运行 ID | `stage-d-run-da566a5644f8` | `run_id` |
| 样本数 | 299 | `sample_count` |
| 记录条数与发布一致 | true | `integrity.record_count_matches_release` |
| 运行失败为零 | true | `integrity.runtime_failure_zero` |
| 严格契约 100% | true | `integrity.strict_contract_100_percent` |
| 三态断裂 macro recall 门 | false | `gates.fracture_three_state_macro_recall` |
| 四状态 macro recall 门 | false | `gates.four_state_macro_recall` |
| `已断裂` 召回门 | false | `gates.已断裂_recall` |
| `未断裂` 召回门 | true | `gates.未断裂_recall` |
| 四字段 joint 正确率门 | false | `gates.joint_correct_rate` |
| 严格合法率门 | true | `gates.strict_valid_rate` |
| 运行失败数门 | true | `gates.runtime_failure_count` |
| 整体 | false | `passed` |
| 密封测试已暴露 | true | `sealed_test_exposed` |
| 受限语义指标已扣留 | true | `restricted_semantic_metrics_withheld` |

契约身份：`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`（runtime contract）。字段路径：`finetune/results/v4_1_stage_d_runs/stage-d-run-da566a5644f8/run_identity.json` 的 `identity.contract_hash`；`docs/results/v4_1_stage_d_sealed_test_release/release_summary.json` 的 `identity.contract_hash` 同为该值。`public_gate_summary.json` 无契约字段，其 `gates` 与 `finetune/results/v4_1_stage_d_runs/stage-d-run-da566a5644f8/stage_d_gate.json` 的 `gates` 一致。

测试发布与准入计数（来源 `docs/results/v4_1_stage_d_sealed_test_release/release_summary.json`）：

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 测试发布 ID | `v4.1-sealed-test-5546b8bf1ec3` | `release.release_id` |
| 发布清单 SHA-256 | `b996f0540681066de0731ffcab5a0f760bc691fcb6e6bd1e687eb150b7b96e72` | `release.manifest_sha256` |
| 审查队列 ID | `v4-1-phase2-sealed_test-4f66487a6315` | `review.queue_id` |
| 审查队列候选数 | 332 | `counts.review_queue_candidates` |
| 准入候选数 | 299 | `counts.admitted_candidates` |
| 排除候选数 | 33 | `counts.excluded_candidates` |
| 独立来源数 | 20 | `counts.admitted_sources` |
| 无候选的 test 划分来源数 | 1 | `counts.test_split_sources_without_candidates` |
| 已批准 / 已纠正 / 已丢弃 / 需重生成 | 209 / 90 / 33 / 0 | `counts.approved`、`counts.corrected`、`counts.dropped`、`counts.needs_regenerate` |

运行身份文件另记三项：`identity.sample_count` 为 299，`identity.code_commit` 为 `f04ca7cb63cd1bbaa921b9dcd7fed3f4dada8d64`，`identity.release_id` 为 `v4.1-sealed-test-5546b8bf1ec3`。

有一处记录不一致，照实写出：`run_identity.json` 的 `status` 为 `authorized_not_started`，而 `stage_d_gate.json` 的 `status` 为 `completed`。本档案不下判断。

数值来源：`docs/reports/2026-07-30-current-release-model-sealed-test-performance-report.md` 第 5 节。该报告抬头明写模型 `v4.1-agent-pipeline-fold0-r1`，模型聚合 SHA-256 `1f75e4f9…`。

| 指标 | 值 | 来源位置 |
| --- | --- | --- |
| 四字段 joint 正确率 | 37.79% | 报告第 5 节 |
| clip_state 准确率 | 52.51% | 报告第 6 节对比表（由第 5.2 节混淆矩阵自算 157/299） |
| 四状态 macro recall | 38.62% | 报告第 5 节 |
| 三断裂相关状态 macro recall | 19.88% | 报告第 5 节 |
| `已断裂` 召回 | 0% | 报告第 5 节 |
| `未断裂` 召回 | 94.83% | 报告第 5 节 |
| fracture_mechanism 非空真值条件准确率 | 4/180 = 2.22% | 报告第 5 节 |
| fracture_site 非空真值条件准确率 | 17/179 = 9.50% | 报告第 5 节 |
| special_case | 无正样本，299/299 为 null 真值 | 报告第 5 节 |

该行是**密封独立测试**，与 425 条 development validation 不是同一集合，`sealed_test_exposed` 为 true。

输入链路：**未找到**该次运行的抽帧分组与 token 记录。不做推定。

### 2.8 行 8：服务冒烟与 Agent 联调冒烟

记录路径：`docs/results/v4_1_agent_pipeline_fold0_r1/deployment_summary.json`

`validated_at` 为 2026-07-29T10:35:00+08:00，`status` 为 `running_and_smoke_validated`。

| 项目 | 值 | 字段路径 |
| --- | --- | --- |
| 主机 | 127.0.0.1 | `runtime.host` |
| 端口 | 8002 | `runtime.port` |
| 模型参数 | `workspace/models/current/merged` | `runtime.model_argument` |
| 运行设备 | cuda:0 | `runtime.runtime_device` |
| 运行精度 | bfloat16 | `runtime.runtime_dtype` |
| 生产别名 | false | `runtime.production_alias` |
| 真实媒体服务冒烟通过 | true | `real_media_service_smoke.passed` |
| 严格输出合法 | true | `real_media_service_smoke.strict_output_valid` |
| 请求 ID 在场 | true | `real_media_service_smoke.request_id_present` |
| 实际帧表在场 | true | `real_media_service_smoke.actual_frame_table_present` |
| tensor 摘要在场 | true | `real_media_service_smoke.tensor_digest_present` |
| tensor 形状在场 | true | `real_media_service_smoke.tensor_shape_present` |
| doctor 通过 | true | `agent_pipeline_smoke.doctor_passed` |
| 真实 GPU 调用通过 | true | `agent_pipeline_smoke.real_gpu_call_passed` |
| 结果 schema | `tensile-agent/result/v4.1` | `agent_pipeline_smoke.result_schema` |
| 响应状态 | `no_fracture` | `agent_pipeline_smoke.response_status` |
| 结果 SHA-256 | `14fa8991681d18fb77c82cb38fc1fed201ea3a5af3e6e11fc90d7e411bf6c5b2` | `agent_pipeline_smoke.result_sha256` |
| 部署身份匹配 | true | `agent_pipeline_smoke.deployment_identity_matched` |
| Stage B 历史状态 | false | `historical_quality_status.stage_b_passed` |
| Stage C 历史状态 | false | `historical_quality_status.stage_c_completed` |
| Stage D 历史状态 | false | `historical_quality_status.stage_d_passed` |
| Stage G 历史状态 | false | `historical_quality_status.stage_g_passed` |
| 生产批准 | false | `historical_quality_status.production_approved` |

两条必写说明：

- `tensor_shape_present` 等布尔值在全仓只出现在该文件（`deployment_summary.json:32`），**未找到**生成这些布尔值的脚本，也**未找到**原始响应落盘。该组布尔值的来源待核。
- 整行没有任何指标数值，不能当作效果测量。

该文件另记 `real_media_smoke_passed` 为 true 于 `delivery/service_component.json`。

### 2.9 矩阵之外的复述来源

以下三处只复述 425 条的部分数字，不是独立评测，不构成新的评测行：

- `README.md` 第 43 行与 `docs/project-status.md` 的 Fold0 中间模型段落：只复述 425 条的 `strict_valid_rate` 0.995294 与 `joint_correct_rate` 0.411765。
- `docs/results/model-gate-baseline-20260914.md` 第 3 节：表内只列 425 条、1,581 条、1,216 条三行；该文件第 66 行明写「本文不读取或重述受限test逐样本内容」。

**299 条数值未被这三处复述。**

## 3. 读法说明

### 3.1 行 1 与行 2 是同一模型换了契约（含 Prompt 指令正文）

行 1 与行 2 是同一个模型、同一批 425 条样本、同一个 merged 目录，换了契约身份（`47e393…` 换成 `3798f00c…`）。

两版契约的 `analysis.system_prompt`、`analysis.user_prompt`、`analysis.retry_prompt` **确实不同**。证据：`docs/results/training-data-ledger-20261017.json` 的 `contract_analysis.differing_paths` 列出 `$.analysis.retry_prompt`、`$.analysis.system_prompt`、`$.analysis.user_prompt`、`$.contract_hash` 四个路径；同一对象的 `semantics_boundary` 原文为「Analysis instructional text changed, so equal structured label definitions do not prove identical annotation guidance or model task behavior. Does not recover actual old Fold0 training Prompt.」；`label_schema_and_enum_generation_video_objects_unchanged` 为 true。两侧正文的字符数、字节数与 SHA-256 见 1.5 节。

因此行 1 到行 2 是同一模型换了契约（含 Prompt 指令正文），既不表示模型能力发生变化，也不涉及重新训练。

同一变更并未只动 Prompt 正文：还包含 `retry_prompt` 与契约结构差异（`$.contract_hash` 一并改变，schema 与 generation 字段不同），仓库内没有受控单变量实验。因此不能把严格合法率 0.995294 到 1、四字段 joint 正确率 0.400 到 0.411765 的差值单独归因于 Prompt 正文改动。

与之相关的代码记录：原 concise 三折报告第 3.2 节（该记录已随 2026-10-18 清理移除）记录提交 `c6098ab1` 修正了 evaluator 的 contract 身份记录并增加 Prompt contract 支持，未修改 `parse_v4_1_output`、`score_v4_1_prediction` 与标签语义。

### 3.2 行 1 至行 6 全部测于改动前开发侧管线

所有 425 条数字（行 1 至行 6）都测于改动前开发侧管线：单组时间融合，1 组 = 64 token。

训练侧与开发侧对齐后是逐帧成组：8 帧即 8 组，视觉 token 推导值 512（512 = 8 × query_num 64，需加载 resampler 做前向才能实测）。来源同为 `docs/project-todo.md`「开发评测侧对齐训练/服务」条。

两种口径不可直接比较。

### 3.3 8 组 / 512 token 链路上没有 R1 的评测记录

「R1 在 8 组 / 512 token 链路下的表现」**没有任何一次真实测量**。仓库里没有该口径下的 R1 评测记录。相关记录只有行 8 的服务冒烟；该文件只登记布尔结果与单值响应，**未登记请求次数**，也没有指标数值。

### 3.4 299 条与 425 条只能并列陈述

行 7 的 299 条是密封独立测试，与 425 条 development validation 不是同一集合，且 `sealed_test_exposed` 为 true。两者契约同为 `3798f00c…`，所以不可比的原因不在契约，而在：不同 release（`v4.1-sealed-test-5546b8bf1ec3` 与 `v4.1.0-ecb5aeb9657c`）、不同样本集合（20 个 test 来源与 29 个 development 来源）、`sealed_test_exposed` 为 true、该次抽帧分组未记录。不同 release、不同集合、不同链路之间只能并列陈述，不能相互换算，也不能作单变量因果对比。

## 4. 结论边界

### 4.1 能断言

- 契约身份层面：同一个 merged 模型在 `3798f00c…` 契约下对 425 条 fold 0 validation 达到严格合法率 1、四字段 joint 正确率 0.411765。来源 `seed3407_runtime_contract_3798/fold0/evaluation_summary.json` 的 `strict_valid_rate` 与 `metrics.joint_correct_rate`。
- 输出分布层面：425 条下预测 `未断裂` 占 270/425；`已断裂` 在开发 425（`3798f00c…` 口径）与密封 299 两次评测中召回均为 0。来源 2.2 与 2.7。
- 工程链路层面：merged 与 adapter 的完整聚合哈希校验通过（`1f75e4f9…` 与 `74842170…`），服务冒烟与 Agent 调用冒烟有通过记录。来源 `deployment_summary.json` 的 `artifacts.full_hash_verification_passed` 与 `agent_pipeline_smoke`。
- 门禁记录层面：Stage B 性能门与 leave-one-source-out 门记录为 false，Stage D 质量门记录为 false，`production_approved` 为 false。来源 2.3、2.4、2.7、2.8。

### 4.2 不能断言

- 不能断言「Prompt 正文改动单独导致严格合法率 0.995294 到 1、四字段 joint 正确率 0.400 到 0.411765」：同一变更还包含 `retry_prompt` 与契约结构差异，且没有受控单变量实验；也不能断言该差值代表模型能力变化。
- 不能断言「R1 在服务链路（8 组 / 512 token）上的表现」：全仓没有该口径的 R1 评测记录；服务冒烟只有布尔值，且 `tensor_shape_present` 等布尔值无生成脚本可追。
- 不能断言「根 adapter 与 checkpoint-250 字节相同」：checkpoint-250 的权重 SHA-256 未在任何记录中出现，只有三者字节数相同与修改时间不同的旁证。
- 不能断言「425 条开发验证与 299 条密封测试可比」：两者契约同为 `3798f00c…`，但 release 不同（`v4.1.0-ecb5aeb9657c` 与 `v4.1-sealed-test-5546b8bf1ec3`）、样本集合不同（29 个 development 来源与 20 个 test 来源）、`sealed_test_exposed` 为 true，且前者为 1 组 64 token、后者输入链路未记录。
- 不能断言「训练时实际喂入的 Prompt 就是 `47e393…` 契约内联正文」：原冻结目录两份摘要不在场，实际训练 Prompt 未证实。
- 不能断言「joint 0.411765 表示四字段判断整体可用」：special_case 在 425 与 299 上都没有正样本（真值全为 null），该字段准确率不具备区分能力；mechanism 与 site 的非空真值条件准确率分别为 11.26% 与 28.63%（425 条，`3798f00c…` 口径）以及 2.22% 与 9.50%（299 条）。
- 不能断言「服务侧部署参数与开发侧的切片、像素、时序组一致」：`docs/project-todo.md` 记录服务侧为推定链路（`pipeline/server_proxy.py` 经 LlamaFactory `ChatModel`、`hf_engine`、`mm_plugin` 共用同一路径）。部署清单 `pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json` 记录了 `processor_version`、`max_frames`（8）、`model_version`、`transformers_version`、`llamafactory_version`、`base_model_version`、`adapter_version`、`config_fingerprint`、`runtime_device`、`runtime_dtype`，**未记录**像素预算、时序分组、单次推理超时；未现场取证。（`docs/project-todo.md` 把该清单表述为「只记 `processor_version` 与 `max_frames: 8`」，与清单实际键不一致；此处以清单实际键为准。）

## 5. R2 现状

### 5.1 身份

数据版本 `data-v4.1-r2`：由 `v4.1.0-ecb5aeb9657c` 的 Phase2 train 发布迁移而来。状态为 `sealed`、`development`，`training_allowed` 为 true，`active`，receipt 为 `committed`。样本数 1678，三折 train 与 validation 计数为 1253/425、1014/664、1186/492（validation 合计 1,581），85 个来源视频，引用去重 1678、缺失 0。来源分层写清，不把一份文件当成全部事实的依据：

- `docs/data-workflow.md:180`：只支持 `active` 与「来源是 `v4.1.0-ecb5aeb9657c` Phase2 train 发布」两项。
- `docs/results/remote-state-refresh-20261013.md:42`：`sealed`、`development`、`training_allowed=true`、`sample_count=1678`、`active`、`receipt committed`、引用去重 1678 / 缺失 0。
- `docs/results/remote-state-refresh-20261013.md:46`：三折 train 与 validation 计数 1253/425、1014/664、1186/492。
- `docs/project-todo.md:64`：1,678 候选、85 个来源视频、validation 三折 425/664/492 合计 1,581。

迁移 receipt：`/data/mVllm_2/migration_receipts/data-v4.1-r2.receipt.yaml`。内容摘要原见清理预检记录（该记录已随 2026-10-18 清理移除），`target_release_digest` 为 `a80199ee464b45250fd6a1f0369f3c23415e5c0d161cfd3591e65b9f8638ac8b`。

提示版本 `prompt-v4.1-r2`：仓库跟踪记录 `records/prompts/prompt-v4.1-r2.yaml`，文件 SHA-256 `9c6ec5274cd804d21bf54585343344a67443f94b8396fe5bc01f41ab2de7269f`，字节数 1808。该文件只有 `version`、`protocol`、`system_prompt`、`user_prompt`、`output_fields` 五个键，没有 sealed、training_allowed 之类的生命周期字段。生命周期是 data release 的属性，不是 prompt 记录的属性。

正文逐字节等于运行期契约 `pipeline/contracts/tensile_vlm_v4_1.json` 的 `analysis.system_prompt` 与 `analysis.user_prompt`。两侧 system_prompt SHA-256 同为 `c9cde7a213b6a118b4ea06b5b27d38993c71e48a49ec3ce78502226afc328980`（285 字节），user_prompt SHA-256 同为 `d06d167b7d67e09c9518f364c175e2d3678b241ff1cc10ae5be1bc3afd9b1a45`（1360 字节）。

历史版本 `prompt-v4.1-r1` 保留未删改，文件 SHA-256 仍为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`。来源：`docs/project-todo.md`「开发评测侧对齐训练/服务」条。

### 5.2 尚未发生的事

- 没有 train 记录。仓库与 store 的 `records/` 下只有 `prompts/`（`records/prompts/prompt-v4.1-r1.yaml`、`records/prompts/prompt-v4.1-r2.yaml`），未找到 `train`、`model`、`eval` 任何一类记录。
- 没有 R2 模型身份。没有 `model-v4.1-r*` 记录，`workspace/models/releases/` 下唯一发布目录仍是 `v4.1-agent-pipeline-fold0-r1`（`docs/results/model-gate-baseline-20260914.md` 第 1 节）。
- 没有 R2 评测记录。未找到任何以 `data-v4.1-r2` 与 `prompt-v4.1-r2` 为输入的 eval 记录。`docs/project-todo.md` 明确记「尚未重测 r0」，旧的 425 与 1,581 指标全部产自改动前管线。

### 5.3 与 R1 的关系

R1 的 `model_name` 是 legacy 命名 `v4.1-agent-pipeline-fold0-r1`，由协议、用途、fold、round 四段组成，不满足新体系 `<kind>-v<协议>-r<N>` 的命名与登记要求（kind 仅限 data、prompt、train、model、eval）。R1 是旧体系产物，其数据身份与模型身份来自 legacy registry 与老实验目录。

R2 与 R1 不构成同一代迭代关系。R2 是新体系的第一代 data 与 prompt 记录（`data-v4.1-r2`、`prompt-v4.1-r2`），与 R1 之间没有 train、model、eval 记录把两端接起来。两者只在内容上有承接关系：`data-v4.1-r2` 由 R1 训练所用的 `v4.1.0-ecb5aeb9657c` 迁移而来。在体系身份上，两者不是同一代的迭代。

### 5.4 训练 R2 的推算与可对照实测

以下推算数字全部标注为推算，不是实测。

- 交办口径给出的推算：三折约 5.78 小时（epoch 口径，1,290 步，每步 10.94 秒，另加 22 次评测）；若只跑 1 epoch，约 1.5 小时。
- **上述 1,290 步、10.94 秒每步、22 次评测、5.78 小时、1.5 小时，仓库内未找到对应的计算记录或实测日志**。这些是推算值与假设。

可对照的实测锚点：R1 的 `train_runtime_seconds` 为 16797.2917，对应 1125 步，折算 16797.2917 ÷ 1125 ≈ 14.93 秒/步。这是同机同配置的历史实测，但步数、数据版本、Prompt 与评测次数都不同，不能直接套算 R2。

事实陈述（不做评价）：`data-v4.1-r2` 是三折齐全、`training_allowed` 为 true 的 sealed development 数据；`prompt-v4.1-r2` 与运行期契约字节相同；R2 训练是新体系下第一条能生成完整 `train-v…-r…` 与 `model-v…-r…` 身份的路径。

## 6. 证据索引

### 6.1 模型与训练

| 路径 | 用途 | 已知 SHA-256 |
| --- | --- | --- |
| `pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json` | 模型注册身份 | — |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/training_run_manifest.json` | 训练记录与产物哈希 | 见 6.3 |
| `finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/run_manifest.json` | 训练运行清单 | `b911c6a0e295c0dc99565f5a27082820bc5ba8542c11c0c1a5c5f06069ebd866` |
| `docs/results/model-inventory-audit-20260831/remote_snapshot.json` | adapter 与 checkpoint 的大小、修改时间快照 | — |
| `docs/results/remote-base-integrity-20261016.json` | adapter 哈希出现位置（第 581、1148 行） | — |
| `docs/results/model-gate-baseline-20260914.md` | 基座身份、发布目录、复述来源 | — |

### 6.2 评测与门禁

| 路径 | 用途 | 已知 SHA-256 |
| --- | --- | --- |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/fold0/evaluation_summary.json` | 行 1 汇总 | — |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_runtime_contract_3798/fold0/evaluation_summary.json` | 行 2 汇总 | — |
| `docs/results/v4_1_stage_b_intermediate/acceptance_summary.json` | 行 3 验收门 | — |
| `finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json` | 行 3 来源明细 | `c31427bdebdffd49e83bb66fbeb663a992b69d36c56b477dc58b2e9080885cd1`（见 `acceptance_summary.json` 的 `acceptance_manifest.sha256`） |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_canary_gate_report.json` | 行 4 Canary 门 | — |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/dual_seed_stability/absolute_performance_snapshot.json` | 行 5 绝对表现快照 | — |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/dual_seed_stability/invalidated_contract_mismatch/final_stability_disposition.json` | 行 6 作废判定 | — |
| `finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/dual_seed_stability/invalidated_contract_mismatch/absolute_performance_snapshot.json` | 行 6 作废语境下的快照 | — |
| `docs/results/v4_1_stage_d_sealed_test_release/public_gate_summary.json` | 行 7 公开门 | `64c76d43615e938302e8b510f8a138a23ba0b6df4612fecb2f711b4965483432`（该文件自身 sha256，1013 字节） |
| `finetune/results/v4_1_stage_d_runs/stage-d-run-da566a5644f8/stage_d_gate.json` | 行 7 门判定原始记录，`gates` 与公开门一致，`status` 为 completed | `e9ebe1f6ad32946a65a65589ce99121641ea150ad48e29212d083ded34039b88`（整文件 sha256，834 字节；亦即公开门的 `public_gate_sha256` 字段值） |
| `finetune/results/v4_1_stage_d_runs/stage-d-run-da566a5644f8/run_identity.json` | 行 7 契约身份、样本数与运行身份 | — |
| `docs/results/v4_1_stage_d_sealed_test_release/release_summary.json` | 行 7 发布与准入计数、`identity.contract_hash` | — |
| `docs/reports/2026-07-30-current-release-model-sealed-test-performance-report.md` | 行 2 与行 7 的数值来源 | — |
| `docs/results/v4_1_agent_pipeline_fold0_r1/deployment_summary.json` | 行 8 冒烟记录 | — |
| `delivery/service_component.json` | 另记 `real_media_smoke_passed` 为 true | — |

### 6.3 已知的分项哈希

| 条目 | SHA-256 | 字节数 |
| --- | --- | --- |
| `intermediate_model_acceptance.json` 的 `evidence.evaluation_summary.sha256` | `71d6c43179fedf761be0bb7de4760fa5eab97f7890af20424e3d07229e333970` | — |
| `intermediate_model_acceptance.json` 的 `evidence.failed_quality_gate_report.sha256` | `f7b1ae6c41c85ab3e9ae01b87c8a78349bec255ac639254640526232b3655a71` | — |
| `intermediate_model_acceptance.json` 的 `evidence.training_run_manifest.sha256` | `1afc1b841fd46130b3fd7b788191718ee0734f0ff57538b97ff246784e44f9c5` | — |
| `intermediate_model_acceptance.json` 的 `evidence.policy.sha256` | `f71a29d0a38dd078629cf440f6011e68753e6d0cc547dcd2851075c2628960fe` | — |
| `intermediate_model_acceptance.json` 的 `evidence.runtime_contract.sha256` | `9fa15b4a267c295727a9a99240b629b65a78508dcd5cc44887168d1878581331` | — |
| `intermediate_model_acceptance.json` 的 `evidence.runtime_failures.sha256` | `7b2427bdf1082958ea796afc5119f6c22e3503584b28548e4db22e5a6c03102b` | 39 |
| `evidence.evaluation_records.sha256`（逐样本记录） | `4c8ea6c3bc77bc9aa05681d8f7033cacd72da541209750ffdc8b2959ced715a5` | 411826 |

`records_*` 与 `evaluation_records.jsonl` 一类的逐样本文件按 `.gitignore` 只留在训练机，本仓库内不存在。

### 6.4 契约、Prompt 与数据版本

| 路径 | 用途 | 已知 SHA-256 |
| --- | --- | --- |
| `pipeline/contracts/tensile_vlm_v4_1.json` | 运行期契约，含 `analysis.system_prompt` 与 `analysis.user_prompt` | 契约身份 `3798f00c…` |
| `pipeline/contracts/tensile_vlm_v4_1_prompt_clarified.json` | 同一 Prompt 正文来源，`base_contract_hash` 为 `47e393…` | — |
| `pipeline/prompt_registry/v4.1-fixed-full-fields-initial-v1/prompt.yaml` | legacy Prompt，仅供辨析 | — |
| `records/prompts/prompt-v4.1-r1.yaml` | legacy Prompt，仅供辨析 | `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6` |
| `records/prompts/prompt-v4.1-r2.yaml` | R2 提示版本记录 | `9c6ec5274cd804d21bf54585343344a67443f94b8396fe5bc01f41ab2de7269f` |
| `pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json` | 部署清单，记 `processor_version`、`max_frames`、`model_version`、`transformers_version`、`llamafactory_version`、`base_model_version`、`adapter_version`、`config_fingerprint`、`runtime_device`、`runtime_dtype`；未记像素预算、时序分组、单次推理超时 | — |
| `docs/results/training-data-ledger-20261017.json` | 两版契约正文差异与 `semantics_boundary`（`contract_analysis`；原运行时就绪材料已于 2026-10-18 并入台账） | — |
| 清理预检记录（已随 2026-10-18 清理移除） | 迁移 receipt 内容摘要 | `target_release_digest` 为 `a80199ee464b45250fd6a1f0369f3c23415e5c0d161cfd3591e65b9f8638ac8b` |
| `docs/data-workflow.md:180` | `data-v4.1-r2` 的 active 状态与来源发布（仅支持此两项） | — |
| `docs/results/remote-state-refresh-20261013.md:42`、`:46` | 状态、sample_count、receipt、去重计数与三折计数 | — |
| 原 concise 三折报告（已随 2026-10-18 清理移除） | 第 3.2 节，提交 `c6098ab1` 的 evaluator 契约身份修正记录 | — |

### 6.5 复述与台账

| 路径 | 用途 |
| --- | --- |
| `README.md`（第 43 行） | 只复述 425 条的 0.995294 与 0.411765，非独立评测 |
| `docs/project-status.md` | Fold0 中间模型段落只复述 425 条上述两项，非独立评测 |
| `docs/results/model-gate-baseline-20260914.md` | 第 3 节表只列 425 / 1,581 / 1,216 三行；第 66 行明写不读取或重述受限 test 逐样本内容 |
| `docs/project-todo.md` | 「开发评测侧对齐训练/服务」「开发输入现场（2026-10-16）」「本轮输入核验（2026-10-16）」三条的口径记录 |

## 7. 声明

- 本档案未修改任何既有记录（`finetune/results/**`、`docs/results/**` 既有文件、JSON、代码均未改动），只新增本档案两个文件。
- 未运行任何模型（未训练、未推理、未评测、未连接训练机）。
- push 无 force（普通推送）。
