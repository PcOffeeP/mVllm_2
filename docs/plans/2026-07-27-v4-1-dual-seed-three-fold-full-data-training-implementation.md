# V4.1 双随机种子、三折验证与全量训练实施手册

> 编写日期：2026-07-27
> 文档状态：已批准的实施依据
> 上位设计：
> [V4.1 双随机种子、三折验证与全量训练实施设计](2026-07-27-v4-1-dual-seed-three-fold-full-data-training-design.md)
> 当前执行状态：只批准按本文准备代码、测试、配置、manifest 和 dry-run；本次文档提交不启动训练
> 适用仓库：`mVllm_2`

## 1. Agent 首读结论

执行 Agent 必须遵守以下顺序，禁止跳步：

```text
实现与测试
  → 只读验证现有 fold0/seed3407
  → 准备并冻结所有预注册身份
  → 等待启动训练的明确指令
  → fold0/seed3411
  → 双 seed 稳定性比较
  → 稳定性通过
  → fold1、fold2
  → 三折完整性与聚合
  → full-development
  → merged BF16
  → 新端口链路验证
  → 原子切换推理入口
```

以下行为禁止：

- 重训现有 coverage-first fold0/seed3407；
- 用历史绝对性能参考值阻断训练；
- 在双 seed 稳定性失败后自动调参或继续三折；
- 读取 sealed-test 标签或逐样本受限语义；
- 将 fold0、fold1、fold2 adapter 或 merged model 互相合并；
- 在 full-development 服务通过链路验证前停止当前 seed3407 服务；
- 将模型称为生产通过、独立测试通过或质量 final；
- 高频轮询长训练、长评测或全视频批处理。

## 2. 机器、路径与运行环境

### 本机

```text
仓库：/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2
分支：main
```

本机负责：

- 代码、测试、配置、schema 和轻量文档；
- Git 提交与同步；
- 轻量离线单元测试；
- 最终通过 SSH tunnel 的客户端链路验证。

### 训练机

```text
SSH：liuyang@100.70.83.68
仓库：/home/liuyang/文档/mVllm_2
Python：/home/liuyang/miniconda3/envs/agent/bin/python
模型服务：训练机 loopback 127.0.0.1:8002
```

训练机负责：

- 媒体、数据和模型权重的只读/受管存储；
- GPU 训练、merge 和严格评测；
- merged BF16 loopback 推理服务；
- 大型结果、checkpoint、adapter 和受限逐样本记录。

任何命令执行前先验证：

```bash
git status --short --branch
git rev-parse HEAD
```

本机与训练机的已提交代码必须指向相同 commit。训练机未跟踪结果目录不得清理、覆盖或加入
Git。

## 3. 已冻结基线与复用边界

现有 fold0/seed3407 复用以下身份：

```text
run:
v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3

adapter:
LlamaFactory/saves/minicpmv4_5/lora/
sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407

merged:
LlamaFactory/saves/minicpmv4_5/lora/
sft_tensile_v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3_seed3407_merged

results:
finetune/results/
v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3/seed3407/fold0
```

只读复用条件：

- adapter `trainer_state.json` 的 `global_step` 为 1125；
- root adapter 对应训练结束后加载的 best checkpoint；
- training run manifest 已冻结；
- 视觉权重和 resampler 权重覆盖验证通过；
- merged BF16 全文件身份可复算；
- fold0 严格评测记录正好 425 条且 identity 一致；
- runtime failure 为 0。

任一身份不匹配时停止并报告。不得用“重训一次”修复既有基线。

历史的 `v4_1_0_760050fad303_20260724_visual` 三折结果只可作为历史诊断，禁止作为当前
fold1/fold2 结果复用。

## 4. 实现批次与提交顺序

代码实现分成五个可独立审查的提交批次。每个批次必须测试通过后再进入下一批次。

### 批次 A：门禁语义与稳定性分析器

新增：

