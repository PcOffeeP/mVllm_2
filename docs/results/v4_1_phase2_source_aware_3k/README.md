# V4.1 phase-2 source-aware 3k

> 状态：首次 Stage B 双 seed 已完成但未通过开发晋级门；Stage C 未授权。

本目录冻结 Stage B 的轻量运行身份。训练、checkpoint、merged BF16、逐样本预测和
full-hash 证据保留在训练机的内容寻址运行目录。首次运行的失败指标已冻结为
`stage_b_gate_summary.json`；原采样、模型和结果保持只读，后续修订使用新的内容寻址
身份。

## 冻结输入

- development release：`v4.1.0-ecb5aeb9657c`
- release manifest SHA-256：
  `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`
- sampling ID：`source-aware-3k-dd89b70e9d63`
- sampling manifest SHA-256：
  `f7629ef943f81402978234405899749d0380603407a5fc2cf706710f839a9044`
- run ID：`v4_1_phase2_source_aware_3k_dd89b70e9d63`
- 实际训练启动代码 commit：
  `f6ba152121d394141ddddaf73926e3a9c065d0a8`
- 启动时 run manifest SHA-256：
  `9f7a025a676310b0bda8495f715caaf2a219933247542693aac3471f44558db6`
- seeds：`3407`、`3411`

每个 seed 使用同一份恰好 3000 行的确定性清单训练 3 epochs，共 9000 次样本曝光和
1125 optimizer steps。每份清单包含 900 条 `未断裂`，其余 2100 条按其他状态频数
反平方根加权；单一 source 上限 5%，有效帧签名上限 3。

## 已冻结的采样证据

| seed | sequence SHA-256 | 最大 source 占比 | 最大签名重复 |
|---|---|---:|---:|
| 3407 | `de0673b494e866e16bc0e17cde22de072750e9c0e4668bc85e134c63c8fedf15` | 3.6333% | 3 |
| 3411 | `4bec24c3414786c9df9109c16d07c47e5ec087ec3cb2b6892301177003e1eba3` | 3.7000% | 3 |

## 首次运行结论

双 seed 均完成 1125 optimizer steps、视觉 adapter 覆盖、BF16 合并和 425 条严格
fold0 评测，两个评测均为严格有效率 100%、runtime failure 0；但效果门未通过：

- seed 3407：断裂三状态宏召回 38.6508%，四状态宏召回 42.3389%，`已断裂`
  recall 18.1818%，`未断裂` recall 53.4031%，joint 36.2353%，LOSO 通过；
- seed 3411：断裂三状态宏召回 26.8818%，四状态宏召回 39.4022%，`已断裂`
  recall 18.1818%，`未断裂` recall 76.9634%，joint 41.1765%，LOSO 未通过；
- 双 seed 均值为断裂三状态宏召回 32.7663%、四状态宏召回 40.8705%、
  `已断裂` recall 18.1818%、`未断裂` recall 65.1833%、joint 38.7059%。

最终 adapter 与各自 best checkpoint-200 的 SHA-256 完全一致，因此不是保存或模型选择
错误。development-only 归因显示其余三种状态的每 epoch 曝光约为
342/1221/537，Seed 间预测偏置明显。硬约束下每类最大合法曝光分别为
351/1677/564/1167，因此“各 700 条”不可行且不得放宽 signature 上限。

下一修订只改变候选选择策略：保留 900 条 `未断裂`，使用 coverage-first 的共享候选
多重集，三个其他状态固定为 351/1185/564；每个候选至少覆盖两次，第三层补足配额，
两个 Seed 只改变顺序而不改变候选重复次数。数据、两个 seed、LoRA、帧数、训练超参数、
source/signature 上限、评测和晋级阈值全部不变。不得读取 sealed labels。

## 晋级门

两个 seed 必须分别满足：

- 断裂三状态宏召回率至少 32.72%
- 四状态宏召回率至少 43.82%
- `已断裂` recall 至少 20.15%
- `未断裂` recall 至少 75.10%
- joint accuracy 至少 41.12%
- 首轮严格契约合法率 100%
- runtime failure 为 0
- 移除任一 source 后保留至少 50% 的三项主要 recall 聚合提升

仅当两个 seed 都通过时，报告两者均值并进入 Stage C。不得挑选较好 seed、放宽阈值
或读取密封测试标签。

## 运行与恢复

- 训练状态：
  `finetune/run_logs/v4_1_phase2_source_aware_3k_dd89b70e9d63/state.json`
- ETA monitor：
  `python finetune/monitor_v4_1_source_aware_3k.py --seed <seed>`
- runner：
  `python finetune/run_v4_1_source_aware_3k.py --seed <seed> --phase <phase>`
- 晋级分析：
  `python finetune/analyze_v4_1_source_aware_3k.py`
- 证据冻结：
  `python finetune/freeze_v4_1_source_aware_3k_evidence.py`
- Stage C 授权：
  `python finetune/authorize_v4_1_stage_c.py --evidence-manifest <full-hash-manifest>`

runner 会拒绝接管不完整或身份漂移的训练/合并目录。已完成的 1125-step 训练、完整
merged BF16 和 425 条零 runtime-failure 评测可幂等跳过。每个 seed 完成训练后必须
先生成独立、不可变的 `training_run_manifest.json`，再进入 merge。

### 中断恢复边界

若 training 或 merge 进程异常退出：

1. 读取 `state.json` 的 `orchestrator_pid`，确认该 PID 和对应子进程均已退出；
2. 记录失败阶段、退出码、日志路径、原目录和当前 HEAD；
3. 将不完整目录用同一文件系统内的原子 rename 移到
   `LlamaFactory/saves/minicpmv4_5/lora/.quarantine/` 下的新时间戳目录；
4. 保留 quarantine，不删除、不覆盖，并在原规范路径不存在后重新执行严格 preflight；
5. 只有身份、媒体、配置 hash、GPU 和容量门再次通过后才重新启动。

不得在 PID 仍存活时移动目录，也不得直接删除不完整 checkpoint 或 merged shards。
这类 quarantine 是可恢复操作，不代表产物通过。

严格评测采用不同恢复策略：`evaluation_records.jsonl` 每条写入后 `flush + fsync`，
`run_identity.json` 不变时从已有 candidate 集继续；身份漂移、重复 candidate 或
dataset 外 candidate 会失败，不得通过 quarantine 后混合两次评测身份。

### Stage B → C 授权

Stage C 不以人工判断或 README 状态启动。只有 `stage_b_gate_report.json` 明确显示
两个 seed 全部通过，且 Stage B evidence 使用 full model hashes、两个 trainer state
均为 1125 steps、两个视觉 adapter 均覆盖 VPM 和 resampler 时，授权器才生成不可变、
内容寻址的 `stage_c_authorization.json`。Stage C 的任何 preflight 必须消费该授权；
当前 `failed_development_gate` 状态没有授权。

最终 evidence manifest 必须分别记录 `training_code_commit` 和
`evidence_freeze_code_commit`；后者仅表示执行哈希冻结器的代码版本，不能替代实际
训练启动版本。
