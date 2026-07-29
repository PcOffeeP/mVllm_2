# mVllm_2

基于 MiniCPM-V-4.5 的材料拉伸视频数据、微调、评测与视觉服务仓库。

## 当前状态（V4.1）

`main` 当前维护 `tensile-vlm/v4.1` 的数据、训练、模型资产、推理服务和
TensileAgent 联调链路。V2 已封存为回滚与历史复现对象，不再是当前默认服务。

| 项目 | 当前状态 |
| --- | --- |
| 活跃契约 | `tensile-vlm/v4.1` |
| 当前运行时契约 hash | `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab` |
| 数据基线 | `workspace/data/releases/` 中的不可变 V4.1 发布 |
| 当前发布模型 | `v4.1-agent-pipeline-fold0-r1` |
| 默认模型入口 | `workspace/models/current` |
| 当前服务 | 训练机 `127.0.0.1:8002`，V4.1 loopback-only 中间开发服务 |
| Agent 状态 | 真实媒体服务 smoke、TensileAgent doctor 和 Agent 调用链路均已通过 |
| 最新完整三折 | `v4.1-prompt-concise-cv-v1-seed3411`，已训练、合并和严格评测 |
| 当前结论 | 工程链路已跑通；模型质量门仍失败，不是最终或生产模型 |

当前工作的核心不再是“证明流程能否运行”，而是保留已经跑通的 Agent 链路基准，同时以
受控实验改善输出契约合法率、类别坍缩和断裂相关状态召回。详细模型身份、实验指标和
限制分别放在 `pipeline/model_registry/`、`docs/results/` 和专项报告中。

## 核心思路与总体流程

本项目以“帧窗口证据”为中心，而不是简单增加子视频数量。完整开发闭环如下：

1. 先冻结契约、标签语义和数据根，避免不同版本的 Prompt、标签与媒体串线。
2. 对模型实际采样帧做 source-aware 审计，识别重复视图、来源集中和跨 split 泄漏。
3. 以实际帧画面进行人工审查；自动标签只作提示，人工结论才可成为训练真值。
4. 将开发数据和独立测试数据分别发布为内容寻址、不可覆盖的版本。
5. 先在固定 fold 上进行受控采样和学习曲线实验，只改变一个主要因素并与冻结基线比较。
6. 方案通过后再运行完整三折、最终全量训练和一次独立测试验收，并冻结全部模型身份。
7. 实验模型先进入 `workspace/runs/`；只有人工确认用途和证据后，才晋级到
   `workspace/models/releases/`。
8. 发布模型通过 `workspace/models/current` 接入服务；服务和 Agent 联调通过不等于
   模型质量门或生产验收通过。

同一源视频可以贡献多个窗口，但不能把近重复帧当作独立视觉证据；三折用于选择方案，
最终模型必须使用全部合格开发数据训练，并由从未参与调参的独立测试发布验收。

## V4.1 视觉语义

单个帧窗口输出四个字段：

- `clip_state`：`未断裂`、`临界未断裂`、`发生断裂`、`已断裂`、`无法判断`。
- `fracture_mechanism`：断裂机制；普通未断裂或无法判断时为 `null`。
- `fracture_site`：`inside_gauge`、`outside_gauge_non_root`、`grip_root` 或 `null`。
- `special_case`：特殊情况或 `null`。

`临界未断裂`表示样本尚未断裂，但当前采样帧已有明确的韧性断裂临界征兆。此时机制与
位置只是 prospective 线索，不能单独当作最终断裂结论。标签以当前帧窗口为权威；
同一源视频的重叠片段可以因可见信息不同而拥有不同标签。

权威 artifact：

- `pipeline/contracts/tensile_vlm_v4_1.json`
- `pipeline/v4_1_labels.py`
- `finetune/v4_1_runtime.py`
- `pipeline/prompt_control/active_prompt.yaml`（新固定全字段实验的唯一 Prompt 编辑入口）
- `pipeline/prompt_registry/`（不可变 Prompt revision）

历史 `pipeline/prompt_library.yaml` 继续用于旧 V1/V2 工具，不能作为新 V4.1 固定 Prompt
实验的正文来源。新实验必须把已发布 Prompt 的完整快照写入 experiment contract，并让
训练、严格评测和后续模型 bundle 校验同一个内容 hash。

## 数据入口与版本隔离

活跃 V4.1 数据和运行产物使用项目内、Git 忽略的本地 workspace：

```text
workspace/
├── data/
│   ├── source/
│   ├── derived/
│   └── releases/
├── runs/<experiment-id>/
│   ├── input/
│   ├── adapter/ 或 fold*/adapter/
│   ├── merged/ 或 fold*/merged/
│   ├── evaluation/
│   └── logs/
└── models/
    ├── current -> releases/<model-name>
    ├── releases/
    └── archive/
```

