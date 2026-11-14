# 测评链路迁移规格：本地 Mac → 远程训练机

**状态：** 本文是测评链路从本地 Mac 迁到远程训练机 `dell-Precision-3660` 的执行规格，覆盖目录、路径配置、backend 接口、迁移点判据、迁移包、迁移步骤、风险回滚和边界。本文只写规格，不含代码；代码与配置由后续步骤落地。**v2 修正：** 判据④改为引用输入契约 §1 的四类边界用例；补工作树与分支名对照。

**失效条件：** 出现下列任一情况时本文失效、须重写：① 第 5 章的 profile 被代码内置配置或环境变量完全替代；② 训练机不再是唯一 GPU 执行环境；③ 第 3 章旧批次被重新授权用作测评输入；④ 本地目录布局（第 4 章）再次变更。

**事实标注约定：** 文中「实测于 2026-11-14，迁移前须复核」表示该段数字来自本地或训练机实测采样，迁移执行前必须重新核对，不得直接当作本轮测评结果。

## 1. 背景与边界

| 侧 | 承担 | 不承担 |
| --- | --- | --- |
| 本地 Mac | 链路梳理、输入与清单元数据、fake backend 切片验证、报告模板、判据与文档 | 真实模型推理、真实指标、任何可对外引用的测评结果 |
| 远程训练机 | 真实权重加载与推理、真实指标与日志 | 数据规则设计、契约与 prompt 定义（只从代码读取，不就地改写） |

**环境事实（实测于 2026-11-14，迁移前须复核）：**

| 项 | 本地 Mac | 训练机 `dell-Precision-3660` |
| --- | --- | --- |
| 硬件 | Apple M4，arm64，无 NVIDIA GPU | Linux x86_64，32 核，125G 内存，单卡 RTX 4090 24.5GB，驱动 580.159，CUDA 13.0 |
| Python 依赖 | `.venv` 无 torch/transformers/vllm；仅 cv2 4.13.0.92、numpy 2.4.6 | conda 在 `~/miniconda3`（不在 PATH）；`agent`/`cpm45`/`mvllm2` 均 Python 3.11 + torch 2.5.1+cu124 + transformers 4.56.1 + peft/trl/accelerate/bitsandbytes/av/cv2；缺 vllm/flash_attn/qwen_vl_utils/timm/decord |
| ffmpeg | 系统 ffmpeg/ffprobe 8.1.1（`/opt/homebrew/bin`） | 随系统/conda 提供，版本待第 10 步复核 |
| 磁盘 | — | `/home` 可用 543G，`/data` 可用 3.4T |

**结论：两边必然不一致，不追求一致，只追求「同一份代码 + 各自一份配置」。**

## 2. 迁移原则

| 编号 | 原则 | 落地要求 |
| --- | --- | --- |
| P1 | 与模型无关的全部在 Mac 做完并验证，必须 GPU 的压成一个 backend 接口 | 输入构造、清单、抽帧记录、报告骨架、判据全部在 Mac 完成并通过；GPU 相关只经由第 6 章接口进入，不散落在脚本里 |
| P2 | 以本地新目录布局为准，不兼容远程即将废弃的 `data/derived` 结构 | 代码只认 `data/videos`、`data/roi/videos`、`data/sub_video/videos`；不写 `data/derived` 的兼容分支或迁移脚本 |
| P3 | 本地产出永不作为测评结果 | 本地输出只用于验证链路；`model_id=fake` 的产出禁止进入任何指标表或跨模型比较（第 7 章） |

## 3. 旧批次退流声明

> **待修订（2026-11-14）：** 迁移方式已变更，本节待按用户最新决定重写。（子视频可能本就在训练机生成，而非需从本机传输。）

训练机 `data/derived/subvideos` 下两个批次属历史批次、已用于训练，新链路一律不读。

**批次事实（实测于 2026-11-14，迁移前须复核）：**

| 批次目录 | 数量 | 状态 | 新链路处理 |
| --- | --- | --- | --- |
| `candidate-plan-ce36b9226be5` | 1617 | 历史批次，已用于训练 | 不读；原文件保留不删；不得作为测评输入 |
| `candidate-plan-v41exp-c99cd2894bb0` | 410 | 历史批次，已用于训练 | 不读；原文件保留不删；不得作为测评输入 |
| 当前批次（本地 `data/sub_video/videos`） | 1621 | 待迁移与人工审核 | 唯一允许的测评输入 |

