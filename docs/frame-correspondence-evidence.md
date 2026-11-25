# 帧对应抽帧取证

## 定位与边界

抽帧取证是独立环节，不属于 `subvideo_generation`，也不属于 `checks`。
设计已定，独立取证 `CLI` 已于 2026-11-24 随 PR #21 落地于 `script/frame_correspondence/`（用法、参数与红线见 [script/frame_correspondence/README.md](../script/frame_correspondence/README.md)），尚未在真实模型运行产物上执行。
该取证独立于子视频生成流程，不需要重新生成当前 1,633 条批次，待实现后按需对目标运行抽取即可。

## 取证锚点

锚点是一次模型运行实际输入的那组帧，例如该次请求输入的 8 帧，而不是重新从片段挑选的代表帧。
不以标注的断裂帧为锚点，也不以视频首帧或末帧为锚点。

## 四级链路与记录项

从 `L3` 模型输入帧回溯到 `L2` 子视频、`L1` ROI 和 `L0` 原视频。
对每个输入帧，各级分别记录该级帧号、时间戳和媒体摘要，并保留对应同一时刻的画面。

| 层级 | 须保留的同刻画面 |
| --- | --- |
| `L3` 模型输入 | 该次运行实际送入模型的帧 |
| `L2` 子视频 | 输入记录所指的片段解码帧 |
| `L1` ROI | 经片段帧号映射定位的 ROI 帧 |
| `L0` 原视频 | 经 ROI 帧号映射定位的原始画面 |

回溯顺序不等于节点的映射方向，读取一律以[输入记录 §10 的方向表](eval/input-record.md)为准。
`clip_to_model_input` 描述 `L2 → L3` 的取帧规则，`clip_to_roi` 为 `L2 → L1`，`roi_to_original` 为 `L1 → L0`（`five-label-input-record/3` 已于 2026-11-24 替换旧 v2 键名并显式拒绝旧记录，见 `DF-052`）。

## 取证对象与产物

按「一次模型运行的输入帧记录 + 片段身份（清单映射）+ 各级媒体摘要」绑定证据。
这是按次取证，不按批次取证；即使片段来自同一批次，不同次运行也是不同取证对象。
只把对应关系与同刻画面落盘供人工回溯；产物的存放与媒体遵循同一规则，不入 Git。

## 证明强度与限制

不做像素比对，不做自动相似度判定，也不让 Agent 判「像不像」。
抽帧取证**不等于「帧级重放通过」**；
`basic`／`none` 批次的 `no_frame_level_replay` 等限制**继续有效**（见[子视频生成逻辑 §8](subvideo-current-logic.md)与 `DF-032` 的审计分层）。
`full` 收据（机器证明）与本次抽帧取证（人工可查证据）**互不替代**。
**不得**把有抽帧图说成「已验证帧对应」。

## 实现前置条件与失效条件

1. 模型输入抽帧口径已于 2026-11-25 拍板落纸（见 [DEC-006](decisions/0006-eval-frame-sampling-and-model-lineup.md)：采用方案 A `evenly_spaced_inclusive` 固定 8 帧、短片 `< 8` 帧 `fail_closed`、L3 PNG `resize: null`；待 `script/five_label_eval/frames.py` 完成代码对齐后即可产出对应记录供本 CLI 消费）。
2. 映射字段命名已定案并落地（见[待办](TODO.md)任务 7 `MAPPING-NODE-RENAME` 与 `DF-052`：`clip_to_model_input`／`clip_to_roi`／`roi_to_original`）。

**失效条件：** 前置条件、映射表、锚点定义或证明强度口径变化时，须重新核对本设计。
