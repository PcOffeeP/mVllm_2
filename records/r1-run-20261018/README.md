# R1 训练过程信息（`records/r1-run-20261018/`）

## 1. 这是什么

本目录是 R1 训练轮的过程信息副本，按训练机仓库内的原始相对路径结构落位，用于在 Git 中留存该轮的训练配置、运行日志、逐样本评测记录、数据采样清单与训练器状态等过程信息。

R1 = `v4.1-agent-pipeline-fold0-r1`，对应 run `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`，fold0 / seed 3407，coverage-first 策略，训练 1,125 步，best checkpoint = checkpoint-250。

本目录共 24 个同步文件，合计 3,995,388 B（不含本说明文件）。

## 2. 授权与例外声明

经用户 2026-10-18 明确授权，**仅此一轮 R1** 允许把逐样本评测记录等过程信息纳入 Git。该授权不适用于后续其余 run：其余 run 仍按 `.gitignore` 的「评测逐样本记录与一次性 smoke 输出只保留在训练机」政策执行，即 `/finetune/results/**/evaluation_records.jsonl` 继续被忽略。本次入库未改动 `.gitignore`。

## 3. 逐文件映射表

训练机原始绝对路径以 `<root>/<相对路径>` 表示，其中 `<root>` = `/home/liuyang/文档/mVllm_2`，训练机为 `liuyang@100.70.83.68`。字节数与 sha256 取自同步清单 `sync-manifest-20261018.md`（训练机一次性只读采集）；复制落位后已逐文件复算 sha256 与字节数，24/24 与清单一致。

