# V4.1 双随机种子、三折验证与全量训练实施设计

> 编写日期：2026-07-27
> 文档状态：已由维护者审查并批准
> 批准日期：2026-07-27
> 执行状态：本文不授权启动训练、评测、模型切换或长视频批处理

## 1. 目标与范围

在保留当前 coverage-first seed3407 merged BF16 中间模型和既有评测证据的前提下，
把后续训练拆成三个顺序严格、身份可验证的阶段：

1. 在同一 fold0 上完成 seed3407 与 seed3411 的双随机种子稳定性测试；
2. 稳定性通过后，完成 fold0、fold1、fold2 三折训练与留一折评测；
3. 三折完整结束后，使用全部 development 数据重新训练一个全量 LoRA，并与
   MiniCPM-V 4.5 基础模型合并为独立 BF16 模型，作为新的受控推理入口。

本实施只把运行完整性和相对稳定性作为阻断门。原先设定的绝对性能目标继续完整计算和展示，
但不再决定训练成功或失败，也不自动触发调参、数据修订或重新训练。

## 2. 当前基线

当前部署模型身份是 coverage-first fold0 seed3407：

- 基础模型：MiniCPM-V 4.5；
- 数据来源：V4.1 Phase 2 development release 的 fold0 training split；
- 采样策略：source-aware coverage-first；
- 每轮 3000 条训练曝光，共 3 轮；
- optimizer steps：1125；
- 训练方式：4-bit QLoRA，视觉塔和 resampler 均参与适配；
- 交付形态：LoRA 与基础模型合并后的独立 BF16 模型；
- 当前定位：`intermediate_development_model`。

coverage-first seed3411 尚未训练。更早版本虽然存在三折 visual 模型，但其 release、prompt、
采样策略和训练身份与当前 coverage-first 模型不同，不能补作当前方案的 fold1/fold2，也不能
加入当前稳定性结论。

## 3. 非目标

- 不在本文确认前启动 seed3411、fold1、fold2 或全量训练。
- 不读取 sealed-test 标签或把 Stage D/Stage G 受限真值并入训练。
- 不因绝对性能低于历史目标而自动判失败、调参、改 prompt 或重训。
- 不把三个 fold 模型直接做权重平均、LoRA 合并或投票服务。
- 不把三折交叉验证结果表述为全量模型结果。
- 不把新的全量 development 模型表述为生产通过或独立测试通过。
- 不覆盖或删除当前 seed3407 adapter、merged BF16、运行 manifest、评测记录和部署回滚入口。

## 4. 方案比较

### 方案 A：继续使用绝对性能门阻断训练

优点是延续旧 Stage B 的质量目标。缺点是当前目标已经从“立即优化模型”改为“验证训练稳定性
并跑通完整训练交付链路”；例如断裂召回率 37% 低于历史 50% 参考线时，会把一个运行完整、
可比较的模型误判为训练失败。

不采用。

### 方案 B：取消全部门禁，只保存指标

优点是执行最简单。缺点是无法回答“双随机种子是否稳定”，也无法阻止样本丢失、身份漂移、
权重未覆盖视觉模块或两个 seed 使用不同数据等无效比较。

不采用。

### 方案 C：完整性门和相对稳定性门阻断，绝对质量只记录

它将三类结论分开：

- 运行是否可信；
- 双随机种子是否相近；
- 模型绝对性能是多少。

采用方案 C。

## 5. 统一术语与身份边界

### 5.1 双随机种子

双随机种子是同一 fold、同一候选多重集、同一超参数和同一验证集上的两次独立训练。
seed3407 与 seed3411 允许改变：

- 3000 条固定候选多重集的排列顺序；
- LoRA 参数初始化；
- dropout 掩码；
- Python、NumPy、PyTorch 和 CUDA 训练随机状态。

coverage-first 的候选选择仍使用固定 selection seed，两个训练 seed 必须拥有完全相同的
候选 ID 及重复次数，只允许顺序不同。因此本阶段验证的是完整训练流程面对正常随机扰动时的
稳定性，而不是只隔离某一个随机算子。

### 5.2 三折验证

三折验证包含三个从同一基础模型独立开始的模型：

- fold0 train → fold0 validation；
- fold1 train → fold1 validation；
- fold2 train → fold2 validation。

每折 validation 的源视频不得出现在该折 training 中。三折模型只用于交叉验证和汇总统计，
不互相合并为推理模型。

