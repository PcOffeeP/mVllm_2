# V4.1 phase-2 source-aware 3k

> 状态：Stage B 训练中；尚未通过晋级门，不得进入 Stage C。

本目录冻结 Stage B 的轻量运行身份。训练、checkpoint、merged BF16、逐样本预测和
full-hash 证据保留在训练机的内容寻址运行目录；两个 seed 完成并通过全部门槛后，
再在此补充最终指标和证据 manifest 摘要。

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
- seeds：`3407`、`3411`

每个 seed 使用同一份恰好 3000 行的确定性清单训练 3 epochs，共 9000 次样本曝光和
1125 optimizer steps。每份清单包含 900 条 `未断裂`，其余 2100 条按其他状态频数
反平方根加权；单一 source 上限 5%，有效帧签名上限 3。

## 已冻结的采样证据

| seed | sequence SHA-256 | 最大 source 占比 | 最大签名重复 |
|---|---|---:|---:|
| 3407 | `de0673b494e866e16bc0e17cde22de072750e9c0e4668bc85e134c63c8fedf15` | 3.6333% | 3 |
| 3411 | `4bec24c3414786c9df9109c16d07c47e5ec087ec3cb2b6892301177003e1eba3` | 3.7000% | 3 |

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

runner 会拒绝接管不完整或身份漂移的训练/合并目录。已完成的 1125-step 训练、完整
merged BF16 和 425 条零 runtime-failure 评测可幂等跳过。每个 seed 完成训练后必须
先生成独立、不可变的 `training_run_manifest.json`，再进入 merge。
