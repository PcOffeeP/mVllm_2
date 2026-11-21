# 变更窗口声明：子视频新批次重生成与回传

- 状态：新批次已在训练机生成、回传本机并完成全量哈希核对；三份 JSON 已纳入本仓 `data/sub_video/`，媒体不入库。人工审核未开始，未发布。
- 时间窗口：2026-11-20，至生成、审计与回传核对完成。
- 动因：重标注与开发集三折重跑后，按新输入重生成候选；旧批次的审核决定不计入新批次进度。

## 批次身份与涉及文件

输入指纹共 10 项，逐条列在清单 `identity.inputs`：标注表 `data/annotation-table-full.csv`、`data/roi/manifest.json`、`data/splits/three-fold/` 下 7 份划分成员与 `docs/subvideo-current-logic.md`；`identity.input_mode="official"`。`identity.rules.digest` 为 `4e6ea196…1c8c`，与历史 1,621 批次及 plan 版一致。训练机入口为 `ssh liuyang@100.70.83.68`，落点为 `~/文档/TensileAgent-Finetune`。本次使用 `--verification basic`，`toolchain.degraded=false`。

回传到 `data/sub_video/` 的三份 JSON 已分别核对 SHA-256：

| 文件 | 字节数（B） | SHA-256 |
| --- | ---: | --- |
| `manifest.json` | 10,549,279 | `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f` |
| `summary.json` | 4,820 | `4919c1b23ece18d2d76fa0c472befa306f0a2c3a85fa9dca0a204d8fe18a52ef` |
| `audit.json` | 14,280 | `e579da79dfab2455bb0a3203feead78b4defa00e5903a6908a94164ac4b237d9` |

## 产出与划分

- 110 个来源，1,633 个候选，全部 `status=cropped`；`complete=true`、`reused_candidates=0`。媒体为 1,633 个 mp4，共 191,625,749 B。`published=false`，`manual_review="required_for_every_publishable_clip"`。
- 角色：`pre` 825、`fracture` 576、`post` 127、`coverage` 93、`no_fracture` 9、`unclamped` 3。
- `excluded_windows=54`：pre 越下界保护 28、post 余量不足 2 秒 18、过渡未覆盖完整事件 6、未夹紧素材不足 2。
- development 1,319、test 314；各折候选数（`fold_counts`）如下：

| 折 | train | val | test |
| --- | ---: | ---: | ---: |
| 0 | 887 | 432 | 314 |
| 1 | 879 | 440 | 314 |
| 2 | 872 | 447 | 314 |

## 生成、审计与证据边界

训练机依次执行：

```bash
generate.py --verification basic --output-dir data/sub_video
generate.py --audit-only --write-audit --output-dir data/sub_video
```

生成流程本身不写 `audit.json`；由第二条命令单独写入，`generate.py:1003-1004` 明确校验 `--write-audit requires --audit-only`。

- `checked_candidates=1633`、`checked_sources=110`、`candidates_needing_attention=63`。63 条均有「未断裂片段的断后脱夹需复核」，其中 15 条同时有「未断裂与爆炸性断裂互斥」。`label_status="candidate_labels_only_unreviewed"`，`clip_replays_recorded=0`、`source_replays_recorded=0`。
- `audit.json` 顶层 `manifest_sha256` 与 `manifest.json` 的实际 SHA-256 完全一致；`generation_validation.run_summary_sha256` 与 `summary.json` 的实际 SHA-256 完全一致。
- `generation_validation` 的 `method="generator_final_manifest_validation"`、`scope="output_bytes_and_metadata_only"`、`validated_outputs=1633`。六项限制为 `no_frame_level_replay`、`no_source_timeline_replay`、`no_clip_frame_correspondence`、`not_new_frame_replay`、`not_human_label_review`、`not_data_publication`。
- 按[当前子视频生成逻辑](../subvideo-current-logic.md) §8，`basic`／`none` 不提供任何帧对应证明。本批 `verification.frame_replay="skipped"`，`reason="user_requested_fast_generation"`。消费方不得将其视为已验证帧对应，也不得据 `frame_mapping` 反推像素对应；需要帧对应或时间戳证据时须以 `--verification full` 生成。

## 与历史批次的差异

相对历史 1,621 个候选，新增的 12 个全部来自 `video_0040` 的 `pre`（3 → 15）。该源断裂模式由脆性改为半脆半韧；按[当前子视频生成逻辑](../subvideo-current-logic.md) §2，脆性断前窗口靠近事件，最多 3 个；半脆半韧窗口分布在可用断前区间的前、中、后，最多 15 个。其余 109 个来源逐源逐角色完全相同。

## 媒体回传与全量核对

媒体留在训练机，不入库；本机按[跨机审查运行手册](../training-machine-review-runbook.md) §5.1 同步。核对记录在仓库外 `~/pi-workspace/tensile-finetune/batch2-sync-verify-20261120.md`。

- 对本机 `data/sub_video/videos/` 逐文件实算 SHA-256，与清单 `output.sha256` 比对，1633/1633 一致，缺失 0、不一致 0；191,625,749 B 与训练机一致。文件集合双向差集为空，无非 mp4、隐藏项或零字节文件。
- 负对照将清单首条哈希换成 64 个零，得到 `match=1632`、`mismatch=1`，退出 1；使用原清单 `match=1633`，退出 0。
- 首／中／末各抽一条 `ffprobe` 检查可读性，不作帧对应证明：

| 文件 | 时长（秒） | 画幅 | 读帧 |
| --- | ---: | --- | --- |
| `video_0001_pre_01.mp4` | 2.000000 | 222×296 | 60/60 |
| `video_0061_pre_11.mp4` | 20.000000 | 432×576 | 600/600 |
| `video_0110_post_03.mp4` | 2.080000 | 192×256 | 52/52 |

## 旧批次归档与删除条件

下列 4 个文件合计 32,577,981 B，已移至训练机仓库外 `~/pi-workspace-backup/tensile-20261120/sub_video-retired-20261108/`：

| 原路径 | 字节数（B） |
| --- | ---: |
| `data/sub_video/manifest.json` | 10,511,341 |
| `data/sub_video/summary.json` | 4,820 |
| `data/sub_video-plan/manifest.json` | 22,057,123 |
| `data/sub_video-plan/summary.json` | 4,697 |

新批次生成、按 runbook §5.1 回传本机、全量哈希核对均已完成（1,633/1,633）。「正式准备开审」以本批清单入 Git 的 PR 合并为准；PR #2 已合并，删除条件达成，上表 4 个文件（合计 32,577,981 B）的暂存副本已于 2026-11-20 删除，删前逐个核对 sha256，删除后无法恢复。过程与各文件哈希见[训练机同步与旧批次归档](2026-11-20-training-machine-sync-and-batch-archive.md) §8。

## 已完成与保留期

2026-11-20 已完成本次生成、审计和回传核对。本声明自「已完成」记录之日起保留 7 天，至 2026-11-27，期满可直接删除、不归档。此保留期不适用于旧批次暂存副本。

## 失效条件

媒体、清单或对照基准变动；下游需要帧对应或时间戳证据；生成规则、ROI 或工具链变化；批次发布或产出人工审核结论。任一条件发生时，本记录不再作为当前批次状态或相应证据的依据。