### 5.3 全量训练

全量训练从 MiniCPM-V 4.5 基础模型重新开始，使用 V4.1 Phase 2 release 中全部可用于
development 训练的候选。它不加载任一 fold 模型继续训练，也不使用 sealed-test、held-out
逐样本语义或 Stage G 输出作为标签。

“合并后的全量模型”只表示：

```text
MiniCPM-V 4.5 基础模型 + 全量 development LoRA → 独立 merged BF16
```

不表示三个 fold adapter 之间的合并。

## 6. 门禁模型

### 6.1 阻断门一：运行与身份完整性

每次训练必须同时满足：

- release、split、candidate multiset、prompt、contract、训练配置和代码 commit 已冻结；
- 训练进程正常完成，optimizer step 与预注册计划一致；
- adapter、trainer state、训练日志和不可变 training run manifest 完整；
- LoRA 权重存在，视觉塔目标和 resampler 目标覆盖数量符合配置；
- merge 输入只引用本次 adapter 和指定基础模型；
- merged BF16 文件、分片、dtype、配置和完整哈希验证通过；
- 评测使用预注册 validation、scorer、生成参数和模型身份；
- 评测记录数准确，逐条身份唯一，无 runtime failure，聚合报告可复算。

任一项失败时停止当前阶段。纯基础设施故障可以在同一身份下按恢复边界续跑；数据、prompt、
模型或 scorer 身份发生变化则必须建立新 run，不能把结果续接到旧身份。

### 6.2 阻断门二：双随机种子相对稳定性

稳定性比较只使用 seed3407 与 seed3411 在同一 fold0 validation 上的冻结结果。采用以下
预注册等价范围：

| 相对指标 | 允许差值 |
| --- | ---: |
| 断裂存在召回率 | 不超过 5 个百分点 |
| 未断裂召回率 | 不超过 5 个百分点 |
| 断裂存在 F1 | 不超过 5 个百分点 |
| macro F1 | 不超过 5 个百分点 |
| strict valid rate | 不超过 1 个百分点 |
| 逐样本“是否断裂”预测不一致率 | 不超过 10% |

所有具备有效分母的相对指标必须同时满足等价范围。没有有效分母的细分指标必须标为
`unavailable`，不得解释为通过；它们只进入诊断附录，不阻断双 seed。

若相对稳定性未通过：

- 冻结两次训练和比较报告；
- 不把任一 seed 的绝对性能高低作为覆盖稳定性失败的理由；
- 不自动调参或重训；
- 不进入三折训练，等待维护者另行决定。

### 6.3 非阻断门：绝对性能快照

原 Stage B 的性能目标保留为 `historical_reference`，不再输出模型质量
`pass/fail`。报告至少包含：

- 断裂存在 accuracy、precision、recall、F1；
- 未断裂 recall；
- clip state 各类别 precision、recall、F1；
- macro/micro 指标；
- mechanism、site 和特殊样例指标（有有效分母时）；
- LOSO/source-aware 诊断；
- 历史参考值、实际值和差值；
- scorer 无法计算的字段及原因。

例如历史断裂召回率参考值为 50%，模型实际为 37% 时，报告写为“实际 37%，低于历史参考
13 个百分点，记录项，不阻断”，不得写为训练失败，也不得写为达到质量门。

## 7. 实施顺序

### 阶段 0：执行前冻结

1. 只读验证当前 seed3407 adapter、merged BF16、training manifest 和 fold0 评测。
2. 冻结新的训练计划 manifest，记录本文版本、代码 commit、release、三折 split、prompt、
   scorer、基础模型、训练参数、生成参数和门禁规则。
3. 为 seed3411、fold1、fold2 和 full-development 分配互不复用的 run identity 和目录。
4. 运行配置 dry-run、数据哈希、媒体存在性、source isolation、磁盘和 GPU 资源预检。
5. 未获得维护者对实施文档和冻结 manifest 的明确授权前停止。

### 阶段 1：fold0 双随机种子稳定性

