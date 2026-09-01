# 归档证据包：v4.1-prompt-minimal-v1-seed3411

## 1. 模型身份
- 运行标识：`v4.1-prompt-minimal-v1-seed3411`
- Fold：0
- 数据集 release：`v4.1.0-ecb5aeb9657c`
- 合约版本：`tensile-vlm/v4.1`；合约 hash：`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`
- 模型产物目录：`workspace/runs/v4.1-prompt-minimal-v1-seed3411/merged`

## 2. 训练配置
- 数据 release：`v4.1.0-ecb5aeb9657c`
- 训练数据：`tensile_v4_1_fixed_full_fields_seed3411`（训练 3000 行，验证 425 行）
- 采样：`source-aware-3k` coverage-first（sampling_id `source-aware-3k-2a84e8b6cfc3`）
- Prompt：`v4.1-fixed-full-fields-initial-v1`（prompt_revision_id）
- Seed：3411
- 超参：lr 5e-6，epochs 3，batch 1，grad accum 8，共 1125 steps
- 早停：无
- Best checkpoint：step 250

## 3. 评测对象与数据
- 评测集：fold_0_validation，共 425 条
- 运行失败（runtime failure）：0 条
- 严格有效（strict valid）：366 条（86.12%）
- 逐样本记录见大文件 `evaluation_records.jsonl`（已在独立存储中清除，仅保留哈希）

## 4. 效果指标（vs r1）
| 指标 | 本模型 | r1 |
| --- | --- | --- |
| valid | 86.12% | 100% |
| joint | 24.00% | 41.18% |
| clip_state | 35.06% | — |
| mechanism | 38.82% | — |
| site | 39.76% | — |

> r1 的 valid 为 100%，joint 为 41.18%。本模型在 joint 与各分项（clip_state/mechanism/site）上均低于 r1，说明提示词精简方向对结构化字段抽取与联合正确率造成明显回退。

## 5. 失败特征
- 严格有效率从 r1 的 100% 降至 86.12%（59 条被判为 `__invalid__`）。
- clip_state 混淆矩阵显示，`未断裂`（33 条 invalid）与 `发生断裂`（12 条 invalid）中 invalid 占比最高，主要发生在状态类别边界 / 表述不规范的样本上。
- 分项正确率偏低（clip_state 35.06%、mechanism 38.82%、site 39.76%），说明精简提示词削弱了字段格式约束与分步推理引导。

## 6. 证据清单
| 子目录 | 内容 |
| --- | --- |
| identity/ | run_identity.json |
| evaluation/ | evaluation_summary.json、evidence_manifest.json |
| input/ | experiment_contract.json、summary.json、dataset_info.json |
| logs/ | train.log、merge.log、evaluation.log、evaluation.exit（若存在） |
| adapter/ | trainer_state.json、training_loss.png、training_eval_loss.png |

## 7. 已清除/仅哈希的大文件
- adapter/adapter_model.safetensors：sha256 `55c8e446af827cfb8c2c3cb0ac1aed8dc88bffb9641fb2713fc188dbb3df3e18`（~460MB）
- merged/（10 分片，共 ~17GB，总字节 17407993021）
- evaluation/evaluation_records.jsonl：sha256 `a32f3e30c494af3ee424ad29a77f3db4f5f664bb966dc88048ed572bee313300`

## 8. 缺口说明
- 本证据包仅含小而关键的文件；adapter、merged、evaluation_records 三大文件仅保留哈希，未纳入本包（受空间约束）。
- 训练日期未作为结构化字段记录于源 JSON，MANIFEST 中 `training_date` 为 null。
- 原 run 目录 `workspace/runs/v4.1-prompt-minimal-v1-seed3411/` 暂未删除（归档试点阶段保留，供回滚/复核）。

## 9. 完整哈希见 MANIFEST.json
MANIFEST.json 包含 run_id、fold、release、训练数据、采样、Prompt、训练超参、adapter/merged/evaluation_records 的 sha256 与大小，以及本证据包逐文件 sha256 清单。
