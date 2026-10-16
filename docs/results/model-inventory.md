# V4.1 模型清单与效果对比

> 本文保留历史阶段记录。2026-09-14现场模型资产与新体系门禁背景见[2026-09-14模型核查档案](model-gate-baseline-20260914.md)；历史工程通过、旧指针及清单中的存活状态不代表当前新门禁通过。

本文记录 V4.1 阶段各训练模型的「数据 release / Prompt revision / 训练参数 / 效果指标」，
作为后续清除过程模型前的信息留存。2026-08-31 已对本地证据与训练机进行只读核查。
本文仍是归档准备清单，**尚不能作为删除放行单**；历史报告不等于当前权重仍存在。
当前文件状态、归档缺口和清理边界见第 8 节；未确认内容不补造。

2026-10-16补充：已对当前基座及旧Fold0 adapter计算完整SHA，并核已知minimal归档位置；归档的原始评测记录副本缺失、原run对应文件仍在（仅stat）。本历史清单不据此升级清理资格，详情见[当前核验与限制](todo-preparation-progress-20261016.md)。

## 1. 目的与范围

- 目的：在清除过程模型前，留存每个模型的发布身份、训练配置与效果证据。
- 范围：V4.1 阶段全部已登记模型（含已发布、已删除、仅 input 无权重）。
- 口径：效果指标以严格推理评测为准（JSON/contract 合法率、四字段正确率、joint correct）。
  不同 release 的全量指标不能直接作为因果对比，跨 release 结论需结合共同样本。

## 2. 数据 release 两版

V4.1 阶段存在两个内容寻址、不可覆盖的训练数据发布，共享同一 V4.1 契约
（contract hash `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`）。

| 项目 | 基础三折发布 | phase2 development release |
| --- | --- | --- |
| release ID | `v4.1.0-760050fad303` | `v4.1.0-ecb5aeb9657c` |
| 物化候选 | 1285 | — |
| 正式发布候选 | 1275 | 1678（= 基础 +403） |
| `effective_frame_signature` 字段 | 无 | 有（新增） |
| 活跃指针 | 否 | 是（当前活跃） |
| Fold 0 train / val | 850 / 425 | 1253 / 425 |
| Fold 1 train / val | 830 / 445 | 1014 / 664 |
| Fold 2 train / val | 929 / 346 | 1186 / 492 |

要点：

- `v4.1.0-ecb5aeb9657c` 在基础发布基础上新增 403 条候选，并新增
  `effective_frame_signature` 字段；当前活跃指针指向它。
- 两个发布共享 V4.1 契约，但样本集不同；跨 release 比较必须提供共同样本分析，
  不能把全量指标差异直接归因于 Prompt 或训练策略。

## 3. 模型清单

编号沿用原清单，新增项追加，不表示日期顺序。状态说明：`存活` = 本轮发现权重文件，
不表示已通过哈希验证；`历史已删记录` = 前序记录，本轮未核实删除事件；
`仅 input` = 当前目录只见输入，无权重；`未找到` 不等于已证明删除。