1. seed3407 作为既有基线，只验证，不重复训练。
2. 确认 seed3411 与 seed3407 的候选多重集哈希相同、候选顺序哈希不同。
3. 从同一 MiniCPM-V 4.5 基础模型启动 seed3411。
4. 完成 1125 optimizer steps、视觉覆盖验证和不可变 training manifest。
5. 合并 seed3411 adapter 为独立 BF16。
6. 使用与 seed3407 完全相同的 fold0 validation、scorer 和生成参数评测。
7. 生成双 seed 逐样本配对比较、相对稳定性报告和绝对性能快照。
8. 只有运行完整性与相对稳定性均通过，才授权阶段 2。

### 阶段 2：三折训练与验证

1. 选择 seed3407 作为三折统一训练 seed。
2. 当前 fold0/seed3407 仅在身份完全匹配时复用；不匹配则停止并报告，不能静默重训。
3. 分别为 fold1 和 fold2 构建 coverage-first 训练 multiset。状态配额、source cap 和
   signature cap 不能静默放宽；若某折容量不足，预检失败并停止。
4. fold1、fold2 均从同一 MiniCPM-V 4.5 基础模型独立训练，不加载 fold0 权重。
5. 每折完成 adapter、training manifest、merged BF16 和对应 validation 评测。
6. 验证三折 validation 的 source 集合互斥，并验证每折 training/validation 无同源泄漏。
7. 汇总逐折指标、样本加权总体指标、三折均值、标准差和最差折结果。
8. 三折绝对性能全部只记录。只要三折运行完整，不因低于历史性能参考而阻断阶段 3。

### 阶段 3：全部 development 数据训练

1. 直接从同一 release 的权威 published candidate 集构造 full-development 候选集合，
   以 candidate ID 去重；三个 fold 的 train/validation 并集只用于反向验证全集身份，
   不能取代权威 release。
2. 验证 full-development 候选集合等于 release 中允许训练的全部 development 候选，
   且不包含 sealed-test、held-out 受限逐样本语义或评测预测。
3. 构造每轮 3000 条 coverage-first multiset，并强制每个合法 development candidate
   每轮至少曝光一次。该全集基础层保留 release 的真实 source/signature 分布；剩余额度作为
   重复曝光层，才按冻结状态配额、source repeat cap 和 signature repeat cap 分配。任何
   source 或 signature 的额外重复都不能伪装成新的唯一候选。
4. 使用 seed3407、3 epochs、gradient accumulation 8 和现有超参数从基础模型重新训练。
5. 全量阶段没有独立 validation，不使用训练集指标选择 best checkpoint；固定使用完成
   1125 optimizer steps 后的最终 adapter。
6. 将全量 adapter 与 MiniCPM-V 4.5 合并为独立 BF16，计算全文件哈希并生成
   `full_development_model` 组件 manifest。
7. 不使用三折 validation 或 sealed-test 结果调节已经完成的全量模型。

### 阶段 4：受控推理入口切换

1. 保持当前 seed3407 服务运行，先在新的 loopback 端口启动 full-development BF16。
2. 验证 contract、deployment identity、dtype、GPU、真实 development 视频调用和响应 schema。
3. 本机通过 SSH tunnel 完成 TensileAgent contract、doctor、真实视频调用和断隧道
   fail-closed 验证。
4. 所有链路门通过后，原子切换 delivery bundle 的当前模型引用。
5. 保留当前 seed3407 模型、服务命令和 previous bundle 作为回滚入口。
6. 新模型准确标为 `full_development_model` 和“当前推理入口”，不得标为生产通过、
   independent-test-passed 或质量 final。

## 8. 组件与职责

### 数据与采样构建器

- 读取不可变 release 和 source-level folds；
- 构建双 seed 共享候选多重集与不同顺序；
- 构建 fold1/fold2 训练 multiset；
- 构建 full-development 候选并集和全覆盖 multiset；
- 输出身份、配额、source、signature 和媒体哈希诊断。

### 训练 orchestrator

- 每个 run 只启动一次；
- 维护阶段状态、PID、日志、checkpoint、恢复边界和不可变 training manifest；
- 长训练只通过 ETA 驱动的低频 automation 监控，不由交互任务高频轮询。

### 评测与稳定性 analyzer

- 对同一验证集做身份绑定的逐样本评测；
- 分离 runtime/integrity、relative_stability 和 absolute_performance 三类结论；
- 生成双 seed 配对差值、三折汇总和绝对性能快照；
- 不读取 sealed-test 标签。

### 模型合并与 deployment

- 只允许“基础模型 + 当前 run adapter”的单一合并；
- 验证 BF16、分片和全文件哈希；
- 训练机只提供 loopback 模型推理服务；
- TensileAgent 保留在本机，通过 SSH tunnel 访问。