理由：① 两个旧批次数量之和（1617+410）与当前 1621 批次都不一致，无法对应同一份片段集；② 两者来自旧划分，与当前固定测试集归属不同。

## 4. 目录约定

> **待修订（2026-11-14）：** 迁移方式已变更，本节待按用户最新决定重写。（项目名与目录位置已变更。）

以本地为准。训练机新建同名结构；旧 `data/source`、`data/derived` 原样保留为历史，不改写、不删除、不被代码引用。

**数据量事实（实测于 2026-11-14，迁移前须复核）：**

| 角色 | 本地（基准） | 训练机新建 | 训练机旧（历史保留） |
| --- | --- | --- | --- |
| 源视频 | `data/videos` 110 个 mp4，6.2G | `data/videos` | `data/source/videos` 110 个，6.3G |
| ROI | `data/roi/videos` 110 个，143M | `data/roi/videos` | `data/derived/roi_videos` 110 个，145M |
| 子视频 | `data/sub_video/videos` 1621 个，186M | `data/sub_video/videos` | `data/derived/subvideos` 1617+410 个，203M |

## 5. 路径配置化要求

- 所有路径从一份配置文件解析（建议 `config/paths.yaml`，本轮不创建），代码内禁止出现字面路径。
- 至少两个 profile：`mac`、`gpu-train`；切换只改 `--profile mac|gpu-train`，**代码零改动**。
- 配置文件入库（随代码分支走），不含任何权重或媒体；缺失键直接报错退出，不回落默认路径。
- `gpu-train` profile 中的相对路径以仓库根为解析基准，绝对路径原样使用。

**参数化的路径项清单（8 项）：**

| # | 配置键 | 含义 | `mac` | `gpu-train` |
| --- | --- | --- | --- | --- |
| 1 | `source_videos` | 源视频目录 | `data/videos` | `data/videos` |
| 2 | `roi_videos` | ROI 视频目录 | `data/roi/videos` | `data/roi/videos` |
| 3 | `sub_videos` | 子视频目录 | `data/sub_video/videos` | `data/sub_video/videos` |
| 4 | `manifest` | 片段清单 | `data/sub_video/manifest.json` | `data/sub_video/manifest.json` |
| 5 | `review_records` | 审核记录目录 | `data/subvideo-review/` | `data/subvideo-review/` |
| 6 | `prompt_dir` | prompt 目录（`prompt_registry/` 各版本 + `pipeline/prompt_control/active_prompt.yaml`） | 仓库内相对路径 | 仓库内相对路径 |
| 7 | `output_dir` | 输出目录 | `evaluations/local/` | `/home/liuyang/文档/mVllm_2/evaluations/gpu-train/` |
| 8 | `score_output` | 评分输出 | `evaluations/local/scores/` | `/home/liuyang/文档/mVllm_2/evaluations/gpu-train/scores/` |

第 6 项指向的 prompt 基础设施（`versioning/prompts.py` 的 `load_prompt`/`freeze_prompt`/`verify_frozen_prompt`、`prompt_registry/{initial-v1,concise-evidence-json-v1,-v2}`、`pipeline/contracts/`）随 W4/W3/W2 合并进入本地，路径只从本表解析（实测于 2026-11-14，迁移前须复核）。`evaluations/` 已在 `.gitignore` 排除，输出不入库。

## 6. backend 接口定义

`backend ∈ {fake, transformers, http}`，由配置选择，其余代码不知道 backend 存在。

| backend | 实现位置 | 作用 | 本轮状态 |
| --- | --- | --- | --- |
| `fake` | 本地 Mac 实现，训练机冒烟复用同一实现 | 不加载权重，按确定性规则产出结果，用于跑通链路与判据 ①③④ | 必做 |
| `transformers` | 训练机 | 真实权重推理（MiniCPM-V-4.5 完整 17G，两处副本；实测于 2026-11-14，迁移前须复核） | 必做 |
| `http` | 预留 | 指向外部服务 | 不实现 |

**输入字段（每条样本一个请求）：** `sample_id`、`video_path`、`frame_indices`（三帧号）、`anchor`（事件锚点）、`size_bucket`、`prompt_id`、`contract_id`、`model_id`、`backend`、`backend_config`。

**输出字段：** `sample_id`、`model_id`、`backend`、`status`、`raw_text`、`parsed`（五类标签逐项）、`frame_refs`（抽帧可还原记录）、`latency_ms`、`error`。

**失败到 `status` 的映射：**

