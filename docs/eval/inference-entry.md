# 推理入口：CLI · 身份字段 · 三态 · backend 边界 · 旧实现借鉴

**失效条件：** `script/five_label_eval/infer.py` 的参数、退出码或校验改变；`http` backend 落地或 backend 列表改变；身份字段口径或三态触发条件改变；旧实现借鉴所引 `mVllm_2` 行号随其重构漂移。以上任一发生，本文的接口规格与借鉴条目都须重新核对。

## 1. 入口现状

| 项 | 现状 |
| --- | --- |
| 模块 | `script/five_label_eval/infer.py` |
| 文件位置 | 已随提交 `2baf363` 合入本分支 `feat/tensileagent-finetune`，本工作树内可直接读取 |
| 实际入口 | `main(argv=None) -> int`（74 行），无名为 `infer` 的函数 |
| 退出码 | 0 成功；2 输入身份或文件错误（`InputError`／`OSError`／`UnicodeError`／`NotImplementedError` 统一返回 2，116 行） |

上述「行」与 §2 参数行号均指本分支 `script/five_label_eval/infer.py` 的当前内容。

**接口契约（已落地）**：入口即 `main(argv=None) -> int`（74 行），全部输入走 §2 的 CLI 参数，代码里没有名为 `infer` 的函数、也没有 `infer(manifest_path, ...)` 这类关键字签名。实现与验收以 §2 的 CLI 为对齐基准，调用方不得按函数签名传参。

## 2. CLI 参数表（行号指 `script/five_label_eval/infer.py`）

| 参数 | 必填 | 含义 | 行号 |
| --- | --- | --- | --- |
| `--manifest` | 是 | 评分用清单 JSON，请求按它绑定候选身份 | 76 |
| `--candidate-ids` | 否 | 候选 ID 的 JSON 字符串数组文件，非空、无重复；给定时按它定记录顺序 | 77 |
| `--profile` | 否 | 路径配置；仅在未给 `--input-config` 时用来推出默认记录路径 | 78 |
| `--model-id` | 否（默认 `fake`） | 权重身份；`fake` backend 只接受 `fake` | 79、89 |
| `--run-id` | 是 | 批次身份 | 80 |
| `--prompt-file` | 是 | prompt 正文文件；本切片只用其身份（`prompt_id`） | 81 |
| `--input-config` | 否 | 抽帧记录 JSONL；缺省取 profile 的 `output_dir/records.jsonl` | 82 |
| `--output` | 是 | 新 `predictions.jsonl`，**独占创建、不覆盖** | 83 |
| `--backend` | 否（默认 `fake`） | `choices=("fake", "transformers")`；**`http` 拟增，当前未实现** | 84 |

注意：`--backend` 只有两个已声明取值，不要按三选实现或验收；`http` 尚无参数、无代码。

## 3. 输入与输出

| 方向 | 内容 |
| --- | --- |
| 输入 1 | `--manifest`：清单顶层 `manifest_version` + `samples[]`，每 sample 带 `IDENTITY`（`manifest_sha256/candidate_id/clip_sha256/source_id/source_type`） |
| 输入 2 | `--input-config`：每个候选一条输入记录（结构见 `docs/eval/input-record.md`）；记录中的 `clip_sha256`／`record_schema`／`manifest_sha256` 必须与清单一致，否则入口拒绝 |
| 输入 3 | `--prompt-file`：正文文本；本切片只取其 `prompt@sha256:` 身份，不把正文发出去 |
| 输出 | `predictions.jsonl`，每候选每批一行，字段与 `score.py` 对齐（见 `docs/eval/output-contract.md` §3） |

## 4. 身份字段填写口径

| 字段 | 口径 | 谁产生 |
| --- | --- | --- |
| `model_id` | 基础权重 + adapter／合并版本 + 权重摘要；不得只写模型名 | 出批次时人工确认并写死 |
| `prompt_id` | `prompt@sha256:<正文文件字节 sha256>`，由 `load_prompt` 计算，不手填 | 入口按 `--prompt-file` 计算 |
| `run_id` | 批次身份；一次评测一个 `run_id`，重试必须换新值 | 发起方指定 |
| `input_id` | 该条记录所描述那份媒体的输入配置身份摘要（抽帧／裁剪／缩放参数 + 选中帧清单摘要 + 该媒体 sha256），**单值** | 输入记录侧产生，入口透传 |
| `request_id` | 每次推理调用唯一；同批内不得重复 | 入口按 `run_id/候选` 生成（当前形态） |
| `clip_sha256` | 清单该候选 `output.sha256` | 清单侧，入口校验一致 |
| `manifest_sha256` | 评分清单文件字节 sha256；与输入记录里引用的 `data/sub_video/manifest.json` 摘要是两份不同文件，不得混用 | 清单侧 |

`source_type` ∈ `real|virtual`：清单 1621 条候选与 110 条来源**都没有该字段**，审核工作台按 `real` 回退（`script/subvideo_review/server.py:213`），因此清单必须显式补该字段，否则虚拟候选会被静默计入 `real` 组。

