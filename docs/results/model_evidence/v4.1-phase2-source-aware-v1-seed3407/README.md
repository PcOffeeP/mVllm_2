# 归档证据包：v4.1-phase2-source-aware-v1-seed3407

## 1. 模型身份
- 运行标识：`v4.1-phase2-source-aware-v1-seed3407`
- 模型名：`v4.1-sampling-source-aware-fold0-r1`（source-aware(r1)）
- 生命周期状态：`evaluated`
- Fold：0
- 数据集 release：`v4.1.0-ecb5aeb9657c`
- 合约版本：`tensile-vlm/v4.1`；合约 hash：`47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`
- 模型产物目录：`workspace/runs/v4.1-phase2-source-aware-v1-seed3407/fold0/merged`（adapter 位于 `fold0/adapter/`）

## 2. 训练配置
- 数据 release：`v4.1.0-ecb5aeb9657c`
- 训练数据：fold0 验证 425 行，训练采样 3000 行/epoch
- 采样：`source-aware-3k-dd89b70e9d63`（seed 3407）
- 超参：epochs 3.0，grad accum 8，总 steps 1125，train runtime 16730.6s
- Best metric：0.05644451826810837
- Best checkpoint：checkpoint-200
- training_code_commit：`f6ba152121d394141ddddaf73926e3a9c065d0a8`
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
| joint | 36.24% | 41.18% |
| clip_state | 47.76% | 56.00% |
| mechanism | 55.06% | 45.88% |
| site | 57.41% | 54.82% |

> 本模型 source-aware(r1) 各项与 r1 的百分点差（正=高于 r1，负=低于）：
- 相对 r1：valid +0.00 个百分点
- 相对 r1：joint -4.94 个百分点
- 相对 r1：clip_state -8.24 个百分点
- 相对 r1：mechanism +9.18 个百分点
- 相对 r1：site +2.59 个百分点
> r1 基准：valid 100%、joint 41.18%、clip_state 56%、mechanism 45.88%、site 54.82%。

## 5. 失败特征
- 严格有效率 100.00%（contract_valid 100.00%）。
- 分项正确率：clip_state 47.76%、mechanism 55.06%、site 57.41%。
- target clip_state 分布：{"临界未断裂": 57, "发生断裂": 144, "已断裂": 33, "未断裂": 191}。
- 详细逐样本见 evaluation_records.jsonl（仅哈希）。

## 6. 证据清单（已归档小文件）
| 子目录 | 内容 |
| --- | --- |
| identity/ | run_identity.json、model_identity.json |
| evaluation/ | evaluation_summary.json |
| input/ | `training_run_manifest.json` |
| adapter/ | trainer_state.json、adapter_config.json、train_results.json、eval_results.json、all_results.json、training_loss.png、training_eval_loss.png |