| 情况 | `status` | 处理要求 |
| --- | --- | --- |
| 正常返回且字段齐全、可解析 | `ok` | 记录 `raw_text`、`parsed`、`frame_refs` |
| 返回内容无法解析或字段缺失/越界 | `invalid_output` | 保留 `raw_text` 原文，不补默认值、不重试掩盖 |
| 加载或推理抛异常、显存不足、进程超时 | `runtime_error` | 记录异常类型与消息到 `error`，该样本记失败，不剔除样本 |
| 前置条件不满足（片段缺失、视频不可解码、`prompt_id` 未冻结） | `skipped` | 记录跳过原因，计入分母统计口径 |

**多模型区分：** 靠 `model_id` + 加载配置（路径、精度、adapter）区分基座、微调 merged 与 adapter 变体；接口不变，新增模型只加配置项。

## 7. 本地护栏

- `fake` backend 的 `model_id` 固定为字符串 `fake`，不可配置为任何真实模型名。
- 本地与远程输出目录物理分离（`evaluations/local/` 与训练机 `evaluations/gpu-train/`），不共享、不同步、不互相覆盖；训练机 fake 冒烟另写 `evaluations/gpu-train/_smoke/`，不并入正式输出目录。
- 报告生成在写入任何跨模型比较前校验 `model_id`：命中 `fake` 即报错退出，`fake` 结果只允许出现在链路验证报告里。
- 理由：防止把本地假数据当结果，防止假结果沿目录同步或复制粘贴进入真实测评结论。

## 8. 迁移点判据

恰好 7 条，全部满足才算迁移点打通：

- [ ] ① 假模型切片跑通并出 `report.md`（`model_id=fake`，链路从清单到报告无人工介入）。
- [ ] ② 抽帧记录可还原：三帧号 + 事件锚点 + `size_bucket` 齐全，按记录可重放取到同样三帧。
- [ ] ③ 同一输入重复运行结果可复现（`fake` 逐字节一致；`transformers` 在温度与采样配置固定下一致）。
- [ ] ④ 四类边界用例（缺项→`missing`、字面量错→`invalid`、跨字段冲突→冲突计数 +1、代码围栏→`strict_format_valid=False`）逐项判定与预期一致；用例定义见 `docs/eval-input-contract.md` §1（该文件位于分支 `feat/eval-input-contract`，合并入主线后引用生效；本分支单独检出时该路径不存在，属预期）。触发条件与判定口径不得临时改写。
- [ ] ⑤ 契约与 prompt 冻结后产出稳定 `prompt_id`（重复冻结结果一致，可校验）。
- [ ] ⑥ 清单转换对 1621 条全部通过（无丢失、无新增、字段无空值）。
- [ ] ⑦ 人审 B0 完成并留档。

## 9. 迁移包清单

> **待修订（2026-11-14）：** 迁移方式已变更，本节待按用户最新决定重写。（项目名与目录位置已变更；子视频清单不再默认为必传。）

**媒体数量事实（实测于 2026-11-14，迁移前须复核）：** 子视频 1621 个 186M、源视频 110 个 6.2G、ROI 110 个 143M。

| 包 | 内容 | 传输方式 | 校验方式 |
| --- | --- | --- | --- |
| 代码 | git 分支；合并顺序 **W4 → W3 → W2 → W5**（分支名与提交在合并时核对） | 授权后 push/pull，或 `git bundle` | 记录四分支提交 SHA，训练机 `git rev-parse` 逐个比对 |
| 配置 | `mac`、`gpu-train` 两份 profile + 配置文件 | 随代码入库 | 与代码同 SHA，`--profile` 可解析 |
| 媒体：子视频 | 1621 个片段 186M（**必传**） | `rsync` 或归档切分 | `sha256` 清单逐项比对，数量必须为 1621 |
| 媒体：源视频/ROI | 110 个 6.2G、110 个 143M（视需要，若训练机需重放抽帧则必传） | `rsync` | `sha256` 清单逐项比对 |
| 文档 | 本文 + 相关口径文档（契约、prompt、评价设计） | 随代码入库 | 与代码同 SHA |

**W 编号对照（工作树目录 ↔ 分支名）：** W4=`TensileAgent-wt-input-contract` ↔ `feat/eval-input-contract`、W3=`TensileAgent-wt-base-eval` ↔ `feat/base-model-eval-plan`、W2=`TensileAgent-wt-eval-design` ↔ `feat/label-position-calibration`、W5=`TensileAgent-wt-migration-plan` ↔ `feat/eval-migration-plan`；合并顺序 W4 → W3 → W2 → W5 不变，各分支提交 SHA 在合并时核对。

