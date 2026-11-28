# `script/five_label_sft`：双通道三折隔离 SFT 数据准备与 QLoRA 配置管线

**失效条件：** 当 `docs/decisions/0008-finetune-base-model-and-sft-recipe.md` 变更首轮主基座或 QLoRA 配方、`docs/eval/output-contract.md` / `script/five_label_eval/score.py` 变更输出契约（`five-label-score/3`）、`LlamaFactory` 子模块升级改变 `Qwen3VLPlugin` 缩放/占位符行为、或 `data/splits/three-fold/*.json` / `data/splits/dev-exclusions.json` 发生结构变更时，本模块的参数与守卫须同步复核。

---

## 1. 功能总览

本模块为 `Qwen3-VL-8B-Instruct` 五类标签 SFT 提供离线数据准备、长度/对齐预检与训练/评测配置生成，同时支持两条无损预抽 L3 PNG 通道：

| 通道 | 占位符与数据列 | 训练参数（RTX 4090 QLoRA） | 推理参数（`vLLM 0.34.0`） | 适用场景 |
| --- | --- | --- | --- | --- |
| `images` (`8f`) | `<image>*8 + "\n" + prompt`，`"images": [f0..f7]` | `image_max_pixels=1200000`, `image_min_pixels=65536`, `cutoff_len=8192` | `--max-model-len 8192` | `DEC-008 §3` 锁定 8 帧全分辨率黄金基线（实测峰值 `22,525 MiB`） |
| `video` (`8f`) | `<video>\n + prompt`，`"videos": [[f0..f7]]` | `video_max_pixels=1200000`, `video_min_pixels=256`, `video_fps=2.0`, `cutoff_len=8192` | `--max-model-len 8192` | 原生 `<video>` 8 帧无损预抽帧列表，比特级对齐 |
| `video` (`16f`) | `<video>\n + prompt`，`"videos": [[f0..f15]]` | `video_max_pixels=1200000`, `video_min_pixels=256`, `video_fps=2.0`, `cutoff_len=8192`，单帧面积守卫 `<= 865,000 px` | `--max-model-len 12288` | 原生 `<video>` 16 帧无损预抽帧列表（全量 1,299 `dev_clean` 最大 `804×1072 = 861,888 px` 零预缩放，4090 峰值 `22,643 MiB`；推理 `12288` 实测 `20,613 MiB` 原生覆盖封存测试最大画幅 `924×1232`） |

> **关键对齐与显存护栏**：
> 1. **不把 `system` 塞进 `messages[0]`**：`LlamaFactory` `Qwen3VLPlugin.process_messages`（`mm_plugin.py:2427`）使用 `video_metadata[idx]`；本模块固定生成 2 轮 `[{"role": "user", ...}, {"role": "assistant", ...}]`，与零样本评测 `five_label_v2.txt` 保持一致并避开 `IndexError`。
> 2. **防两段式缩放失配与 4090 OOM 守卫**：`video_max_pixels=1200000` 确保所有 `dev_clean`（`<= 804×1072`）零预缩放、与 `vLLM` 100% 比特级对齐（避免 `865,000` / `900,000` 等中间值 `int()` vs `floor()` 失配）；同时在 `preflight` / `build_dataset` 固化单帧面积守卫 `<= 865,000 px`（16f `<video>`），阻止未来若引入 `>= 924×1232` 开发源静默触发 RTX 4090 反向 OOM。推理侧 `vllm serve` 同步锁定 `--media-io-kwargs '{"video":{"num_frames":-1,"fps":2.0}}'` 与 `--mm-processor-kwargs '{"videos_kwargs":{"do_sample_frames":false,"cap_pixels_per_frame":false}}'`。
> 3. **短片策略**：全量 1,633 条实测 `min(total_frames) = 45`（0 条 `< 16` 帧），坚持 `DEC-006` `evenly_spaced_inclusive` + `fail_closed`（`total_frames < num_frames` 直接报错，且 `video` 通道强制偶数帧避免末帧静默复制）。
> 4. **双环境 `PATH` 隔离（`DEC-008 §2`）**：运行 `vlm-eval` 的 `vllm serve` 时必须使用纯系统 `PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin` 加绝对路径 `/home/liuyang/miniconda3/envs/vlm-eval/bin/vllm`，严禁混入 `vlm-sft/bin/ninja`。

