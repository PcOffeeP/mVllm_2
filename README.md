# mVllm_2

基于 MiniCPM-V-4.5 的材料拉伸视频数据、微调、评测与视觉服务仓库。

## 当前状态（V4.1）

`main` 当前只继续维护 `tensile-vlm/v4.1` 数据与训练链路。V2 已通过
`tensile-vlm-v2-final` / `archive/v2` 封存，只用于历史复现。

| 项目 | 当前状态 |
| --- | --- |
| 活跃契约 | `tensile-vlm/v4.1` |
| 契约 hash | `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937` |
| 活跃数据根 | `tensile-data/current` |
| 冻结 V2 数据根 | `tensile-data/archive` |
| V4.1 训练发布 | `v4.1.0-760050fad303`，1275 个样本 |
| 三折 LoRA 训练 | 已完成 |
| 正式视觉 LoRA 三折、BF16 合并与验证 | 已完成，1216 条，运行失败 0 |
| 4-bit 一致性评估 | 两条路线均已完成；adapter-direct 作为后续独立部署候选 |
| 当前模型结论 | 视觉方向有效，但断裂状态召回和契约合法率未达到生产门槛 |
| 当前生产推理服务 | 仍为 `tensile-vlm/v2`，尚未切换到 V4.1 |
| TensileAgent 运行时 | 仍为 V2，V4.1 只完成目标契约冻结 |

当前正式视觉 BF16 的 `clip_state` 准确率为 49.67%，断裂相关三状态宏平均召回率为
24.54%，`已断裂`召回率仅 9.00%；35 条输出因漏掉必填 `special_case` 字段而严格
非法。V4.1 数据或模型产物存在，不等于生产服务和 Agent 已经迁移。下一轮必须先扩充
经过人工审查的独立视觉证据并完成受控 fold0 实验，再决定是否进入完整三折、最终全量
训练和部署。

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

当前批次已经完成审查和发布；以下命令用于复核或复现当前流程，不应覆盖冻结产物：

```bash
# 构建 observed + incipient 审查队列
python pipeline/scripts/build_v4_1_review_queue.py \
  --materialized <development_materialized.json> \
  --manifest <candidate_media_manifest.json>

# 以帧画面优先的 V4.1 UI 进行人工审查
streamlit run pipeline/scripts/review_v4_candidates_app.py -- \
  --queue <review_queue.json> \
  --manifest <candidate_media_manifest.json> \
  --reviewer-id <reviewer-id>

# 复核输入并生成不可覆盖的训练发布
python pipeline/scripts/build_v4_1_training_release.py
```

正式路径、当前批次身份、恢复规则和不可绕过的质量门见
[数据处理与训练运行手册](docs/DATA_PROCESSING_RUNBOOK.md)。

## V4.1 三折训练、合并与评测

训练和 GPU 推理只在训练电脑执行。本机用于代码检查、文档整理和已同步结果复核。

当前正式视觉运行：

- 运行 ID：`v4_1_0_760050fad303_20260724_visual`
- 训练：4-bit bnb 基座、视觉塔 LoRA、完整训练并保存 `resampler`
- 主评估：三个 merged BF16 模型
- 量化评估：merged 后重新 4-bit，以及 4-bit 基座直挂原始 adapter
- 轻量证据：[正式视觉运行证据冻结](docs/results/v4_1_0_760050fad303_20260724_visual/README.md)

以下命令是上一轮语言层 LoRA 基线的复现入口，不是当前正式视觉运行的重跑命令：

```bash
# 逐文件验证发布、媒体、标签、划分和输出目录
python finetune/run_v4_1_three_fold_training.py --validate-only

# 依次训练三个 fold
python finetune/run_v4_1_three_fold_training.py

# 训练完成后检查合并与评测前置条件
python finetune/run_v4_1_post_training.py --validate-only

# 合并三个 LoRA，并对各自 validation fold 做可恢复的严格推理
python finetune/run_v4_1_post_training.py
```

训练配置：

- `finetune/MiniCPM/config/train_v4_1_fold0.yaml`
- `finetune/MiniCPM/config/train_v4_1_fold1.yaml`
- `finetune/MiniCPM/config/train_v4_1_fold2.yaml`

合并配置：

- `finetune/MiniCPM/config/merge_v4_1_fold0.yaml`
- `finetune/MiniCPM/config/merge_v4_1_fold1.yaml`
- `finetune/MiniCPM/config/merge_v4_1_fold2.yaml`

严格评测汇总 JSON/schema 合法率、四字段准确率、联合准确率、`clip_state` 混淆表和
运行失败。训练 loss 或 eval loss 下降只证明训练目标收敛，不能单独证明任务效果。
完整说明见 [微调与评估](finetune/README.md)。

冻结现有正式视觉运行的轻量证据：

```bash
python finetune/freeze_v4_1_evidence.py \
  --run-root finetune/results/v4_1_0_760050fad303_20260724_visual \
  --ablation-root finetune/results/v4_1_0_760050fad303_20260723/fold0_ablation \
  --release-manifest data/current/training_releases/v4.1.0-760050fad303/manifest/release_manifest.json \
  --contract pipeline/contracts/tensile_vlm_v4_1.json \
  --output-dir finetune/results/v4_1_0_760050fad303_20260724_visual/evidence_freeze \
  --model-hash-mode full
```

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
