# 帧对应抽帧取证 CLI（DEC-005）

本目录提供独立于 `script/subvideo_generation/` 与 `script/checks/` 的按次抽帧取证工具。
它严格消费 `five-label-input-record/3` JSONL 输入记录，按一次模型运行实际送入的 `frames[]` 逐帧回溯四级链路（`L3` 模型输入 → `L2` 子视频 → `L1` ROI → `L0` 原视频），并将机器可读的 `evidence_manifest.json`、人工查阅页 `index.md` 及可选的同刻 PNG 画面输出到 **Git 仓库之外** 的指定目录。

设计边界见[帧对应抽帧取证](../../docs/frame-correspondence-evidence.md)，决策依据见 [DEC-005](../../docs/decisions/0005-frame-correspondence-evidence.md)，四级谱系与映射方向契约见[输入记录](../../docs/eval/input-record.md)。

## 前置边界说明

- 本 CLI 采用 **记录驱动（record-driven）** 方式，直接锚定传入的 `five-label-input-record/3` 记录里 `frames[]` 实际列出的输入帧，不自行挑选断裂帧、首帧或末帧。
- 上游**「模型输入抽帧口径落纸」**仍为独立前置事项；待具体模型的抽帧规则确定并产出对应 `five-label-input-record/3` 记录后，本工具可直接消费该记录进行按次取证，无需改动子视频生成批次。

## 用法

```bash
# 提取四级对应元数据与同刻 PNG（输出目录必须在 Git 仓库外）
.venv/bin/python -m script.frame_correspondence \
  --input-records /path/to/input_records.jsonl \
  --output-dir /tmp/frame-correspondence-out \
  --extract-images

# 仅生成四级对应清单与人工索引，不解码视频（适合无本地视频媒体时核对链路）
.venv/bin/python -m script.frame_correspondence \
  --input-records /path/to/input_records.jsonl \
  --output-dir /tmp/frame-correspondence-out \
  --metadata-only

# 按片段或运行过滤，并绑定子视频/ROI 清单与媒体根目录
.venv/bin/python -m script.frame_correspondence \
  --input-records /path/to/input_records.jsonl \
  --output-dir /tmp/frame-correspondence-out \
  --clip-id video_0001_fracture_01 \
  --run-id run-20261124-01 \
  --subvideo-manifest data/sub_video/manifest.json \
  --roi-manifest data/roi/manifest.json \
  --media-root /path/to/media_root \
  --l3-frames-dir /path/to/extracted_l3_frames
```

### 常用参数

| 参数 | 说明 |
| --- | --- |
| `--input-records` | 必填，`five-label-input-record/3` JSONL 路径；旧 v2 schema 或遗留键名会被显式拒绝并返回非零退出码 |
| `--output-dir` | 必填，输出目录；必须在任何 Git 仓库/worktree 之外，否则直接拒绝执行 |
| `--clip-id` | 可选（可重复），按 `candidate_id` / `clip_id` 过滤 |
| `--run-id` | 可选（可重复），按记录内 `run_id` 过滤 |
| `--subvideo-manifest` | 可选，绑定子视频清单以核对 `clip_sha256` 并继承批次 `audit_tier` / `no_frame_level_replay` 限制 |
| `--roi-manifest` | 可选，绑定 ROI 清单以核对 `l1` 摘要及记录 `recipe_hash` |
| `--media-root` | 可选，跨机或相对路径场景下定位 L0/L1/L2/L3 媒体的根目录 |
| `--l3-frames-dir` | 可选，存放已落盘的 L3 模型输入 PNG 的根目录（优先匹配运行级子目录 `<dir>/<run_id>/<candidate_id>/<image>` 或帧级 `image_sha256`；同候选跨次歧义或缺失时标记跳过，绝不用 L2 顶替） |
| `--extract-images` / `--metadata-only` | 互斥模式；默认 `--extract-images`，`--metadata-only` 仅落盘元数据清单与 `index.md` |
| `--backend` | 抽帧后端：`auto`（默认，优先 `ffmpeg`，不可用时退回 `opencv` 顺序解码）、`ffmpeg`、`opencv` |

## 输出结构

```text
<output-dir>/
  run_index.json
  <run-slug>/
    <candidate-id>/
      evidence_manifest.json
      index.md
      frames/                      # 仅实际抽取/复制出图片时创建
        order_000_L3_model_input.png
        order_000_L2_clip_f000000.png
        order_000_L1_roi_f000973.png
        order_000_L0_orig_f000973.png
```

## 契约与证明强度红线（DEC-005）

1. **严格校验 `five-label-input-record/3`**：复用 `script/five_label_eval/frames.py` 的 `read_records` 与 `verify_lineage`，拒绝 `five-label-input-record/2`、无 schema 记录及遗留/反向映射键（`media_to_clip`、`source_to_media`、`roi_to_source`、`original_to_roi`、`source_frame_index` 等）。
2. **严格遵守映射方向**：`clip_to_model_input`（`L2->L3`）、`clip_to_roi`（`L2->L1`）、`roi_to_original`（`L1->L0`）。
3. **只做人工视觉证据，不做自动判定**：代码中不做任何像素比对、不做相似度打分、不输出“像不像”或“已验证帧对应”结论；每份 `evidence_manifest.json` 固定写入 `proof_strength: "manual_visual_evidence_only"` 与 `replaces_full_receipt: false`。
4. **保留批次审计限制**：当记录或子视频清单处于 `basic` / `none` 审计层级（或记录为 `unverified`）时，显式透传 `audit_tier` 与 `no_frame_level_replay: true`。
5. **缺图不伪造**：任一层视频文件缺失、解码失败、`unverified` 导致帧号为空、或 L3 原图缺失时，均记录到 `extraction_summary.skipped_layers`，绝不伪造或以其他层级画面顶替。

## 测试

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q script/frame_correspondence/tests
```

**失效条件：** 当 `five-label-input-record/3` 的映射字段命名或方向契约变更、上游模型输入抽帧口径导致记录 schema 升级、或 DEC-005 证明强度与输出边界调整时，本说明与对应实现须同步更新并重新核对。