`pipeline.current_data` 固定解析 `<repo>/workspace/data`，不读取
`TENSILE_DATA_HOME`、marker、profile 或 `.compat/workspace`。首次从旧根迁移时执行：

```bash
python pipeline/scripts/migrate_project_local_workspace.py --copy
python pipeline/scripts/migrate_project_local_workspace.py
```

迁移会把旧 `training_releases/` 物理复制为 `releases/`，并逐文件比较数量、字节数和
SHA-256；不会创建软链接，也不会删除旧根。`config/data_roots.json` 与
`manage_versioned_data_roots.py` 仅用于历史 V2/V4.1 外部根复现。

迁移设计、清单与校验结果：

- [V2 封存与 V4.1 数据隔离设计](docs/plans/2026-07-23-v2-v4-1-data-isolation-design.md)
- [V2 / V4.1 数据隔离迁移报告](docs/reports/2026-07-23-v2-v4-1-data-migration.md)
- [数据目录说明](data/README.md)

## V4.1 数据发布

当前 development 发布：

`workspace/data/releases/v4.1.0-ecb5aeb9657c`

该发布包含 1678 个唯一媒体，并被当前 coverage-first Fold0 模型和最新 concise Prompt
三折实验使用。各折记录数：

| Fold | Train | Validation |
| --- | ---: | ---: |
| 0 | 1253 | 425 |
| 1 | 1014 | 664 |
| 2 | 1186 | 492 |

历史基础三折发布：

`workspace/data/releases/v4.1.0-760050fad303`

基础发布统计：

| 项目 | 数量 |
| --- | ---: |
| 物化候选 | 1285 |
| 人工审查 | 774 |
| 自动稳定阴性 | 511 |
| 排除 | 10 |
| 正式发布 | 1275 |
| Fold 0 train / val | 850 / 425 |
| Fold 1 train / val | 830 / 445 |
| Fold 2 train / val | 929 / 346 |

两个发布都是内容寻址、不可覆盖的训练输入。更正数据必须生成新的发布编号，不能直接
修改现有发布目录。跨 release 比较必须提供共同样本分析，不能把全量指标差异直接归因于
Prompt 或训练策略。

## V4.1 数据审查与发布

当前冻结发布是训练与回归基线。新增媒体必须先经过有效视图审计和人工复审，再生成新的
不可变发布；不得修改已有发布，也不得沿用旧视频级标签覆盖帧窗口结论。

```bash
# 审计正式发布、开发候选与独立测试候选的实际采样视图
python -m finetune.audit_v4_1_effective_views \
  --test-materialized <test_materialized_audit.json> \
  --output-dir <effective_view_audit_dir>

# 从已物化媒体构建 V4.1 审查队列
python pipeline/scripts/build_v4_1_review_queue.py \
  --materialized <development_materialized.json> \
  --manifest <candidate_media_manifest.json>

# 有上一轮冻结审查时，先按历史基准生成只读分流制品
python pipeline/scripts/route_v4_1_review_from_history.py \
  --queue <review_queue.json> \
  --previous-decisions <previous_frozen_decisions.json> \
  --current-draft <current_full_queue_draft.json>

# 以帧画面优先的 V4.1 UI 只审 manual_review 候选
streamlit run pipeline/scripts/review_v4_candidates_app.py -- \
  --queue <review_queue.json> \
  --routing-manifest <routing_manifest.json> \
  --reviewer-id <reviewer-id>

# 复核输入并生成不可覆盖的训练发布
python pipeline/scripts/build_v4_1_training_release.py
```

正式路径、当前批次身份、恢复规则和不可绕过的质量门见
[数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)。

## 训练、评测与证据冻结

训练和 GPU 推理只在训练电脑执行。本机用于代码检查、文档整理和已同步结果复核。

正常训练开发顺序是：

1. 校验契约、发布清单、媒体哈希、标签和源视频级 split；
2. 在固定 fold 上完成小规模或消融实验，预注册随机种子、指标与晋级门槛；
3. 通过门槛后运行完整三折并生成统一的分类别、混淆矩阵和按源统计；
4. 固定方案后使用全部开发数据训练最终模型；
5. 在密封测试发布上执行一次验收，不根据测试结果继续调参；
6. 冻结基座、adapter、processor、帧采样、生成参数、量化路径、代码和结果哈希。

当前视觉训练配置位于 `finetune/MiniCPM/config/active/v4_1_visual/`；历史语言层、
消融和 V2 配置分别保存在 `archive/` 与 `experiments/`，不得作为当前活动配置混用。

严格评测汇总 JSON/schema 合法率、四字段准确率、联合准确率、`clip_state` 混淆表和
分类别召回、按源分布及运行失败。训练 loss 或 eval loss 下降只证明训练目标收敛，
不能单独证明任务效果；量化模型也必须作为独立变体验收。

