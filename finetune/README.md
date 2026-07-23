# V4.1 微调、合并与评测

本目录维护 MiniCPM-V-4.5 的 V4.1 三折 LoRA 微调、模型合并和严格验证集推理。
训练、模型合并和 GPU 推理必须在训练电脑执行；本机只复核代码和已同步的轻量结果。

## 当前身份

| 项目 | 值 |
| --- | --- |
| 契约 | `tensile-vlm/v4.1` |
| 契约 hash | `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937` |
| 数据发布 | `v4.1.0-760050fad303` |
| 发布路径 | `data/current/training_releases/v4.1.0-760050fad303` |
| 发布样本 | 1275 |
| 三折训练 | 已完成 |
| 三折合并与验证推理 | 正在执行；是否完成以状态文件和各 fold 汇总为准 |

V4.1 不使用旧 `finetune/active_data_release.json`、旧
`finetune/dataset_info.json` 或 V2 Prompt 作为活动指针。三个训练配置直接绑定冻结发布
中的 `dataset_info.json`，避免 V2/V4.1 串线。

## 环境

```bash
cd LlamaFactory
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

运行时需要：

```bash
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
export PYTHONPATH="$PWD/LlamaFactory/src:$PWD"
```

## 三折训练

从仓库根目录执行：

```bash
python finetune/run_v4_1_three_fold_training.py --validate-only
python finetune/run_v4_1_three_fold_training.py
```

预检会验证：

- 数据根 marker 与 `tensile-vlm/v4.1` 一致；
- 发布 manifest、契约版本和契约 hash 一致；
- 1275 个媒体路径及其哈希可用；
- 所有标签满足 V4.1 字段和联动约束；
- 每个 fold 的 train/validation 按源视频隔离；
- YAML 绑定正确，且不会覆盖已有训练目录。

对应配置：

- `MiniCPM/config/train_v4_1_fold0.yaml`
- `MiniCPM/config/train_v4_1_fold1.yaml`
- `MiniCPM/config/train_v4_1_fold2.yaml`

状态文件：

`run_logs/three_fold_training_v4_1_0_760050fad303_20260723.json`

三个输出目录分别为：

- `LlamaFactory/saves/minicpmv4_5/lora/sft_tensile_v4_1_0_760050fad303_20260723_fold0`
- `LlamaFactory/saves/minicpmv4_5/lora/sft_tensile_v4_1_0_760050fad303_20260723_fold1`
- `LlamaFactory/saves/minicpmv4_5/lora/sft_tensile_v4_1_0_760050fad303_20260723_fold2`

流水线拒绝覆盖不完整或身份不一致的输出目录。不要通过删除状态文件绕过产物检查。

## 合并 LoRA 与严格验证集推理

训练完成后运行：

```bash
python finetune/run_v4_1_post_training.py --validate-only
python finetune/run_v4_1_post_training.py
```

流水线先合并三个 LoRA，再分别使用对应 fold 的 validation 数据进行严格 V4.1 推理。
合并配置：

- `MiniCPM/config/merge_v4_1_fold0.yaml`
- `MiniCPM/config/merge_v4_1_fold1.yaml`
- `MiniCPM/config/merge_v4_1_fold2.yaml`

总状态文件：

`run_logs/post_training_v4_1_0_760050fad303_20260723.json`

结果目录：

```text
results/v4_1_0_760050fad303_20260723/three_fold_validation/
├── fold0/
├── fold1/
└── fold2/
```

每个 fold 完成后必须包含：

- `run_identity.json`
- `evaluation_records.jsonl`
- `evaluation_summary.json`
- `runtime_failures.csv`

逐样本结果会实时追加到 JSONL。进程中断后可以用同一模型、数据和输出目录续跑；
若 run identity 漂移，脚本会拒绝复用目录。

单独运行某个 fold：

```bash
python -m finetune.run_v4_1_evaluation \
  --fold 0 \
  --model-dir /path/to/fold0_merged \
  --out-dir finetune/results/<run>/fold0
```

`--max-samples` 只用于冒烟检查，不能把受限样本的结果作为完整 validation 验收。

## 评测口径

严格评测至少检查：

- 运行失败数与严格 JSON/schema 合法率；
- `clip_state`、`fracture_mechanism`、`fracture_site`、`special_case` 字段准确率；
- 四字段联合准确率；
- `clip_state` 混淆表和类别分布；
- `临界未断裂` 是否被错误当成已发生断裂；
- `inside_gauge`、`outside_gauge_non_root`、`grip_root` 的混淆；
- 典型成功、失败和非法输出样例。

训练 loss 和 eval loss 下降只能证明训练目标收敛。没有逐样本预测和任务指标时，不得
声称模型已经达到可部署效果。

## 生产切换边界

当前生产推理服务与 TensileAgent 仍运行 `tensile-vlm/v2`。完成 V4.1 三折评测后仍需：

1. 根据任务指标选择 fold 模型，或按已批准方案准备全量训练；
2. 冻结最终 V4.1 模型、processor、generation 与部署 manifest；
3. 使服务端只接受 V4.1 artifact 中的 Prompt 和 schema；
4. 同步升级 TensileAgent 的 HTTP 契约、搜索方向、证据聚合、Stub、Web 与测试；
5. 完成真实视频联调和回滚验证。

不得把 V4.1 模型装入 V2 服务并继续宣称 `contract_version=tensile-vlm/v2`。

## V2 历史复现

下列入口仅用于封存版本复现，不是 `main` 的当前训练说明：

- Git：`tensile-vlm-v2-final` 或 `archive/v2`
- 数据：`data/archive/training_releases/v2.0.0-1dab1e5e`
- 旧配置：`train_fold*.yaml`、`merge_fold*.yaml`、`train_full.yaml`、
  `merge_full.yaml`
- 旧评测：`finetune.validation.run_evaluation`

进行 V2 复现时应切换到封存 Git 引用并使用 frozen 数据根，不要在 V4.1 主分支上混用
旧活动指针。

## 关联文档

- [仓库总览](../README.md)
- [数据处理与训练运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)
- [数据隔离设计](../docs/plans/2026-07-23-v2-v4-1-data-isolation-design.md)
- [迁移报告](../docs/reports/2026-07-23-v2-v4-1-data-migration.md)
- [V2 生产推理服务运行手册](../docs/INFERENCE_SERVICE_RUNBOOK.md)