校验统一用 `sha256` 清单（相对路径 + 摘要 + 大小），清单本身随代码入库，作为第 10 步的前置输入。

## 10. 迁移步骤

> **待修订（2026-11-14）：** 迁移方式已变更，本节待按用户最新决定重写。（项目名与目录位置已变更；子视频可能本就在训练机生成。）

按序执行，前一步未通过不进入下一步；每步留下可核对的输出。

1. **建目录**：在训练机仓库内新建 `data/videos`、`data/roi/videos`、`data/sub_video/videos`、`data/subvideo-review/`、`evaluations/gpu-train/`；`data/source`、`data/derived` 保持原样不动。
2. **传媒体**：先传子视频 1621 个片段（必传）；源视频与 ROI 按第 9 章判断是否需要。
3. **校验摘要**：按 `sha256` 清单逐项比对；数量、路径、摘要任一不一致即停。
4. **拉代码**：按 W4 → W3 → W2 → W5 顺序合并/拉取，核对四分支提交 SHA 与本地一致。
5. **装配置**：放入 `gpu-train` profile，用配置打印命令确认 8 项路径都指向新建目录、无一项落在 `data/derived`。
6. **fake backend 冒烟（CPU）**：在训练机上跑 `backend=fake` 小批，确认清单读取、抽帧记录、报告生成可用（只验证环境，不作为结果）；冒烟输出写入隔离目录 `evaluations/gpu-train/_smoke/`，该目录任何产物都不进入报告与跨模型比较。
7. **切 transformers backend**：激活 conda `mvllm2`（Python 3.11），确认 torch 2.5.1+cu124 可见 GPU（实测于 2026-11-14，迁移前须复核），先测单样本加载与显存峰值。
8. **单批小样本真跑**：取小批真实片段跑通 `transformers`，产出 `report.md` 与评分输出；记录 `status` 分布与显存峰值，通过后再扩大批次。

## 11. 风险与回滚

**风险事实（实测于 2026-11-14，迁移前须复核）：** 该卡被非本项目进程（分子动力学作业）占用约 9.6GB，剩余约 14.9GB；bf16 全量加载约需 16.5G。

| 风险 | 触发条件 | 影响 | 处置 |
| --- | --- | --- | --- |
| 显存不足 | bf16 需约 16.5G vs 剩余约 14.9G | 加载失败或推理 OOM，`status=runtime_error` | 先与占用方协调释放；仍不足则降批（单样本）、缩短帧数或 4bit 量化，并记录配置变更 |
| GPU 被无关作业占用 | 分子动力学作业或其他进程抢卡 | 吞吐下降、OOM 概率上升 | 运行前查占用并记录；不与无关作业争抢，跑前跑后各记一次显存快照 |
| Python 版本漂移 | 本地与训练机版本不一致 | 语法/依赖行为差异，复现性破坏 | 两边固定 Python 3.11；训练机用 conda `mvllm2`，不混用 `agent`/`cpm45` |
| 误读历史目录 | 代码残留 `data/derived` 引用 | 读到旧批次，结果失效 | 第 10 步第 5 项校验；判据 ⑥ 覆盖清单来源 |
| 传输不完整 | 1621 片段缺失或截断 | 分母错、结论偏差 | 第 10 步第 3 项 `sha256` 校验为硬门 |

**回滚方式：** 只切配置、不动目录——把 `--profile` 切回 `mac` 或恢复上一版 profile 文件；历史目录（`data/source`、`data/derived`）与既有输出一律不删不覆盖，回滚不涉及数据搬迁。代码回滚用 W5/W2/W3/W4 已记录的提交 SHA。

## 12. 不做什么

- 不迁移 `data/derived`（含两个历史批次），不建兼容分支、不写转换脚本。
- 不迁移 `.venv`，训练机依赖由 conda 环境提供。
- 不复用旧 v4.1 微调契约（四字段旧契约，本轮不可用）与旧 v4.1 微调权重（merged 17G、adapter 440M；实测于 2026-11-14，迁移前须复核）。
- 不在训练机上改造现有 `main`（HEAD `316a197`，实测于 2026-11-14，迁移前须复核）的历史目录结构，历史原样保留。
- 不把本地 `fake` 产出当测评结果，不在 Mac 上做任何真实指标口径的结论。
- 不实现 `http` backend（本轮只保留枚举位）。