---

## 2. 三折隔离与防泄漏红线（全部 fail-closed）

对任意目标折 $k \in \{0, 1, 2\}$，导出器强制执行以下检查，任一违约即中止且不写出任何文件：

1. **当前批次确认身份校验**：复用 `script/subvideo_review/server.py` 的 `ReviewApp` 与 `ReviewApp.matches`（校核 `revision_sha256`、`review_subject_sha256`、`manifest_sha256`、`clip_sha256`、`label_rules_sha256`、`split_identity_sha256`），仅纳入当前批次最新修订为 `confirmed` 的记录，自动跳过历史隔离记录与 `draft` / `question` / `returned` / 未审记录。
2. **DEC-007 排除守卫**：强制加载 `data/splits/dev-exclusions.json`，排除 `video_0006`、`video_0079` 及其 20 条子视频和 15 条隔离虚拟视频。
3. **零交集断言**：仅从 `fold_{k}_train.json` 扣除 `DEC-007` 后的 **58 个干净开发源**取样，并显式断言导出集与 `fold_{k}_val.json`、`test.json`、`eval-dev-v1 ∩ fold_{k}_val`、`eval-test-v1.json`、`dev-exclusions.json` 交集全为 `∅`。
4. **目标输出严格单 JSON 核验**：每条 `assistant` 目标串经 `script.five_label_eval.score.extract()` 实时校验，要求 100% `strict_format_valid == True`、`issues == []`、`conflicts == []`。
5. **L3 帧血缘与写保护（全 fail-closed）**：非 dry-run 正式导出**强制要求提供 `frames.py` 生成的 `--frames-manifest`（`records*.jsonl`）**，逐帧核验 `manifest_sha256`、`clip_sha256`、采样序与 PNG SHA-256；校验 `total_frames >= num_frames`（`fail_closed`，且 `video` 通道要求偶数帧）与 `cutoff_len` / 4090 单帧面积守卫；所有写盘操作均拒绝符号链接目标、拒绝保留产物撞名、拒绝写入受保护目录，覆写使用同目录临时文件原子替换。
6. **配置与数据包跨折互校**：`render_config.py` 默认强制校验 `--dataset-dir` 下的 `build_summary.json`、`dataset_info.json` 与数据集 JSON SHA-256，确认折号、通道、帧数与 `dataset_name` 完全一致且非 dry-run 产物，杜绝跨折配置错配（仅在跨机渲染远端路径模板时才可显式传 `--allow-remote-dataset-dir`）。

---

## 3. 常用命令

### 3.1 离线长度与短片预检（含未来 B3 全量开发集）

```bash
.venv/bin/python -m script.five_label_sft.preflight \
  --fold 0 --scope all_clean_dev --modality video --num-frames 16 --fail-on-lf-downscale
```

### 3.2 导出 Fold 0 SFT 数据集（训练机真实 L3 帧 / 本机 dry-run）

```bash
# 本机无 L3 PNG 时的只读 dry-run 核验
.venv/bin/python -m script.five_label_sft.build_dataset \
  --fold 0 --modality video --num-frames 16 \
  --output-dir /tmp/sft-fold0-video16f-dryrun \
  --allow-missing-frames-dry-run --fail-on-lf-downscale

# 训练机基于 frames.py 产出的 records_16f.jsonl 强校验导出
.venv/bin/python -m script.five_label_sft.build_dataset \
  --fold 0 --modality video --num-frames 16 \
  --frames-manifest /path/to/l3_16f/records_16f.jsonl \
  --frames-dir /path/to/l3_16f \
  --output-dir trains/sft-fold0-video16f/input \
  --fail-on-lf-downscale
```

### 3.3 生成 LlamaFactory QLoRA YAML 与配套 vLLM 评测命令（仅生成配置，不启动训练）

```bash
.venv/bin/python -m script.five_label_sft.render_config \
  --fold 0 --modality video --num-frames 16 \
  --dataset-dir trains/sft-fold0-video16f/input \
  --train-output-dir trains/sft-fold0-video16f/adapter \
  --output-yaml trains/sft-fold0-video16f/qlora_fold0_video16f.yaml
```
