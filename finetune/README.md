# V4.1 微调、合并与评测

本目录维护 MiniCPM-V-4.5 的 V4.1 三折 LoRA 微调、模型合并和严格验证集推理。
训练、模型合并和 GPU 推理必须在训练电脑执行；本机只复核代码和已同步的轻量结果。

可读版本体系的三折训练使用统一 `train prepare / validate / run / export` 入口，见 [versioning 训练操作说明](../versioning/SCRIPTS.md#三折训练准备与执行)。正式验证集测评使用 `eval prepare / validate / run / export`，见 [versioning 测评操作说明](../versioning/SCRIPTS.md#正式验证集测评)。下文既有实验命令与结果保留其 legacy 身份语义。

## 当前身份

| 项目 | 值 |
| --- | --- |
| 契约 | `tensile-vlm/v4.1` |
| 当前运行时契约 hash | `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab` |
| 当前 development 发布 | `v4.1.0-ecb5aeb9657c` |
| 当前发布路径 | `workspace/data/releases/v4.1.0-ecb5aeb9657c` |
| 当前发布样本 | 1678 |
| 上一轮三折基础发布 | `v4.1.0-760050fad303`，1275 条 |
| 当前发布模型 | `v4.1-agent-pipeline-fold0-r1`，coverage-first seed3407 Fold0 |
| 最新三折实验 | `v4.1-prompt-concise-cv-v1-seed3411`，三折均已完成 |
| 正式视觉运行 | `v4_1_0_760050fad303_20260724_visual`，已完成 |
| BF16 / 两种 4-bit 验证 | 均已完成，1216 条，运行失败 0 |
| 当前结论 | Agent 工程链路已通过；最新三折出现契约退化和类别坍缩，质量门仍失败 |

`finetune/active_data_release.json` 路径沿用自 V2，但旧内容已删除，现为当前 V4.1
活跃指针，指向 `workspace/data/releases/v4.1.0-ecb5aeb9657c`。release 后必须手动回填
`expected_contract_hash` 与 `expected_manifest_sha256`（值取自对应
`release_summary.json` 的 `contract_hash` / `release_manifest_sha256` 字段），否则默认
校验会 fail-closed。V4.1 不再使用旧 `finetune/dataset_info.json` 或 V2 Prompt 作为活动指针；三个训练配置直接绑定冻结发布中的
`dataset_info.json`，避免 V2/V4.1 串线。

## 固定全字段 Prompt 受控实验

新 Prompt 研发链路只允许编辑：

`pipeline/prompt_control/active_prompt.yaml`

校验并发布不可变 revision：

```bash
python -m pipeline.prompt_control validate \
  --source pipeline/prompt_control/active_prompt.yaml

python -m pipeline.prompt_control publish \
  --source pipeline/prompt_control/active_prompt.yaml
```

初版 revision 为 `v4.1-fixed-full-fields-initial-v1`。registry 中的 `prompt.yaml` 与
`manifest.json` 不可覆盖；同 revision 内容变化会直接失败。

在训练机上从冻结的 coverage-first sampling 生成语义实验输入：

```bash
python finetune/train_build_dataset.py
```

该命令校验 source sampling 的全部受管文件，只保留 seed3411 的视频多重集、顺序和四字段
assistant 标签，并把完整 Prompt snapshot 写入同一实验的 `input/`。随后生成 Git 管理的
语义配置：

```bash
python finetune/train_prepare_run.py
```

实验 ID 是 `v4.1-prompt-minimal-v1-seed3411`。Git 配置位于同名
`finetune/experiments/` 目录，运行输入和输出位于同名 `workspace/runs/` 目录。LoRA
超参数、seed、epoch 和 optimizer steps 保持不变；详细身份 hash 只保存在
`manifest.json`，不编码到目录名。

严格评测必须显式使用同一个 experiment contract：

```bash
python -m finetune.eval_run \
  --fold 0 \
  --release-id v4.1.0-ecb5aeb9657c \
  --model-dir /path/to/seed3411_merged \
  --out-dir finetune/results/<run>/seed3411/fold0 \
  --experiment-contract /path/to/fixed_prompt_bundle/experiment_contract.json
```

`--analysis-prompt-overlay` 仅保留给历史实验复现，不能用于新的固定 Prompt 实验。当前
V4.1 中间服务和 TensileAgent 链路已经跑通，但固定 Prompt 实验仍必须使用 fail-closed
的 Prompt/schema 身份校验；链路通过不授予 production approval。

## 当前模型与实验资产

训练产物不再长期散落在 `LlamaFactory/saves/`。统一规则如下：

```text
workspace/
├── runs/<experiment-id>/             实验输入、checkpoint、adapter、merged、评测
└── models/
    ├── current                       当前发布指针
    ├── releases/<model-name>/        人工确认的发布模型
    └── archive/                      历史模型
```

当前发布模型：

```text
workspace/models/releases/v4.1-agent-pipeline-fold0-r1/
├── adapter/
├── merged/
└── release-manifest.json
```

`workspace/models/current` 指向该目录。模型部署必须通过
`pipeline/model_registry/current.json` 解析身份，不能从实验文件名猜测模型。

最新三折实验位于：

```text
workspace/runs/v4.1-prompt-concise-cv-v1-seed3411/
├── fold0/
├── fold1/
└── fold2/
```

这组三折的训练、最佳 checkpoint 回载、合并和严格评测已完成，但结果没有晋级为发布
模型：加权 contract 合法率为 79.63%，joint correct 为 32.07%，并出现明显“未断裂”
类别坍缩。完整结论见
[Concise Prompt 三折报告](../docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md)。

Checkpoint 保留以“训练任务是否已完成分析”为边界：

- 当前发布来源实验的 5 个 checkpoint 全部保留；
- 最新 concise 三折的 15 个 checkpoint 全部保留；
- 其他已完成实验仅保留 root adapter、merged 和结果证据。

新训练不得在任务级分析完成前自动删除 checkpoint。管理入口：

```bash
python scripts/serve_manage_checkpoints.py plan
```

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

## 正式视觉 LoRA 结果

正式视觉运行启用视觉塔 LoRA，并完整训练和保存 `resampler`。为适配 24GB GPU，
训练使用 4-bit bnb 基座、`adamw_torch`、batch size 1 和梯度累积 8；跨实验主评估
仍统一使用 merged BF16。

| 推理路线 | 首轮严格合法率 | 联合准确率 | 状态准确率 | 机制准确率 | 位置准确率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| merged BF16 | 97.12% | 40.21% | 49.67% | 50.66% | 56.66% |
| merged 后重新 4-bit | 98.19% | 34.87% | 47.53% | 48.68% | 51.23% |
| 4-bit 基座直挂 adapter | 100.00% | 37.42% | 47.37% | 49.92% | 53.45% |

BF16 的断裂相关三状态宏平均召回率为 24.54%，`已断裂`召回率为 9.00%。
35 条严格非法输出全部漏掉必填 `special_case` 字段；没有运行异常或 token 截断。
解析器不得自动补字段。

验证目标中没有 `无法判断` 或非空 `special_case`，因此当前运行不能证明这些能力。
完整逐折指标、非法输出和模型/结果哈希见
[证据冻结报告](../docs/results/v4_1_0_760050fad303_20260724_visual/README.md)。

若以后部署必须使用 4-bit，应优先评估“4-bit 基座 + 原始 adapter + BF16
resampler”；该路线是独立模型变体，不能继承 BF16 验收结论。

## 证据冻结

训练机的大型权重和逐样本 JSONL 不进入 Git。使用以下命令为发布、契约、结果、基座、
三个 adapter、三个 merged 模型和 processor/config 生成完整 SHA-256 索引：

```bash
# 已删除，可从 git 历史查看
python finetune/archive/freeze_v4_1_evidence.py \
  --run-root finetune/results/v4_1_0_760050fad303_20260724_visual \
  --ablation-root finetune/results/v4_1_0_760050fad303_20260723/fold0_ablation \
  --release-manifest workspace/data/releases/v4.1.0-760050fad303/manifest/release_manifest.json \
  --contract pipeline/contracts/tensile_vlm_v4_1.json \
  --output-dir finetune/results/v4_1_0_760050fad303_20260724_visual/evidence_freeze \
  --model-hash-mode full
```

正式冻结必须使用 `--model-hash-mode full`。`metadata` 只用于单元测试，不能作为权重
身份。

## 上一轮语言层 LoRA 基线复现

以下入口对应 `20260723` 语言层 LoRA 基线。当前正式视觉运行不得覆盖它。

从仓库根目录执行：

```bash
python finetune/archive/run_v4_1_three_fold_training.py --validate-only
python finetune/archive/run_v4_1_three_fold_training.py
```

预检会验证：

- 数据根 marker 与 `tensile-vlm/v4.1` 一致；
- 发布 manifest、契约版本和契约 hash 一致；
- 1275 个媒体路径及其哈希可用；
- 所有标签满足 V4.1 字段和联动约束；
- 每个 fold 的 train/validation 按源视频隔离；
- YAML 绑定正确，且不会覆盖已有训练目录。

对应配置：

- `MiniCPM/config/archive/v4_1_language/train_v4_1_fold0.yaml`
- `MiniCPM/config/archive/v4_1_language/train_v4_1_fold1.yaml`
- `MiniCPM/config/archive/v4_1_language/train_v4_1_fold2.yaml`

状态文件：

`run_logs/three_fold_training_v4_1_0_760050fad303_20260723.json`

迁移后的三个受管输出目录分别为：

- `LlamaFactory/saves/minicpmv4_5/lora/archive/v4_1_language/sft_tensile_v4_1_0_760050fad303_20260723_fold0`
- `LlamaFactory/saves/minicpmv4_5/lora/archive/v4_1_language/sft_tensile_v4_1_0_760050fad303_20260723_fold1`
- `LlamaFactory/saves/minicpmv4_5/lora/archive/v4_1_language/sft_tensile_v4_1_0_760050fad303_20260723_fold2`

以上旧路径现在是兼容链接；权威物理路径位于：

- `workspace/runs/archive/v4.1-language-cv-v1-seed3407/fold0`
- `workspace/runs/archive/v4.1-language-cv-v1-seed3407/fold1`
- `workspace/runs/archive/v4.1-language-cv-v1-seed3407/fold2`

流水线拒绝覆盖不完整或身份不一致的输出目录。不要通过删除状态文件绕过产物检查。

## 上一轮语言层 LoRA 合并与严格验证集推理

训练完成后运行：

```bash
python finetune/archive/run_v4_1_post_training.py --validate-only
python finetune/archive/run_v4_1_post_training.py
```

流水线先合并三个 LoRA，再分别使用对应 fold 的 validation 数据进行严格 V4.1 推理。
合并配置：

- `MiniCPM/config/archive/v4_1_language/merge_v4_1_fold0.yaml`
- `MiniCPM/config/archive/v4_1_language/merge_v4_1_fold1.yaml`
- `MiniCPM/config/archive/v4_1_language/merge_v4_1_fold2.yaml`

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
python -m finetune.eval_run \
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

## 当前部署与质量边界

当前训练机已使用 `v4.1-agent-pipeline-fold0-r1` 启动 V4.1 中间服务，并通过真实媒体
service smoke、TensileAgent doctor 和 Agent 调用。它解决的是“整个链路能否运行”的
问题，不代表模型质量已经达标。

下一轮优化仍需：

1. 用保留的 checkpoint 分析类别坍缩和契约合法率随 step 的变化；
2. 通过交叉 Prompt/采样对照隔离退化来源；
3. 提升 `临界未断裂`、`发生断裂`、`已断裂` 的召回与四字段合法率；
4. 通过完整三折门槛后再决定 full-data 训练；
5. 独立测试只能在方案冻结后执行，不能用于继续调参；
6. 新模型只有在证据优于当前发布模型时才能晋级并替换 `current`。

当前模型仍是 Fold0 中间开发模型，不得宣称为 final、full-data、
independent-test-passed 或 production-approved。

## 可读版本控制新体系的训练与测评记录

`refactor/readable-version-control` 分支提供独立的 `python -m versioning` 入口，用于在
MLflow 本地 store 中记录可读训练与测评身份；它尚未替换本文件前述 legacy 训练命令，也不在
Mac 上执行真实 GPU 训练或推理。

- `train create train-v...` 先校验封存 data release 和已冻结 Prompt，再创建训练父 Run；
  `fold-start` / `fold-end` 管理 fold0–fold2 子 Run，`summary` 写三折汇总，全部完成后才能
  `complete`。
- `eval create eval-v...` 创建独立测评父 Run；single-fold、cross-validation、full 三种
  scope 分别执行各自的 fold/汇总完整性门。holdout 额外要求把预注册原子冻结到 eval
  staging 稳定路径，并以完整内容摘要绑定全局一次性 claim；完成测评时消费该 claim，只有
  同一身份、executor 与摘要可以恢复。
- `model register model-v...` 在关联 train 完整后先登记 staging Model Version；`eval create`
  必须精确引用它的可读身份与 MLflow 数值版本，eval passed 后再执行 `model finalize
  model-v... --eval-version eval-v...` 单向绑定结论。candidate/production alias 均拒绝未
  finalize 的模型；备份范围、批准和物化也只通过显式子命令推进，不存在隐式最新模型。
- model 登记还要显式声明 `source_scope`、artifacts 清单和唯一 `deploy_target`；三折模型组的
  `deploy_target` 必须为空，不能进入 candidate/production。`model manifest` 先从 Registry
  单向导出严格 manifest；随后 `model current --alias ... --service-mode ...` 才能在完整下载、
  manifest 与精确数值版本校验后原子切换 `workspace/models/current`。生产模式只接受
  production alias，缺参、断链或内容不一致均拒绝启动。
- `eval manifest` 从封存 data、正式 Prompt、已完成 train 和 eval 结论单向导出轻量证据，
  并要求模型已绑定当前 eval、`source_train` 与模型登记的 train 完全一致；
  不反向修改 MLflow。`backup create/verify/restore` 只处理显式路径，并拒绝覆盖恢复目标。
- 离线备份的 `adapter` 范围只复制身份资料和声明 adapter，不夹带 merged；只有
  `production_bundle` 才复制声明的 adapter 与 merged，正式评测证据随 MLflow store 保存。

参数清单运行 `python -m versioning <领域> --help` 查看。模块与命令索引见
[`versioning/SCRIPTS.md`](../versioning/SCRIPTS.md)，架构边界见
[`ARCHITECTURE.md`](../ARCHITECTURE.md)。

## V2 历史复现

下列入口仅用于封存版本复现，不是 `main` 的当前训练说明：

- Git：`tensile-vlm-v2-final` 或 `archive/v2`
- 数据：`data/archive/training_releases/v2.0.0-1dab1e5e`
- 旧配置：`MiniCPM/config/archive/v2/`
- 旧评测：`finetune.validation.run_evaluation`

进行 V2 复现时应切换到封存 Git 引用并使用 frozen 数据根，不要在 V4.1 主分支上混用
旧活动指针。

## 关联文档

- [仓库总览](../README.md)
- [数据处理与训练运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)
- [当前推理服务运行手册](../docs/INFERENCE_SERVICE_RUNBOOK.md)
- 历史数据隔离、模型资产生命周期与 checkpoint 清理文档已在提交 `d964eeb5` 归档；需要时从 Git 历史查阅。