## 7. 已清除/仅哈希的大文件
- adapter/adapter_model.safetensors：sha256 `13d56ca4010ded03bd1b9570ffc72ef47f57ab5c3f3cbc3a45ee2b9e6c573616`（460430776 B）
- merged/（30 文件，总 17407993021 B）：
  - `added_tokens.json`: sha256 `1f41288392d77dd5dd9f235bdef78a3152d41651ff56b15ebdec476e3aa1cb7f` (2862 B)
  - `chat_template.jinja`: sha256 `56786063c90f9f67402d4d9af27f5c17f206467d577dc04d6dcfee2d57c8a2f0` (4229 B)
  - `config.json`: sha256 `2b6c82b8fe27e7e59412a54050f96968861c1c4b165406b3bd6a21b82abbade1` (2440 B)
  - `configuration_minicpm.py`: sha256 `bfdb65b291246e0d709831df2e10aaba96b94d2369f670f3ad831711d2f97e45` (3288 B)
  - `generation_config.json`: sha256 `b7ba498b309c1b46b7da2d5ae7699bc608bca1a6e2cad1ae0bab2959c535e7a0` (276 B)
  - `image_processing_minicpmv.py`: sha256 `52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7` (20757 B)
  - `merges.txt`: sha256 `8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5` (1671853 B)
  - `model-00001-of-00010.safetensors`: sha256 `29049c32883bb349fd5afefcbe8a48cbce7df8aaaa9ca0ed4337a20c707ddeed` (1914228064 B)
  - `model-00002-of-00010.safetensors`: sha256 `89a42f8871a868cf3d897b1b537ad8367b437b5639ae14759aed1c1fc3c3e2d9` (1929470832 B)
  - `model-00003-of-00010.safetensors`: sha256 `cd2dd227777de764ea34177c305701ca3df8527f9bea327804ca243f02a472eb` (1929470856 B)
  - `model-00004-of-00010.safetensors`: sha256 `304e13b2c1b07c28569ff1bc6bd3b81034f1ee779de80a4944e5b26c361114eb` (1929470888 B)
  - `model-00005-of-00010.safetensors`: sha256 `624378d9e31f5aa9fc0d89dd68c9e9532af323a1ba25657e85cb4627cccdbf9d` (1929470888 B)
  - `model-00006-of-00010.safetensors`: sha256 `8c18918e693db848ff033d87ddbb68f144d6868344e28fb4c66416c8de871a48` (1929470888 B)
  - `model-00007-of-00010.safetensors`: sha256 `60edc0f2041fc4d3b88116570996aa1d767ed4467d7e631b0e1748ff55fd8c87` (1929470888 B)
  - `model-00008-of-00010.safetensors`: sha256 `ad51ea16a125933fc758d6870a3849ddce56049cf8535947d528d16cf7eef5aa` (1644265032 B)
  - `model-00009-of-00010.safetensors`: sha256 `6de6bdaf2000a623b9b2c0c263dc68c0528fbe9166147fc2d28c52c97f9b682a` (1997939416 B)
  - `model-00010-of-00010.safetensors`: sha256 `861f2beb2ee27af2251193839adb34a2361d620cb93e43da20c0002d9e8e622b` (258632328 B)
  - `Modelfile`: sha256 `95d2a815e542d15e9f7a4feeab46402d7f8cef3b63ba3c26a5c4d9f6e70f8e9f` (424 B)
  - `modeling_minicpmv.py`: sha256 `f385948d8321fc9e30b178f7bb39020c845c7b367eeb0b762a50746368b25d10` (18609 B)
  - `modeling_navit_siglip.py`: sha256 `c71ca316fe7405325b7097364f98f71c317fff8c9f5c8820f30d3362b1ed5bfa` (41835 B)
  - `model.safetensors.index.json`: sha256 `39760fa6d7171527eaf19fe8830717b2cc5e2eaadaa677d0375595cb54c01095` (72209 B)
  - `preprocessor_config.json`: sha256 `0de71dc9a792f99a6ca9270f4d5b28b632b488c89d8a8ea42dac346fe43e858a` (934 B)
  - `processing_minicpmv.py`: sha256 `aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd` (11026 B)
  - `processor_config.json`: sha256 `67cf814ee0c745e7f4de82606d2e0a7ea3b2f8879845a4566f0b37c4a164496b` (127 B)
  - `resampler.py`: sha256 `9258b6e6e0b66fd5d3ce7127372fd82eff3659481602658045c253ae18e8d5be` (11732 B)
  - `special_tokens_map.json`: sha256 `447547e6205a50dad31cc19dcc3344bbef4e03c8aa6d428067e6cc671d72703b` (2450 B)
  - `tokenization_minicpmv_fast.py`: sha256 `770e4a934f2e74e0e88e85126bceea93e345d84b411d21e99b38c5cfd095f736` (1647 B)
  - `tokenizer_config.json`: sha256 `8bd65a16f51ab20577cfdc54d5de224450540e48f1a18578c4207b3615b862d3` (21542 B)
  - `tokenizer.json`: sha256 `c5a94a2c3913b8aa2175fffb5fd6cf4301958f323d06475bfd91037c13bdd74b` (11437868 B)
  - `vocab.json`: sha256 `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` (2776833 B)
- evaluation/evaluation_records.jsonl：sha256 `0d8817675fc3777f910451bb8049335648e596c9f019e4753fec35aa68f38ca5`（415832 B）

## 8. 缺口说明
- `evaluation/evidence_manifest.json`
- `input/experiment_contract.json`
- `input/summary.json`
- `input/dataset_info.json`
- `logs/`
- `input/merged_model_file_manifest.json`（训练机未生成，改用 run 目录 merged/ 实际哈希）
- 说明：本模型 run 目录为 `fold0/` 结构，任务模板所指 `evaluation/`、`input/`、`logs/` 目录在 run 目录内不存在；评测产物实际位于 finetune/results 对应实验路径，已从该处采集真实数据。
- 原 run 目录 `workspace/runs/v4.1-phase2-source-aware-v1-seed3407/` 暂未删除（本阶段仅归档，不删除）。

## 9. 完整哈希见 MANIFEST.json
MANIFEST.json 含 run_id、fold、release、合约、采样、训练超参、adapter/merged/eval_records 的 sha256 与大小，以及本证据包逐文件 sha256。
