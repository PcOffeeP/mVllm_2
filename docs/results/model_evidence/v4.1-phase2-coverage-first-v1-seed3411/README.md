# 归档证据包：v4.1-phase2-coverage-first-v1-seed3411

## 1. 模型身份
- 运行标识：`v4.1-phase2-coverage-first-v1-seed3411`
- 模型名：`v4.1-sampling-coverage-first-fold0-r1`（coverage-first）
- 生命周期状态：`evaluated`
- Fold：0
- 数据集 release：`v4.1.0-ecb5aeb9657c`
- 合约版本：`tensile-vlm/v4.1`；合约 hash：`3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`
- 模型产物目录：`workspace/runs/v4.1-phase2-coverage-first-v1-seed3411/fold0/merged`（adapter 位于 `fold0/adapter/`）

## 2. 训练配置
- 数据 release：`v4.1.0-ecb5aeb9657c`
- 训练数据：fold0 验证 425 行，训练采样 3000 行/epoch
- 采样：`source-aware-3k-2a84e8b6cfc3`（seed 3411）
- 超参：epochs 3.0，grad accum 8，总 steps 1125，train runtime 16790.4s
- Best metric：0.05516669899225235
- Best checkpoint：checkpoint-200
- training_code_commit：`f54d9ca617e455454f28e31ae058eda2dfdb5ec7`
- adapter 覆盖：resampler_weight 13，visual_weight 324，target_module 11

## 3. 评测对象与数据
- 评测集：fold0 validation，共 425 条
- 运行失败（runtime failure）：0 条
- 严格有效（strict valid）：425 条（100.00%）
- 逐样本记录见 eval_records.jsonl（已归档哈希，不复制大文件）

## 4. 效果指标（vs r1）
| 指标 | 本模型 | r1 |
| --- | --- | --- |
| valid | 100.00% | 100% |
| joint | 37.41% | 41.18% |
| clip_state | 55.76% | 56.00% |
| mechanism | 44.00% | 45.88% |
| site | 51.06% | 54.82% |

> 本模型 coverage-first 各项与 r1 的百分点差（正=高于 r1，负=低于）：
- 相对 r1：valid +0.00 个百分点
- 相对 r1：joint -3.77 个百分点
- 相对 r1：clip_state -0.24 个百分点
- 相对 r1：mechanism -1.88 个百分点
- 相对 r1：site -3.76 个百分点
> r1 基准：valid 100%、joint 41.18%、clip_state 56%、mechanism 45.88%、site 54.82%。

## 5. 失败特征
- 严格有效率 100.00%（contract_valid 100.00%）。
- 分项正确率：clip_state 55.76%、mechanism 44.00%、site 51.06%。
- target clip_state 分布：{"临界未断裂": 57, "发生断裂": 144, "已断裂": 33, "未断裂": 191}。
- 详细逐样本见 evaluation_records.jsonl（仅哈希）。

## 6. 证据清单（已归档小文件）
| 子目录 | 内容 |
| --- | --- |
| identity/ | run_identity.json、model_identity.json |
| evaluation/ | evaluation_summary.json |
| input/ | `training_run_manifest.json`、`merged_model_file_manifest.json` |
| adapter/ | trainer_state.json、adapter_config.json、train_results.json、eval_results.json、all_results.json、training_loss.png、training_eval_loss.png |