## 5. 三态与 `raw_output`

| `status` | 触发条件 | `raw_output` | 评分器后续行为 |
| --- | --- | --- | --- |
| `request_failed` | 请求已发出但返回错误、空响应或不可解析的传输失败 | `null` | 不提取：11 个叶字段直接被赋予同名状态（324–327 行的 `else` 分支），不算 `missing` 也不算 `invalid` |
| `timeout` | 超过设定时限未返回（超时预算须可执行，见 §7） | `null` | 同上 |
| `unprocessed` | 本轮未发出请求：不在候选列表、被跳过、批次中断 | `null` | 同上；清单里有、文件里没有该候选时也按 `unprocessed` 计（324–327 行） |

四值全集即 `STATUS`（`score.py` 23 行）：`success`／`request_failed`／`timeout`／`unprocessed`；`success` 之外的任何状态都不尝试从 `raw_output` 解析。**失败行必须显式写出**，留空（不出现该行）在评分上等价于 `unprocessed`，但会丢失跳过原因。

## 6. 重试必须另起批次

- 新 `run_id`、独立的 `predictions.jsonl`、独立评分；不得在原文件追加或改写。
- 原因：`score.py` 要求一批只有一个 `(run_id, model_id, prompt_id)`（288–291 行），且同一候选在批内出现第二行直接 `InputError`（295–296 行）。
- 重试结果与原批次**不得合并成一个指标**；需要比较时只作同样本配对展示，并各自标出 `run_id` 与 `input_id`。

## 7. 旧实现借鉴（`mVllm_2`，只读参考）

| 事实 | 位置 |
| --- | --- |
| `torch_dtype=bfloat16`，无 bf16 时退 `"auto"`；`trust_remote_code=True`、`device_map="auto"`、`low_cpu_mem_usage=True` | `finetune/validation/model_runtime.py:68`、`81`、`83`、`84` |
| 可选 4-bit 量化：`BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, ...)`，跳过 `resampler` 模块（`FOUR_BIT_SKIP_MODULES = ("resampler",)`，22 行） | 同文件 71–78 |
| processor 帧数必须为 8：调用 `configure_processor_max_frames(processor)`，`max_frames != 8` 时抛 `ValueError("MiniCPM-V contract requires max_frames=8")` | `pipeline/preprocessing/minicpm_preprocessor.py:93`、`101–102`；调用点 `finetune/validation/model_runtime.py:64` |
| `VIDEO_MAX_FRAMES = 8`、`VIDEO_SLICE_MAX_NUMS = 2`、`INFERENCE_TIMEOUT_SECONDS = 600.0` | `finetune/validation/constants.py:36`、`48`、`50` |
| 超时用 POSIX `SIGALRM` + `signal.setitimer(ITIMER_REAL)`；非主线程或缺 `SIGALRM` 时 fail-closed 抛 `RuntimeError`，不静默忽略预算；超时抛 `InferenceTimeoutError`；不改动机器可重试 | `finetune/validation/model_runtime.py:192–212` |
| 旁路证据 1：数据构建期记录 `frame_artifacts`（含 path／sha256／size） | `versioning/data_pipeline.py:1432` |
| 旁路证据 2：离线诊断脚本 `export_review_frames.py` 产出 `review_frames_manifest.json` | `pipeline/scripts/diagnostics/SCRIPTS.md:26` |

**两条由上述事实推出的硬结论：**

1. **帧数不是自由参数**。`max_frames` 被 processor 硬性要求为 8，单请求帧数不可作为可调项。若把「单请求帧数」写进 `input_id`，则每调整一次就会换一批 `input_id`，历史批次无法比较；帧数只允许通过 processor 侧契约变更（另立 `input_id` 版本）来改。
2. **旧实现缺失、本轮必须补的三样**：逐帧**帧号**、每份媒体的**实际像素尺寸**、**视频内容摘要**。旧实现只留了旁路产物，不足以事后回答「模型看到的是哪几帧」。

## 8. backend 可插拔边界

| backend | 状态 | 职责 | 边界 |
| --- | --- | --- | --- |
| `fake` | **唯一已实现**（`infer.py` 的 `plan_predictions`） | 链路自检：按类别轮转生成合法／非法输出，验证清单绑定、身份透传、每候选一行、文件不覆盖 | 不产生任何真实判读结论；不得用于评测结论 |
| `transformers` | CLI 已声明，本切片抛 `NotImplementedError`（88 行）；本机权重不可用，属训练机侧 | 本地加载权重逐条推理，产出 `raw_output` 原文 | 只在训练机侧执行；本机不得声称已跑通 |
| `http` | **拟增，当前未实现** | 远端服务推理，按 HTTP 结果映射三态 | 尚无参数、无代码、无超时实现；不得按已支持三选验收 |

不变项：三个 backend 共用同一份身份字段口径、同一份输出字段与三态语义；切换 backend 不改变 `predictions.jsonl` 的字段与校验。