| 本目录路径 | 训练机原始绝对路径 | 字节数 | sha256 |
|---|---|---|---|
| `records/r1-run-20261018/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/fold0/evaluation_records.jsonl` | `<root>/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/fold0/evaluation_records.jsonl` | 411826 | `4c8ea6c3bc77bc9aa05681d8f7033cacd72da541209750ffdc8b2959ced715a5` |
| `records/r1-run-20261018/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411/fold0/evaluation_records.jsonl` | `<root>/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411/fold0/evaluation_records.jsonl` | 408698 | `26073ce13b653bedf48f491d07d766ba47cb683e03b331a48e54470c2c0f6dfa` |
| `records/r1-run-20261018/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_runtime_contract_3798/fold0/evaluation_records.jsonl` | `<root>/finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_runtime_contract_3798/fold0/evaluation_records.jsonl` | 408763 | `067bca1c90b074fa8caad63b3b3f1981bb33880e746500291661c1e4fcae98a9` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/trainer_state.json` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/trainer_state.json` | 43857 | `6855109d36b2cb3981f4560e4e1e91e1e72a4184fb541fd7c924f0217368d10b` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/all_results.json` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/all_results.json` | 350 | `d3fecdc634306014ba775b6a26c70bc16500d69313af4629982d5293aff47d18` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/train_results.json` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/train_results.json` | 207 | `89bf51381e28f4905caf45c476ed3ac0554f4db407890a4af7df79d06cf90c7c` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/eval_results.json` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/eval_results.json` | 163 | `aac7ff7ea41cabfb429ea2bda000e36b8e277c21c05982cfb8d4debb017b443d` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/trainer_log.jsonl` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/trainer_log.jsonl` | 46969 | `68cdfb6847c13014eb75f7d1650aff1a57389585ec41f599a789bf6bb9cd95fa` |
| `records/r1-run-20261018/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/adapter_config.json` | `<root>/workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter/adapter_config.json` | 1123 | `d7dadf6efeed393a9379a14aadb29edddc3ee56261e758cba8e5177306493c0a` |
| `records/r1-run-20261018/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/run_manifest.json` | `<root>/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/run_manifest.json` | 1555 | `b7b76ade22d4fe042023d1095cff202a7a2ada697e9e91008145e22874dc4a3e` |
| `records/r1-run-20261018/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/train_seed3407.yaml` | `<root>/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/train_seed3407.yaml` | 1499 | `d3fd4000fb593c64fa653261fafda118651de2268b59195c6b94f8e46a89cac3` |
| `records/r1-run-20261018/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/train_seed3411.yaml` | `<root>/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/train_seed3411.yaml` | 1499 | `162feb83a162fd73109ec13dca21f21a0489e348b533051d4d8c4ba0a47e3cac` |
| `records/r1-run-20261018/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/merge_seed3407.yaml` | `<root>/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/merge_seed3407.yaml` | 462 | `cd2d0dfcef2decbfb7b91db61893d734bd23927060e5d2d3d9c04ba76b037c6a` |
| `records/r1-run-20261018/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/merge_seed3411.yaml` | `<root>/finetune/MiniCPM/config/active/v4_1_source_aware_3k_coverage_first/merge_seed3411.yaml` | 462 | `28a93aa390331ae1079fcee56daa917d73308b8a287acfd2c6dcf553065095f2` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_train.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_train.log` | 940563 | `ccf29fd91733abc2766883fb5093f5fabcefb323db0b5a6becbbb1e925ab378c` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_train.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_train.log` | 939723 | `96744cc55c5f26aedaaf01ee2e073c739de508cbf812fd3d3471fb6f54c7749b` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_evaluate.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_evaluate.log` | 43222 | `9a643b8832f5716c71a330d70c1d7aa711227df9a1ee8db7255270cb06171d2f` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_evaluate.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_evaluate.log` | 43149 | `0a199d2a5a0550336c4a4839915e5c9891d1e265fde7a7fa80bd9a90cbb8c785` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_merge.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_merge.log` | 27570 | `2a3ebf85f3bbb60ebcc5bf682d1180086f86252f20618d61d3bbe68d542be624` |
| `records/r1-run-20261018/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_merge.log` | `<root>/finetune/run_logs/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411_merge.log` | 27570 | `b0d2cd0548d8920dafdc486f06d44861402c20cd486bd3281da1fa2af0244526` |
| `records/r1-run-20261018/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/sampling_manifest.json` | `<root>/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/sampling_manifest.json` | 632717 | `d939fc004e3f9af4b4b0dad1ecad4ba6d9b8f4c862ee87fe4c47aae7c28a7038` |
| `records/r1-run-20261018/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/summary.json` | `<root>/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/summary.json` | 2150 | `74d592c4f87518ddbf135f1c93a7ed741d981c0455a9b4fdc4fa0de108933e8c` |
| `records/r1-run-20261018/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/dataset_info.json` | `<root>/workspace/data/derived/metadata/v4_1/source_aware_3k/source-aware-3k-2a84e8b6cfc3/dataset_info.json` | 1344 | `ff1f495d714595b6aad27568dd0eef579af280cd05186eb4a9a9a108223e2157` |
| `records/r1-run-20261018/finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json` | `<root>/finetune/results/v4_1_stage_b_intermediate_acceptances/stage-b-intermediate-8e1fdb09f8e6/intermediate_model_acceptance.json` | 9947 | `c31427bdebdffd49e83bb66fbeb663a992b69d36c56b477dc58b2e9080885cd1` |

## 4. 权重不在本目录，也不应入 Git

LoRA adapter（460,430,776 B）与 merged 全量权重（10 个分片，合计 17,391,890,080 B）均不在本目录，也不应纳入 Git。二者仅存在于训练机：adapter 位于 `workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0/adapter`，merged 位于 `workspace/models/releases/v4.1-agent-pipeline-fold0-r1/merged`。本目录只保留上述 adapter 目录中的配置与训练过程文件，权重文件本身未同步。

另需注意：`LlamaFactory/saves/...` 下对应目录是指向上述真实路径的**符号链接**，直接 `du` 只会得到 79 B / 73 B 的链接自身大小，不能据此判断权重体积。

## 5. 与 R1 数字无关的目录

`docs/results/model_evidence/v4.1-phase2-source-aware-v1-seed3407/` 的 `model_dir` 指向 `dd89b70e9d63`（joint 0.362353），那**不是 R1**，不得当作 R1 的数字使用。