| # | 模型 / 实验 ID | 数据 release | Prompt revision | 状态 |
| --- | --- | --- | --- | --- |
| 1 | `v4.1-agent-pipeline-fold0-r1`（来源 `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`） | `v4.1.0-ecb5aeb9657c` | V4.1 契约 Prompt | 存活（已发布） |
| 2 | coverage-first seed3411（fold0） | `v4.1.0-ecb5aeb9657c` | V4.1 契约 Prompt | 存活 |
| 3 | coverage-fallback seed3413（fold0） | `v4.1.0-ecb5aeb9657c` | V4.1 契约 Prompt | 存活 |
| 4 | prompt-minimal seed3411（fold0） | `v4.1.0-ecb5aeb9657c` | `v4.1-fixed-full-fields-initial-v1` | 存活 |
| 5 | prompt-concise-v1 seed3411 | `v4.1.0-ecb5aeb9657c` | `v4.1-concise-evidence-json-v1` | 仅 input |
| 6 | prompt-concise-v2 seed3411 | `v4.1.0-ecb5aeb9657c` | `v4.1-concise-evidence-json-v2` | 仅 input（后转三折） |
| 7 | `v4.1-prompt-concise-cv-v1-seed3411`（三折） | `v4.1.0-ecb5aeb9657c` | `v4.1-concise-evidence-json-v2` | 约定路径未找到，待查备份 |
| 8 | `v4.1-visual-cv-v1-seed3407`（三折） | `v4.1.0-760050fad303` | — | 历史已删记录 |
| 9 | `v4.1-language-cv-v1-seed3407`（三折） | — | — | 历史已删记录 |
| 10 | `v2.0.0-1dab1e5e`（fold0/1/2/full） | — | — | 历史已删记录 |
| 11 | source-aware seed3407（fold0，`v4.1-sampling-source-aware-fold0-r1`） | `v4.1.0-ecb5aeb9657c` | 契约 Prompt，精确内容待归档绑定 | 存活，原清单漏列 |
| 12 | source-aware seed3411（fold0，`v4.1-sampling-source-aware-fold0-r2`） | `v4.1.0-ecb5aeb9657c` | 契约 Prompt，精确内容待归档绑定 | 存活，原清单漏列 |

## 4. 训练参数

下表是参数摘要，不是完整可复现实验配置。权重缺失不应成为丢弃已有历史参数或结果的理由；
历史模型仍应从已有 manifest/报告补录，并标记来源与缺口。

| # | 模型 | seed | lr | epochs | batch | grad accum | steps | 早停 | best checkpoint |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 1 | r1（coverage-first seed3407） | 3407 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 250 |
| 2 | coverage-first seed3411 | 3411 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 200 |
| 3 | coverage-fallback seed3413 | 3413 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 200 |
| 4 | prompt-minimal seed3411 | 3411 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 250 |
| 7 | concise-cv 三折（历史报告） | 3411 | 5e-6 | 2（上限） | 1 | 8 | 300/350/250 | patience 3 | 225/275/175 |
| 11 | source-aware seed3407 | 3407 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 200 |
| 12 | source-aware seed3411 | 3411 | 5e-6 | 3 | 1 | 8 | 1125 | 无 | 200 |

补充说明：

- 模型 1–4 使用同一 release 的 fold0 train 池（1253 条），每份训练输入 3000 行、
  计划 3 epoch。它们并非同一份固定采样序列：模型 1 的 dataset 键为
  `tensile_v4_1_phase2_3k_seed3407`，模型 2 为 `tensile_v4_1_phase2_3k_seed3411`；
  模型 4 的 input summary 记录 coverage-first 的 seed3411 序列及 Prompt 替换后的输入哈希。
  coverage-first 配额为未断裂 900 + 其他三态 2100，source 上限 5%、
  effective-frame signature 上限 3；各实际序列以对应 sampling manifest/哈希为准。
- 模型 3 将采样换成 coverage-fallback（canary 未过开发门后的回退采样）。
- 模型 4 的实验意图是替换 Prompt 为 `v4.1-fixed-full-fields-initial-v1`（system 444 / user 39，
  删掉时序判定语义/字段联动/null 约束）；名义数据/采样与主要超参参考 r1，
  但 seed 不同，adapter 配置记录 PEFT 0.19.1（r1 为 0.18.1），不能视为已控制全部变量。
- 模型 7 为三折交叉验证，25-step eval/save、`early_stopping_patience=3`，三折最佳
  checkpoint 分别为 225 / 275 / 175。

## 5. 效果对比

横向对比各模型效果指标（valid = JSON/contract 合法率，joint = joint correct）。