```text
finetune/policies/v4_1_training_stability.json
finetune/analyze_v4_1_training_stability.py
tests/test_v4_1_training_stability.py
```

策略文件固定：

```json
{
  "schema_version": "tensile-vlm-v4.1-training-stability-policy/v1",
  "absolute_performance_mode": "record_only",
  "relative_limits_percentage_points": {
    "fracture_recall": 5.0,
    "non_fracture_recall": 5.0,
    "fracture_f1": 5.0,
    "macro_f1": 5.0,
    "strict_valid_rate": 1.0
  },
  "max_prediction_disagreement_rate": 0.1,
  "require_zero_runtime_failures": true
}
```

分析器输入：

- seed3407 `evaluation_records.jsonl`；
- seed3411 `evaluation_records.jsonl`；
- 两个 evaluation run identity；
- 冻结 scorer 身份；
- 稳定性 policy。

分析器输出：

```text
paired_prediction_comparison.json
relative_stability_gate.json
absolute_performance_snapshot.json
```

实现规则：

- 两份记录必须拥有相同且唯一的 candidate ID 集合；
- 必须逐 candidate 配对，不按 JSONL 行号配对；
- 百分点差值统一使用 `abs(seed3407 - seed3411) * 100`；
- `relative_stability_gate.json` 只含运行完整性和相对差值判定；
- 历史绝对阈值只写入 snapshot 的 `historical_reference`；
- 绝对指标低于历史参考不得改变 gate 布尔值；
- 分母为 0 时写 `available=false`，不能填 0 或判通过；
- 输出必须记录输入文件 SHA-256、policy SHA-256、scorer identity 和生成时间。

测试至少覆盖：

- 37% 与 39% 在 5 个百分点范围内；
- 37% 与 55% 超出稳定范围；
- 两 seed 都低于历史 50% 时仍可稳定性通过；
- candidate 集缺失、重复或错配时 fail closed；
- runtime failure 非零时阻断；
- 分母为 0 时输出 unavailable；
- 10% 不一致率通过，超过 10% 失败；
- 指标恰好等于边界时通过。

### 批次 B：通用三折数据与配置构建器

新增：

```text
finetune/build_v4_1_crossval_coverage_first.py
finetune/prepare_v4_1_crossval_coverage_first.py
tests/test_v4_1_crossval_coverage_first.py
```

不得修改现有不可变 fold0 builder 的输出。新 builder 可以复用其无副作用函数，但必须把
以下 fold0 硬编码参数化：

- `fold_index`；
- train split 路径；
- validation split 路径；
- dataset registry 名称；
- adapter/output/result 路径；
- train/validation 数量和 SHA 字段名。

CLI：

```bash
python finetune/prepare_v4_1_crossval_coverage_first.py \
  --release-dir <release_dir> \
  --fold 1 \
  --seed 3407 \
  --output-root <staging_dir> \
  --validate-only
```

同一命令去掉 `--validate-only` 后才允许冻结内容寻址目录。`<release_dir>` 与
`<staging_dir>` 由当前 release manifest 和训练机预检结果提供，Agent 不得在文档中抄写旧
哈希目录代替运行时发现。

builder 必须输出：

```text
sampling_manifest.json
dataset_info.json
train.json
validation.json
train_config.yaml
merge_config.yaml
run_manifest.json
```

强制验证：

- fold 只允许 0、1、2；
- fold train 和 validation candidate ID 不重叠；
- fold train 和 validation source video 不重叠；
- 三个 validation source 集两两不重叠；
- 三个 validation source 并集等于 release 的 development source 集；
- 所有媒体路径存在且 SHA-256 匹配；
- 每个 fold 的状态配额可满足；
- source cap 和 signature cap 不得静默放宽；
- seed3407 下配置、采样和输出完全可复现；
- fold1/fold2 的 adapter 和结果目录不能与 fold0 或彼此重叠。

### 批次 C：通用训练、merge、评测与监控 runner

新增：

