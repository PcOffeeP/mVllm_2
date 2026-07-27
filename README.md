# mVllm_2

基于 MiniCPM-V-4.5 的材料拉伸视频数据、微调、评测与视觉服务仓库。

## 当前状态（V4.1）

`main` 当前只继续维护 `tensile-vlm/v4.1` 数据与训练链路。V2 已通过
`tensile-vlm-v2-final` / `archive/v2` 封存，只用于历史复现。

| 项目 | 当前状态 |
| --- | --- |
| 活跃契约 | `tensile-vlm/v4.1` |
| 当前运行时契约 hash | `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab` |
| 数据基线 | `tensile-data/current` 中的不可变发布 `v4.1.0-760050fad303` |
| 模型研发 | 已完成视觉 LoRA、BF16 和 4-bit 路线验证，确认视觉适配方向有效 |
| 数据改进 | 已建立有效视图审计、开发候选与独立测试候选隔离流程 |
| 当前结论 | 模型尚未通过生产效果验收，继续补充独立视觉证据并做受控实验 |
| 生产边界 | 推理服务和 TensileAgent 继续使用 `tensile-vlm/v2` |

V4.1 当前是可继续迭代的研发链路，不是可直接替换 V2 的生产模型。详细实验指标、逐折
结果和阶段性候选统计放在 `docs/results/` 与专项文档中；README 只维护总体状态、稳定
身份和实际开发流程。

## 核心思路与总体流程

本项目以“帧窗口证据”为中心，而不是简单增加子视频数量。完整开发闭环如下：

1. 先冻结契约、标签语义和数据根，避免不同版本的 Prompt、标签与媒体串线。
2. 对模型实际采样帧做 source-aware 审计，识别重复视图、来源集中和跨 split 泄漏。
3. 以实际帧画面进行人工审查；自动标签只作提示，人工结论才可成为训练真值。
4. 将开发数据和独立测试数据分别发布为内容寻址、不可覆盖的版本。
5. 先在固定 fold 上进行受控采样和学习曲线实验，只改变一个主要因素并与冻结基线比较。
6. 方案通过后再运行完整三折、最终全量训练和一次独立测试验收，并冻结全部模型身份。
7. 模型验收通过后，才同步升级推理服务与 TensileAgent，并完成联调和回滚验证。

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

## 数据入口与版本隔离

仓库中的 `data/` 不保存实际大型数据，只提供语义入口：

```text
data/
├── current -> ../../tensile-data/current
├── archive -> ../../tensile-data/archive
└── README.md

tensile-data/current/
├── source/
│   ├── videos/
│   ├── annotations/
│   └── splits/
├── derived/
│   ├── roi_videos/
│   ├── subvideos/
│   ├── frames/
│   └── metadata/
├── training_releases/
└── .compat/workspace/
```

默认外部根目录为仓库同级的 `tensile-data`，可用 `TENSILE_DATA_HOME` 覆盖。
`config/data_roots.json` 是契约、生命周期和目录之间的唯一映射。

初始化或检查数据入口：

```bash
python pipeline/scripts/manage_versioned_data_roots.py init --contract all
python pipeline/scripts/manage_versioned_data_roots.py check --contract all
python pipeline/scripts/manage_versioned_data_roots.py workspace \
  --contract tensile-vlm/v4.1
```

每个根目录必须带 `.tensile-data-root.json`。程序会拒绝把 V2 根用于 V4.1，也会拒绝
向 frozen 的 V2 根写入新数据。`.compat/workspace` 只链接到同一版本的数据，用于兼容
已冻结产物中的 `data/...` 相对路径。

迁移设计、清单与校验结果：

- [V2 封存与 V4.1 数据隔离设计](docs/plans/2026-07-23-v2-v4-1-data-isolation-design.md)
- [V2 / V4.1 数据隔离迁移报告](docs/reports/2026-07-23-v2-v4-1-data-migration.md)
- [数据目录说明](data/README.md)

## 已冻结的 V4.1 训练发布

发布目录：

`data/current/training_releases/v4.1.0-760050fad303`

发布清单：

`data/current/training_releases/v4.1.0-760050fad303/manifest/release_manifest.json`

已确认的统计：

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

该发布是内容寻址、不可覆盖的训练输入。更正数据必须生成新的发布编号，不能直接修改
现有发布目录。

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
python finetune/freeze_v4_1_evidence.py \
  --run-root finetune/results/v4_1_0_760050fad303_20260724_visual \
  --ablation-root finetune/results/v4_1_0_760050fad303_20260723/fold0_ablation \
  --release-manifest data/current/training_releases/v4.1.0-760050fad303/manifest/release_manifest.json \
  --contract pipeline/contracts/tensile_vlm_v4_1.json \
  --output-dir finetune/results/v4_1_0_760050fad303_20260724_visual/evidence_freeze \
  --model-hash-mode full
```

精确的训练入口、恢复规则、历史运行身份和评测口径见
[微调与评估](finetune/README.md)；当前视觉结果见
[正式视觉证据冻结](docs/results/v4_1_0_760050fad303_20260724_visual/README.md)，有效视图
审计见 [V4.1 有效视图审计](docs/V4_1_PHASE1_EFFECTIVE_VIEW_AUDIT.md)。

## 生产推理服务边界

当前生产服务仍固定使用 `pipeline/contracts/tensile_vlm_v2.json`。现有部署和
TensileAgent 接入应继续遵循
[V2 推理服务运行手册](docs/INFERENCE_SERVICE_RUNBOOK.md)，不得把 V4.1 训练模型直接放入
V2 服务或伪造 V2 deployment manifest。

V4.1 上线需要单独完成：

1. 选定通过任务效果验收的 V4.1 模型；
2. 发布与 V4.1 artifact 一致的服务端 schema、Prompt 和 manifest；
3. 同步升级 TensileAgent schema、搜索语义、Stub、Verifier、Web 展示和端到端测试；
4. 完成真实视频联调与回滚验证后再切换生产地址。

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
pipeline/      数据处理、V4.1 标签/契约、生产服务
finetune/      三折训练、模型合并、严格评测
data/          current/archive 语义入口
config/        数据根配置
docs/          运行手册、设计和迁移报告
tests/         数据、契约和评测测试
LlamaFactory/  LLaMA-Factory 子模块
models/        本地模型目录
```

## 相关文档

- [数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)
- [微调与评估](finetune/README.md)
- [V4.1 临界未断裂契约设计](docs/plans/2026-07-23-tensile-vlm-v4-1-incipient-fracture-design.md)
- [Agent 工作说明](AGENTS.md)

V2/V3 Prompt、旧审核和旧数据流水线文档只用于历史追溯。新工作应从本 README、
V4.1 契约、当前数据运行手册和冻结发布清单开始。