| # | 模型 | valid | joint | clip_state | mechanism | site | special_case |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | r1（coverage-first seed3407，fold0） | 100.00% | 41.18% | 56.00% | 45.88% | 54.82% | 100% |
| 2 | coverage-first seed3411（fold0） | 100.00% | 37.41% | 55.76% | 44.00% | 51.06% | 100% |
| 3 | coverage-fallback seed3413（fold0） | 100.00% | 35.06% | 54.59% | 44.47% | 52.71% | 100% |
| 4 | prompt-minimal seed3411（fold0） | 86.12% | 24.00% | 35.06% | 38.82% | 39.76% | 86.12% |
| 7 | concise-cv 三折（fold0） | 89.41% | 43.53% | 46.35% | 47.06% | 46.12% | 89.41% |
| 7 | concise-cv 三折（fold1） | 71.08% | 23.19% | 26.66% | 26.81% | 29.82% | 71.08% |
| 7 | concise-cv 三折（fold2） | 82.72% | 34.15% | 39.02% | 35.16% | 40.24% | 82.72% |
| 7 | concise-cv 三折（三折加权） | 79.63% | 32.07% | 35.80% | 34.85% | 37.44% | 79.63% |
| 11 | source-aware seed3407（fold0） | 100.00% | 36.24% | 47.76% | 55.06% | 57.41% | 100% |
| 12 | source-aware seed3411（fold0） | 100.00% | 41.18% | 51.06% | 52.71% | 58.59% | 100% |

参考（历史完整三折，来自 `docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md`，
非任务提供事实，仅作背景）：

| 模型 | release | 样本 | valid | joint | clip_state | mechanism | site |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 历史 visual 三折 `v4_1_0_760050fad303_20260724_visual` | `760050fad303` | 1216 | 97.12% | 40.21% | 49.67% | 50.66% | 56.66% |

## 6. 关键结论

1. **r1 是当前发布基线**：本轮发现 `workspace/models/releases/` 仅保留该发布身份，
   不等于质量验收已通过；注册表仍为 `production_approved: false`。
2. **未见替代发布，不能据此判定所有指标最优**：concise fold0 joint 为 43.53%，
   高于 r1 的 41.18%，但合法率更低；source-aware seed3411 的 mechanism/site 也更高。
   跨契约与不同实验因素的结果只能作描述性比较，不能直接归因。
3. **精简 Prompt 实验出现退化，但根因尚未隔离**：
   - minimal（`v4.1-fixed-full-fields-initial-v1`）记录合法率下降
     （100% → 86.12%），joint 下降 17.18pp（41.18% → 24.00%）。
   - concise 三折出现类别坍缩：68.88% 预测为「未断裂」，临界未断裂 / 已断裂召回为 0%。
4. **权重缺失与记录保存分开判断**：visual-cv、language-cv、V2 的删除状态沿用历史记录；
   concise-cv 本轮在约定位置未找到。已有参数、指标和原始预测仍有归档价值。

## 7. 证据与限制

- 模型 1 的评测源：[runtime-contract 3798 摘要](../../finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407_runtime_contract_3798/fold0/evaluation_summary.json)。
- 模型 2：[评测摘要](../../finetune/results/v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3411/fold0/evaluation_summary.json)；模型 3：[评测摘要](../../finetune/results/v4_1_phase2_coverage_first_fallback_seed3413/seed3413/fold0/evaluation_summary.json)。
- 模型 4：训练机 `workspace/runs/v4.1-prompt-minimal-v1-seed3411/evaluation/evaluation_summary.json`，本轮内容已收入第 8 节快照；原始逐样本记录未复制到本快照。
- 模型 7 及历史 visual 对比：[三折报告](v4_1_prompt_concise_cv_v1_seed3411/README.md)。本轮只核报告，没有重跑三折评测或验证缺失权重。
- 模型 11/12：[seed3407 摘要](../../finetune/results/v4_1_phase2_source_aware_3k_dd89b70e9d63/seed3407/fold0/evaluation_summary.json)、[seed3411 摘要](../../finetune/results/v4_1_phase2_source_aware_3k_dd89b70e9d63/seed3411/fold0/evaluation_summary.json)；同目录上层 `training_run_manifest.json` 记录训练代码、采样序列哈希、best step 等，训练 YAML 在 `finetune/MiniCPM/config/active/v4_1_source_aware_3k/`，归档前需校验其与 manifest 哈希一致。
- **数据契约与推理契约不同**：第 2 节的 `47e393...` 是数据发布契约；模型 1–4 上述推理记录为 `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`，模型 11/12 为 `47e393...`。相同 V4.1 标签不能代替逐次评测的契约和 Prompt 内容绑定。
- 本文修正事实与归档要求，不修改配置、契约、指针，不删除远程文件。数字摘录与文件存在性核查不等于本轮完整模型质量验收。