```text
finetune/run_v4_1_crossval_coverage_first.py
finetune/monitor_v4_1_crossval_coverage_first.py
tests/test_v4_1_crossval_runner.py
tests/test_v4_1_crossval_monitor.py
```

CLI：

```bash
python finetune/run_v4_1_crossval_coverage_first.py \
  --run-manifest <immutable_run_manifest> \
  --fold 1 \
  --seed 3407 \
  --phase train

python finetune/run_v4_1_crossval_coverage_first.py \
  --run-manifest <immutable_run_manifest> \
  --fold 1 \
  --seed 3407 \
  --phase merge

python finetune/run_v4_1_crossval_coverage_first.py \
  --run-manifest <immutable_run_manifest> \
  --fold 1 \
  --seed 3407 \
  --phase evaluate
```

runner 约束：

- `--run-manifest` 必须是不可变文件且包含自身以外全部输入哈希；
- phase 只允许 `train/merge/evaluate`，默认不得一次执行全部长阶段；
- 已有活动 PID 时拒绝重复启动；
- 现有完整 phase 幂等返回，不覆盖；
- train 完成必须验证预注册 optimizer steps、视觉权重和 resampler 权重；
- training run manifest 必须在 merge 前冻结；
- merge 必须验证基础模型和 adapter 身份；
- evaluate 必须绑定 merged model、validation、scorer 和生成参数；
- JSONL 恢复只接受完全相同 run identity；
- 不完整或错身份 JSONL 先 quarantine，再按合法记录续跑；
- state、PID、日志和环境文件权限不得弱于现有 runner。

monitor 输出机器可读 JSON，至少包含：

```text
status
phase
pid_running
global_step
expected_global_step
evaluation_record_count
evaluation_expected_count
gpu_memory_mib
disk_free_bytes
eta_reliable
estimated_completion_at
suggested_check_after_seconds
```

训练达到首个 50-step eval 后才可将 ETA 标为可靠。长评测 ETA 使用有效记录数和滚动吞吐，
不得读取预测语义。

### 批次 D：三折完整性与聚合报告

新增：

```text
finetune/analyze_v4_1_three_fold.py
finetune/freeze_v4_1_three_fold_evidence.py
tests/test_v4_1_three_fold_analysis.py
```

输入是 fold0 既有结果与 fold1/fold2 新结果。输出：

```text
three_fold_integrity.json
three_fold_aggregate.json
three_fold_evidence_manifest.json
```

`three_fold_integrity.json` 是阻断结论，验证：

- 三折数据身份属于同一 release、contract、prompt 和 recipe；
- fold0 允许使用既有 seed3407，fold1/fold2 必须使用 seed3407；
- 三折 validation source 两两互斥且覆盖预期 source；
- 每折评测数量与各自 validation manifest 完全一致；
- runtime failure 均为 0；
- 三折 adapter、merged model 和 evaluation identity 完整。

`three_fold_aggregate.json` 只报告：

- 每折样本数和所有绝对指标；
- 样本加权 pooled 指标；
- 三折算术均值、标准差、最小值和最大值；
- 历史参考值与差值；
- unavailable 指标及原因。

任何绝对性能值不得改变三折完整性结论。

### 批次 E：full-development 构建、训练和部署

新增：

```text
finetune/build_v4_1_full_development.py
finetune/run_v4_1_full_development.py
finetune/monitor_v4_1_full_development.py
finetune/prepare_v4_1_full_development_deployment.py
tests/test_v4_1_full_development.py
tests/test_v4_1_full_development_runner.py
tests/test_v4_1_full_development_deployment.py
```

full-development builder 直接读取 release 的权威 published candidate 集。三个 fold 的
train/validation 并集只用于验证，不作为新的真值来源。

每轮 3000 条分两层：

1. `unique_coverage_layer`：每个合法 development candidate 恰好出现一次；
2. `balanced_repeat_layer`：填满剩余额度，只对额外重复应用状态配额、source repeat cap 和
   signature repeat cap。

