# V4.1 Phase 2 development 发布冻结

> 日期：2026-07-26
> 状态：阶段 A 完成；下一步为 source-aware 3k 双 seed。

## 冻结身份

- release：`v4.1.0-ecb5aeb9657c`
- release manifest SHA-256：
  `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`
- combined review：
  `combined-review-decisions-b4ade2d3e526`
- combined review SHA-256：
  `0537ba7b783f3709fe7bd5c4eedc1a728a89e2c35b10cd1ba1987653d601c25a`
- contract hash：
  `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`
- 代码提交：`97d36a90003957be3c13b5dbfc017452a308e54d`

基础不可变发布 `v4.1.0-760050fad303` 未改写；其 manifest SHA-256 复验为
`c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`。

## 数量闭合

| 项目 | 数量 |
| --- | ---: |
| 基础发布 | 1275 |
| 阶段 2 候选 | 410 |
| `existing_human` | 33 |
| `historical_consensus` | 233 |
| `manual_review` | 144 |
| 阶段 2 排除 | 7 |
| 阶段 2 加入 | 403 |
| 最终 development | 1678 |

人工决定累计为 approved 635、corrected 299；历史一致沿用 233 条单独记录，不计作
本轮人工批准。

## Split

| Split | 数量 |
| --- | ---: |
| fold0 train / validation | 1253 / 425 |
| fold1 train / validation | 1014 / 664 |
| fold2 train / validation | 1186 / 492 |

source、密封测试来源、有效帧签名和近重复视图隔离门均通过。新发布的
`metadata/training_candidates.json` 为每个 development 候选补充了
`effective_frame_signature`，供阶段 B 限制同一有效视图的重复次数。

## 验证

训练机实际执行：

```bash
python pipeline/scripts/release_build_phase2.py --validate-only
python pipeline/scripts/release_build_phase2.py
python finetune/release_validate.py \
  --release-id v4.1.0-ecb5aeb9657c \
  --verify-media
```

结果：

- preflight 与发布后复跑得到相同 release ID；
- 1678 条媒体、标签、三个 fold 和 11 个受管文件全部通过；
- 11 个文件的 size 和 SHA-256 与 release manifest 一致；
- runtime failure 为 0；
- 本机全量轻量测试：`542 passed, 1 skipped`；
- 训练机阶段 A 相关测试：`19 passed`；
- 训练机全量测试只因既有 `agent` 环境缺少 `streamlit-cropper` 在 3 个 ROI
  模块收集阶段停止，和阶段 A 发布路径无关。

大型媒体与发布数据保留在训练机外部数据根，不进入 Git。