## 8. 2026-08-31 清理可行性核查

**结论：目标可行，当前留存仍不足以放行删除；先补证据归档，再按明确文件清单清理。**
记录超参数和历史结果支持追溯，但不能恢复学得的权重，也不能支持新样本推理或中间 step 诊断。

### 8.1 实际文件与体量

证据：[训练机只读快照](model-inventory-audit-20260831/remote_snapshot.json)。
采集于训练机 `dell-Precision-3660`、项目 `/home/liuyang/文档/mVllm_2`；远端 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，工作区干净；本地核查基线 `main@7b8192bd197ad8c94e38d0a5ab1776450e4f7a50`，比远端多 3 个提交，远端独有 0 个。本轮没有同步或更改训练机。

以下路径相对训练机项目根；占用按分配字节计，不跟随软链接，GiB = 2^30 字节。

| `workspace/runs/` 下目录 | 本轮实际状态 | 占用 | 建议边界（未获删除放行） |
| --- | --- | ---: | --- |
| `v4.1-phase2-source-aware-v1-seed3407` | root adapter + merged | 16.656 GiB | 补齐归档及诊断取舍后列为候选 |
| `v4.1-phase2-source-aware-v1-seed3411` | root adapter + merged | 16.656 GiB | 同上 |
| `v4.1-phase2-coverage-first-v1-seed3411` | root adapter + merged | 16.656 GiB | 同上 |
| `v4.1-phase2-coverage-fallback-v1-seed3413` | root adapter + merged | 16.656 GiB | 同上 |
| `v4.1-prompt-minimal-v1-seed3411` | root adapter + merged + input/logs/evaluation | 16.663 GiB | 同上；不能整目录删掉唯一结果 |
| `v4.1-phase2-coverage-first-v1-seed3407` | root adapter + 5 个 checkpoint，merged 为指向发布库的软链接 | 6.953 GiB | 当前保留策略保护，暂不清理 |
| `v4.1-prompt-concise-v1-seed3411` / `v4.1-prompt-concise-v2-seed3411` | 仅输入和配置 | 合计约 11.5 MiB | 保留，清理收益很小 |
| `v4.1-prompt-concise-cv-v1-seed3411` | 约定路径不存在 | 不计 | 查备份/迁移位置；不能继续写“存活” |

`workspace/runs` 总计约 **90.253 GiB**（`du -sh` 四舍五入显示 91G）。前五组仅 merged 权重约 **80.988 GiB**，各 root LoRA 权重约 **439.1 MiB**。这是候选体量，不是已批准可释放空间。
`workspace/models` 另约 17 GiB，不在本次候选范围。r1 的 runs/merged 链接指向发布库，不能把解析后的发布模型路径加入清理清单。

本轮在 `workspace` 与 `LlamaFactory/saves` 常规层级搜索只见 concise 两组单折输入；没有扫描训练机其他目录或备份设备，因此不推断 concise-cv 已永久删除。部分 `model_identity.json` 仍写 5 个 checkpoint，但实际对应 run 已无 checkpoint，说明静态元数据不能替代文件盘点。

### 8.2 删除前必须保留的信息

每个实际训练模型、每个 fold 单独绑定以下证据；摘要中无空间展开的内容保留原文件并链接，不增加多份重复叙述。

> 已归档证据包统一位于 [模型归档证据包索引](model_evidence/README.md)，按 `model_id/` 存放于 `docs/results/model_evidence/`。该链接**仅作为证据定位入口**，索引内已有目录不等于归档已完整、也不等于清理已放行；能否删除仍以本节归档验收条件与 TODO 的 MODEL-ARCHIVE 显式授权为准。