manifest 必须分别记录：

- 全部唯一 candidate ID 及 SHA；
- unique coverage count 和 coverage rate；
- repeat candidate 计数；
- 每 source 的 unique/repeat/total；
- 每 signature 的 unique/repeat/total；
- 三折并集与 release 全集的集合差；
- sealed/held-out 排除证明。

训练配置固定：

```text
base model: MiniCPM-V 4.5
seed: 3407
rows per epoch: 3000
epochs: 3
gradient accumulation: 8
expected optimizer steps: 1125
LoRA rank: 8
LoRA alpha: 16
LoRA dropout: 0.25
learning rate: 0.000005
weight decay: 0.2
bf16: true
vision tower frozen: false
multimodal projector frozen: false
additional target: resampler
```

full-development 没有独立 validation：

- 配置必须关闭 `load_best_model_at_end`；
- 不得把 training loss 用作质量门；
- 固定使用 step1125 最终 adapter；
- merge 前验证完整训练和视觉覆盖；
- 只允许“MiniCPM-V 4.5 + full-development adapter”合并；
- merged 模型必须生成全部受管文件的大小与 SHA-256 清单。

部署 manifest 的 capability 固定为：

```text
full_development_model
```

不得写：

```text
production_passed
independent_test_passed
quality_final
```

## 5. 实现完成后的本机验证

在本机运行：

```bash
cd /Users/pcoffeep/AgentPlayground/active-projects/mVllm_2

python -m pytest -q \
  tests/test_v4_1_training_stability.py \
  tests/test_v4_1_crossval_coverage_first.py \
  tests/test_v4_1_crossval_runner.py \
  tests/test_v4_1_crossval_monitor.py \
  tests/test_v4_1_three_fold_analysis.py \
  tests/test_v4_1_full_development.py \
  tests/test_v4_1_full_development_runner.py \
  tests/test_v4_1_full_development_deployment.py

python -m pytest -q
git diff --check
```

测试不得读取训练机 sealed 语义或依赖 GPU。测试 fixture 使用临时目录和合成轻量 manifest。

代码和测试提交后：

1. 推送共同 Git remote；
2. 训练机 `fetch`；
3. 只允许 fast-forward 到同一 commit；
4. 再次运行训练机 CPU-only 测试和 `--validate-only`；
5. 不覆盖训练机未跟踪结果目录。

## 6. 训练启动前的强制 dry-run

在训练机执行：

```bash
cd "/home/liuyang/文档/mVllm_2"

/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/run_v4_1_source_aware_3k_coverage_first.py \
  --seed 3411 \
  --validate-only
```

然后分别对 crossval 和 full-development 执行各自 `--validate-only`。dry-run 报告必须冻结：

- repo commit；
- release、split、candidate、prompt 和 scorer identity；
- seed3407/3411 候选多重集相同证明；
- seed3407/3411 顺序哈希不同证明；
- fold source isolation；
- full-development 全覆盖与受限数据排除证明；
- GPU 型号、空闲显存、磁盘空间和 Python 环境；
- 预计训练步数、评测条数和产物路径；
- 当前 seed3407 服务 PID、deployment identity 和回滚命令。

dry-run 通过只代表可以申请启动，不代表自动启动训练。

## 7. 实际运行手册

### 7.1 启动 fold0/seed3411

获得明确启动指令后：

```bash
cd "/home/liuyang/文档/mVllm_2"

/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/run_v4_1_source_aware_3k_coverage_first.py \
  --seed 3411 \
  --phase train
```

必须由现有 orchestrator 的单实例方式启动并记录 PID。若 state 或 PID 显示仍在运行，禁止重复
启动。

监控：

```bash
/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/monitor_v4_1_source_aware_3k_coverage_first.py \
  --seed 3411
```

首个 50-step eval 前按 warm-up 低频检查；其后严格使用
`estimated_completion_at` 和 `suggested_check_after_seconds` 调整 automation。