## 7. 已清除/仅哈希的大文件
- adapter/adapter_model.safetensors：sha256 `3f83131667bc839dabeba0ff8a06590518cbef4382abbc089cdd0ee5d76a4da5`（460430776 B）
- merged/（30 文件，总 17407993021 B）：
  - `Modelfile`: sha256 `95d2a815e542d15e9f7a4feeab46402d7f8cef3b63ba3c26a5c4d9f6e70f8e9f` (424 B)
  - `added_tokens.json`: sha256 `1f41288392d77dd5dd9f235bdef78a3152d41651ff56b15ebdec476e3aa1cb7f` (2862 B)
  - `chat_template.jinja`: sha256 `56786063c90f9f67402d4d9af27f5c17f206467d577dc04d6dcfee2d57c8a2f0` (4229 B)
  - `config.json`: sha256 `2b6c82b8fe27e7e59412a54050f96968861c1c4b165406b3bd6a21b82abbade1` (2440 B)
  - `configuration_minicpm.py`: sha256 `bfdb65b291246e0d709831df2e10aaba96b94d2369f670f3ad831711d2f97e45` (3288 B)
  - `generation_config.json`: sha256 `b7ba498b309c1b46b7da2d5ae7699bc608bca1a6e2cad1ae0bab2959c535e7a0` (276 B)
  - `image_processing_minicpmv.py`: sha256 `52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7` (20757 B)
  - `merges.txt`: sha256 `8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5` (1671853 B)
  - `model-00001-of-00010.safetensors`: sha256 `d17dfad738a0e0dfb9337fe319a11dff9f34183433c201d0a497ba73b6ebc173` (1914228064 B)
  - `model-00002-of-00010.safetensors`: sha256 `4f9637ed7571ec8b1b11586dd1be6b4a1a4835ce6deb30098153fb3676f19f1a` (1929470832 B)
  - `model-00003-of-00010.safetensors`: sha256 `6fb422c2009577af7d0a61ac04abc86790d7af7146eda4ca790065d60fbcd439` (1929470856 B)
  - `model-00004-of-00010.safetensors`: sha256 `70b97819276f4fcf550ba29b7f3e77f79eacf940e71031cc3809577caba392f5` (1929470888 B)
  - `model-00005-of-00010.safetensors`: sha256 `f1f373fe3d568fb243702b30c8f44f2c111a1962344145072108f4b61be964d4` (1929470888 B)
  - `model-00006-of-00010.safetensors`: sha256 `7fb6fd407402b1a02f16750682ec46a8e0cf80b82c090cfd56c3e759aa3657cf` (1929470888 B)
  - `model-00007-of-00010.safetensors`: sha256 `8c19b5b4ecb0a05779a0d179cd9c3343a8585ebdd2ff6da531c6dfe2a2a146e2` (1929470888 B)
  - `model-00008-of-00010.safetensors`: sha256 `d8fba10829557df6fee86af94ab098c2c69f21d98e6a225d992c710bd96c79b0` (1644265032 B)
  - `model-00009-of-00010.safetensors`: sha256 `13941dfa32600409ea20700d18f5e8d29782030260d7c9fe14b80a307588ad35` (1997939416 B)
  - `model-00010-of-00010.safetensors`: sha256 `6ee035105a4a25358af869d06304467b0e4df675fd261be1df279653f9089200` (258632328 B)
  - `model.safetensors.index.json`: sha256 `39760fa6d7171527eaf19fe8830717b2cc5e2eaadaa677d0375595cb54c01095` (72209 B)
  - `modeling_minicpmv.py`: sha256 `f385948d8321fc9e30b178f7bb39020c845c7b367eeb0b762a50746368b25d10` (18609 B)
  - `modeling_navit_siglip.py`: sha256 `c71ca316fe7405325b7097364f98f71c317fff8c9f5c8820f30d3362b1ed5bfa` (41835 B)
  - `preprocessor_config.json`: sha256 `0de71dc9a792f99a6ca9270f4d5b28b632b488c89d8a8ea42dac346fe43e858a` (934 B)
  - `processing_minicpmv.py`: sha256 `aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd` (11026 B)
  - `processor_config.json`: sha256 `67cf814ee0c745e7f4de82606d2e0a7ea3b2f8879845a4566f0b37c4a164496b` (127 B)
  - `resampler.py`: sha256 `9258b6e6e0b66fd5d3ce7127372fd82eff3659481602658045c253ae18e8d5be` (11732 B)
  - `special_tokens_map.json`: sha256 `447547e6205a50dad31cc19dcc3344bbef4e03c8aa6d428067e6cc671d72703b` (2450 B)
  - `tokenization_minicpmv_fast.py`: sha256 `770e4a934f2e74e0e88e85126bceea93e345d84b411d21e99b38c5cfd095f736` (1647 B)
  - `tokenizer.json`: sha256 `c5a94a2c3913b8aa2175fffb5fd6cf4301958f323d06475bfd91037c13bdd74b` (11437868 B)
  - `tokenizer_config.json`: sha256 `8bd65a16f51ab20577cfdc54d5de224450540e48f1a18578c4207b3615b862d3` (21542 B)
  - `vocab.json`: sha256 `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` (2776833 B)
- evaluation/evaluation_records.jsonl：sha256 `26073ce13b653bedf48f491d07d766ba47cb683e03b331a48e54470c2c0f6dfa`（408698 B）

## 8. 缺口说明
- `evaluation/evidence_manifest.json`
- `input/experiment_contract.json`
- `input/summary.json`
- `input/dataset_info.json`
- `logs/`
- 说明：本模型 run 目录为 `fold0/` 结构，任务模板所指 `evaluation/`、`input/`、`logs/` 目录在 run 目录内不存在；评测产物实际位于 finetune/results 对应实验路径，已从该处采集真实数据。
- 原 run 目录 `workspace/runs/v4.1-phase2-coverage-first-v1-seed3411/` 暂未删除（本阶段仅归档，不删除）。

## 9. 完整哈希见 MANIFEST.json
MANIFEST.json 含 run_id、fold、release、合约、采样、训练超参、adapter/merged/eval_records 的 sha256 与大小，以及本证据包逐文件 sha256。