| 信息 | 最小留存内容 |
| --- | --- |
| 模型身份 | experiment/model ID、fold/seed、基座精确 revision 与哈希、训练代码 commit/未提交补丁、根 adapter/merged/选中 checkpoint 的文件 SHA-256、历史路径→当前路径映射 |
| 完整训练配置 | 实际 train/merge YAML、adapter config（rank/alpha/dropout/target/modules_to_save）、量化/精度、视觉帧参数、optimizer/scheduler/warmup、batch/accum、step/epoch、保存与早停规则；不能只留 lr/epochs 表格 |
| 数据与 Prompt | release manifest/契约原文及哈希、fold 划分、实际采样序列与哈希、数据构建配置、Prompt 原文/revision、训练契约与推理契约分别保存 |
| 训练过程 | trainer_state（包括完整 log_history）、trainer_log、train/eval/all_results、最佳与停止 step、best checkpoint 与最终导出权重对应证据 |
| 效果证据 | 每次开发评测的 run_identity、生成参数、评分代码版本、evaluation_summary 与 evaluation_records 原始预测、四字段正确率、合法率、各状态召回/混淆矩阵、joint、分布与失败样例；已有受限测试材料维持原访问边界 |
| 归档验收 | 按实际路径列文件大小/SHA-256、缺失项及原因、独立副本位置与复核结果、明确只留历史记录还是需再次推理；归档已提交/备份后才提交删除候选单 |

本轮 `remote_snapshot.json` **仅为审查快照，不是上述完整归档包**：没有读取并哈希大权重、没有复制原始预测/完整训练日志，trainer_state 的 log_history 已省略；快照内元数据 SHA-256 对应原始源文件，不对应删减后的嵌入内容。它不能用于宣称归档完成或模型可恢复。

本地核对还发现：source-aware、coverage-first、fallback 共 6 份开发评测摘要旁均无
`evaluation_records.jsonl`，尚未证明远端这些原始预测已独立备份；concise 报告所指
`finetune/experiments/` 配置集合本地也不存在。需要查找原始产物或登记无法补回的证据缺口，
不能仅凭汇总表宣称“所有参数、结果已留全”。

### 8.3 可选择的保留层级与当前限制

- **只保留研究记录**：完整冻结上述证据后，可将已明确退役、无后续模型依赖的 adapter/merged/训练恢复状态纳入删除候选；代价是永久失去该权重的新推理能力。重新训练不能保证得到同一模型。
- **兼顾空间和后续使用**：保留约 439 MiB 的原始 adapter、准确基座及自定义模型/processor 代码、配置和合并环境，优先考虑删除约 16.2 GiB 的 merged 权重。必须先验证重新合并链路；不能以“4-bit 基座直挂 adapter”替代历史 merged BF16 评测口径。本轮未进行恢复/合并验证。
- **当前发布与诊断**：保留 `workspace/models/releases/v4.1-agent-pipeline-fold0-r1`；[checkpoint 保留策略](../../pipeline/checkpoint_policy.json) 还保护 r1 来源及 concise 三折。TODO 的 MODEL-DIAG 需要模型交叉推理/中间 step 评测；要删除其依赖，须先完成对应诊断或由用户明确取消该诊断目标。本次提出节省空间不自动等于取消诊断。
- **现有工具不能代替新清理方案**：[serve_manage_checkpoints.py](../../scripts/serve_manage_checkpoints.py) 仅针对 checkpoint 子目录，不是 root adapter/merged 或整个 run 的归档清理器。不能直接套用到本次目标。
- **执行前再验证**：核对两机 Git、真实路径/链接、当前模型完整性、在用进程与文件占用、归档校验及备份；固定显式路径清单，排除发布库、基座、数据、证据目录。这里只读核查不构成删除授权，不提供整目录通配删除命令。

状态与下一动作统一追踪于 [project-todo.md](../project-todo.md) 的 MODEL-ARCHIVE；MODEL-DIAG 的权重缺失需同步处理。