训练完成后再次执行同一 `--phase train` 入口，使 runner 幂等验证完成状态并冻结不可变
training run manifest；随后按顺序执行：

```bash
/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/run_v4_1_source_aware_3k_coverage_first.py \
  --seed 3411 \
  --phase merge

/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/run_v4_1_source_aware_3k_coverage_first.py \
  --seed 3411 \
  --phase evaluate
```

评测期间只读查看 state、PID、GPU、日志和 identity-bound JSONL 有效条数，不读预测语义。

### 7.2 双 seed 比较

seed3411 评测完整后执行：

```bash
/home/liuyang/miniconda3/envs/agent/bin/python \
  finetune/analyze_v4_1_training_stability.py \
  --seed3407-records <seed3407_evaluation_records> \
  --seed3411-records <seed3411_evaluation_records> \
  --policy finetune/policies/v4_1_training_stability.json \
  --output-dir <dual_seed_report_dir>
```

路径必须从被冻结的 run manifest 解析，不得凭人工记忆拼接。Agent 向维护者展示：

| 类别 | 内容 |
| --- | --- |
| 运行完整性 | 两 seed 步数、视觉覆盖、merge、评测条数、runtime failure |
| 相对稳定性 | 六项差值、不一致率、逐项门和 overall |
| 绝对性能 | 两 seed 指标、历史参考、差值、record-only 标记 |

只有 `relative_stability_gate.json` 的 `overall=true` 才可进入 7.3。

### 7.3 fold1 与 fold2

顺序固定为 fold1 后 fold2；一次只运行一个 GPU 长任务。

每折：

1. `prepare ... --validate-only`；
2. 冻结内容寻址 run manifest；
3. `run ... --phase train`；
4. ETA automation 监控；
5. 幂等冻结 training manifest；
6. `--phase merge`；
7. `--phase evaluate`；
8. 验证评测记录数和 identity；
9. 冻结该折轻量完整性报告。

fold1 完整结束前不得启动 fold2。fold2 完整结束后运行三折 analyzer 和 evidence freezer。

三折向维护者展示：

| fold | train candidates | validation candidates | train sources | validation sources | runtime | 绝对指标 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| fold0 | manifest 值 | manifest 值 | manifest 值 | manifest 值 | 完整性 | record-only |
| fold1 | manifest 值 | manifest 值 | manifest 值 | manifest 值 | 完整性 | record-only |
| fold2 | manifest 值 | manifest 值 | manifest 值 | manifest 值 | 完整性 | record-only |

“manifest 值”由实际冻结文件渲染，不能提前在文档中硬编码。

### 7.4 full-development

三折完整性通过后：

1. 构建 full-development staging manifest；
2. 验证 release 全集覆盖率 100%；
3. 验证 sealed/held-out 受限语义交集为空；
4. 冻结 full-development run identity；
5. 获得启动 full-development 的明确指令；
6. 从 MiniCPM-V 4.5 启动训练；
7. automation 按 ETA 监控至 step1125；
8. 冻结最终 adapter manifest；
9. merge BF16；
10. 生成全文件哈希和 model component manifest。

该阶段没有质量 pass/fail。训练成功只表示：

- 数据全集身份正确；
- 训练、视觉权重和 adapter 完整；
- merge 完整；
- 模型可以进入链路验证。

### 7.5 推理入口验证与切换

不要直接替换 `127.0.0.1:8002`。先为 full-development 分配未占用 loopback 端口：

1. 用 deployment manifest 启动新服务；
2. 验证 contract、model/deployment identity、BF16 和 GPU；
3. 对预注册 development 真实视频做单条 smoke call；
4. 建立本机 SSH tunnel；
5. 运行 TensileAgent contract、doctor 和真实视频调用；
6. 主动断 tunnel，验证 fail closed 且无协议降级；
7. 恢复 tunnel；
8. 更新 delivery bundle 的 current 指针；
9. 保留 previous bundle 和 seed3407 服务回滚命令；
10. 再按 bundle 操作规程切换正式 loopback 端口引用。