## 9. 产物布局与最小清单

每个阶段至少冻结：

```text
run_manifest.json
state.json
training_run_manifest.json
sampling_manifest.json
adapter_file_manifest.json
merged_model_file_manifest.json
evaluation_run_identity.json
evaluation_summary.json
absolute_performance_snapshot.json
```

双 seed 追加：

```text
paired_prediction_comparison.json
relative_stability_gate.json
```

三折追加：

```text
three_fold_integrity.json
three_fold_aggregate.json
```

全量与部署追加：

```text
full_development_dataset_manifest.json
full_development_model_component.json
deployment_manifest.json
delivery_validation.json
rollback_manifest.json
```

逐样本预测、大型模型、adapter、视频、checkpoint、optimizer 和受限语义不得进入 Git。
Git 只同步代码、配置、测试、schema、轻量 manifest、完整性结论和无受限逐样本内容的聚合报告。

## 10. 失败处理

- 训练进程异常退出：保留日志和 checkpoint；只有 identity 与恢复策略匹配时才能续跑。
- JSONL 尾部损坏：隔离损坏尾部，按模型、数据、scorer、生成参数和样本身份续跑。
- 数据或配置漂移：当前 run 失败并冻结，不允许原目录覆盖。
- 双 seed 相对稳定性失败：停止在阶段 1，不自动优化。
- 三折某一折运行完整性失败：停止在该折；已完成折保持只读，不生成伪三折汇总。
- 某折绝对性能较低：如实记录，不阻断后续全量训练。
- full-development 数据未做到全集覆盖：停止训练前预检。
- 新服务 contract 或真实视频调用失败：不切换当前入口，继续使用 seed3407 服务。
- 推理入口切换后异常：按 previous bundle 回滚，不重新训练。

## 11. 测试策略

实施前必须增加或扩展自动化测试，覆盖：

- 双 seed 候选多重集相同、顺序不同；
- train/eval seed、数据 seed 和输出目录身份不会串用；
- fold0/fold1/fold2 source isolation 和 validation 互斥；
- full-development candidate 并集精确且排除受限数据；
- full-development 每轮唯一候选覆盖率为 100%；
- 历史绝对性能阈值只生成差值，不产生阻断失败；
- 相对稳定性边界值、无效分母和逐样本不一致率；
- 视觉 adapter 覆盖、1125 steps 和 merged BF16 完整性；
- 评测记录的 identity-bound 恢复；
- 新旧服务并行预检、bundle 原子切换和回滚；
- SSH tunnel 正常调用与断隧道 fail-closed。

执行前验证至少包含：

```bash
pytest -q
git diff --check
```

训练机还需执行配置 dry-run、数据/media 哈希预检、磁盘空间检查和 GPU 基线检查。任何长训练
或长评测的自动化监控必须依据运行输出的 ETA 调整频率。

## 12. 阶段结果向维护者展示

每个核心阶段完成后只展示一张结论表，并附机器 manifest 路径：

| 阶段 | 必须展示 |
| --- | --- |
| seed3411 训练 | 数据身份、步数、视觉覆盖、adapter、merge、运行完整性 |
| 双 seed 比较 | 两 seed 的绝对指标、指标差值、预测不一致率、稳定性结论 |
| 三折训练 | 每折数据量、source isolation、运行状态、逐折指标、均值和标准差 |
| 全量训练 | development 全覆盖证明、步数、adapter、merged BF16、全文件哈希 |
| 推理入口 | contract、deployment、真实视频调用、SSH tunnel、fail-closed、回滚 |

任何表格都必须把以下三项分列，禁止合并为一个模糊的“通过/失败”：

1. 运行完整性；
2. 相对稳定性；
3. 绝对性能记录。

## 13. 授权边界

本文批准后，实施仍应按阶段授权：

1. 先只允许准备代码、测试、配置和 dry-run；
2. 再明确授权启动 seed3411；
3. 双 seed 稳定性报告通过后，才允许启动 fold1/fold2；
4. 三折完整报告生成后，才允许启动 full-development；
5. full-development 链路验证完成后，才允许切换当前推理入口。

任一阶段授权都不能扩展为读取 sealed 标签、修改性能标准、自动调参、重复训练已完成 run 或
宣称生产通过。