大型权重、媒体和逐样本输出保留在训练机；Git 只保存可追溯的轻量摘要与哈希。冻结
既有运行的入口如下：

```bash
python finetune/archive/freeze_v4_1_evidence.py \
  --run-root finetune/results/v4_1_0_760050fad303_20260724_visual \
  --ablation-root finetune/results/v4_1_0_760050fad303_20260723/fold0_ablation \
  --release-manifest workspace/data/releases/v4.1.0-760050fad303/manifest/release_manifest.json \
  --contract pipeline/contracts/tensile_vlm_v4_1.json \
  --output-dir finetune/results/v4_1_0_760050fad303_20260724_visual/evidence_freeze \
  --model-hash-mode full
```

精确的训练入口、恢复规则、历史运行身份和评测口径见
[微调与评估](finetune/README.md)；当前视觉结果见
[正式视觉证据冻结](docs/results/v4_1_0_760050fad303_20260724_visual/README.md)，有效视图
审计见 [V4.1 有效视图审计](docs/V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT.md)。

## 模型资产与 checkpoint 生命周期

模型名称固定使用：

```text
<协议版本>-<本轮核心要点>-<训练范围>-r<轮次>
```

实验 ID 用来描述实验变量；模型名用来描述保留权重的身份，二者不得混用。所有新训练先写
入 `workspace/runs/<experiment-id>/`，不能再把 `LlamaFactory/saves/` 当作长期模型库。
晋级、替换和回滚通过 Git 管理的 `pipeline/model_registry/` 与训练机发布目录共同完成。

Checkpoint 是实验过程资产，不是发布模型。当前策略：

- 当前发布模型来源实验保留全部 checkpoint；
- 最新 `v4.1-prompt-concise-cv-v1-seed3411` 三折保留全部 checkpoint，供中间能力分析；
- 其他已完成实验已删除 checkpoint，但保留 root adapter、merged、评测、日志和身份文件；
- 新训练在分析完成前不得自动清理 checkpoint。

详见[模型资产生命周期设计](docs/plans/2026-07-29-model-artifact-lifecycle-design.md)与
[Checkpoint 清理报告](docs/reports/2026-07-29-checkpoint-retention-plan.md)。

## 当前推理服务边界

当前默认推理入口是中间开发模型 `v4.1-agent-pipeline-fold0-r1`，运行时使用
`tensile-vlm/v4.1` 契约和 `workspace/models/current/merged`。训练机服务只监听
`127.0.0.1:8002`，TensileAgent 通过受控本机访问或 SSH tunnel 调用。

该模型完成了训练、合并、部署和 Agent 链路验证，但仍有明确限制：

- 仅 Fold0；
- 不是最新三折最优模型；
- 不是 full-data final；
- 历史模型质量门未通过；
- 未获得 production approval。

V2 保留为历史回滚对象。启动、预检、真实视频 smoke 和停止方式见
[推理服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md)。

## 环境

推荐 Python 3.11、Conda 和 Linux/GPU 环境：

```bash
git submodule update --init --recursive
conda create -n mVllm2 python=3.11 pip -y
conda activate mVllm2
pip install -r requirements.txt
pip install -e ./LlamaFactory
```

子视频处理需要 `ffmpeg` / `ffprobe`。MiniCPM-V-4.5 基座模型放在 `models/`，或通过
具体运行配置指定。

## 项目结构

```text
pipeline/      数据处理、V4.1 契约、模型注册表与推理服务
finetune/      三折训练、模型合并、严格评测
workspace/     训练机本地数据、实验运行和模型资产（Git 忽略）
data/          旧外部数据根的兼容入口
config/        数据根配置
docs/          运行手册、设计和迁移报告
tests/         数据、契约和评测测试
LlamaFactory/  LLaMA-Factory 子模块
models/        本地模型目录
```

## 相关文档

- [当前项目状态与开发原则](docs/CURRENT_PROJECT_STATUS.md)
- [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)
- [微调与评估](finetune/README.md)
- [推理服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md)
- [当前模型部署证据](docs/results/v4_1_agent_pipeline_fold0_r1/README.md)
- [最新三折结果](docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md)
- [模型资产生命周期设计](docs/plans/2026-07-29-model-artifact-lifecycle-design.md)
- [V4.1 临界未断裂契约设计](docs/plans/2026-07-23-tensile-vlm-v4-1-incipient-fracture-design.md)
- [Agent 工作说明](AGENTS.md)

V2/V3 Prompt、旧审核和旧数据流水线文档只用于历史追溯。新工作应从本 README、
V4.1 契约、当前数据运行手册和冻结发布清单开始。