任何步骤失败都保持 seed3407 为当前入口，不重训 full-development。

## 8. Automation 规则

长训练、merge、严格评测和全文件哈希可以使用 automation；交互 Goal 不得高频等待。

automation 每次只读检查：

- state JSON；
- PID 是否仍存活；
- GPU 使用和显存；
- 磁盘空间；
- 日志尾部；
- global step 或 identity-bound 评测记录数；
- ETA 元数据。

automation 只有在以下情况下执行恢复：

- PID 已结束且 state 非完成；
- 日志确认属于基础设施错误；
- run identity、checkpoint 或合法 JSONL 前缀与原 run 完全一致；
- 恢复不会改变数据、模型、prompt、scorer、生成参数或阈值。

以下情况停止并通知维护者：

- 数据、模型、prompt、scorer 或 manifest 身份漂移；
- GPU/磁盘故障无法在原身份下恢复；
- 双 seed 相对稳定性失败；
- full-development 全集覆盖无法满足；
- 需要 sealed 数据、凭据、生产授权或不可恢复操作。

## 9. 每阶段提交与 Git 边界

允许提交：

- Python 源码、测试和 schema；
- train/merge 配置；
- policy；
- 内容寻址轻量 manifest；
- 无受限逐样本语义的完整性、稳定性和聚合摘要；
- deployment component 和文件哈希清单；
- 文档。

禁止提交：

- 原始视频、clip、抽帧；
- dataset 大 JSON；
- adapter、checkpoint、optimizer、merged model；
- 原始长日志；
- sealed/held-out 标签；
- 逐样本预测或 source-level 受限错误语义；
- token、密钥和 `.env`。

每次提交前：

```bash
git status --short
git diff --check
python -m pytest -q
```

只显式 `git add` 本批次文件，不使用 `git add .`。推送后训练机只允许 fast-forward；禁止
`reset --hard`、`clean` 或覆盖未跟踪运行产物。

## 10. 最终完成门

整个计划只有同时满足以下条件才算实施完成：

- 双 seed 运行完整且相对稳定性通过；
- 双 seed 绝对性能已记录但没有作为阻断门；
- fold0/fold1/fold2 三折运行完整、source isolation 和评测完整；
- 三折绝对性能、均值和标准差已冻结为 record-only；
- full-development 覆盖全部合法 development candidates；
- full-development adapter 完成 1125 steps 且视觉覆盖有效；
- full-development merged BF16 全文件哈希通过；
- 新服务 contract、真实视频远程 GPU 调用和断 tunnel fail-closed 通过；
- delivery bundle 已原子切换并保留 seed3407 回滚入口；
- Git 中没有权重、视频、密钥、sealed 标签或逐样本受限结果；
- 所有报告均未宣称生产、独立测试或质量 final 通过。

## 11. Agent 续跑提示

```text
请完整阅读并严格执行：
/home/liuyang/文档/mVllm_2/docs/plans/
2026-07-27-v4-1-dual-seed-three-fold-full-data-training-design.md

以及：
/home/liuyang/文档/mVllm_2/docs/plans/
2026-07-27-v4-1-dual-seed-three-fold-full-data-training-implementation.md

严格按“实现与测试 → fold0 双 seed → 三折 → full-development → 新端口链路验证 →
原子切换”的顺序推进。当前 seed3407 不得重训；历史绝对性能只记录，不阻断；双 seed
相对稳定性是进入三折的唯一质量相关阻断门。三折模型不得互相合并，full-development 必须
从 MiniCPM-V 4.5 基础模型重新训练。禁止读取 sealed 标签、提交大型或受限产物、停止当前
推理服务或未经链路验证切换入口。长任务使用 ETA 驱动 automation，禁止高频忙等待。
```
