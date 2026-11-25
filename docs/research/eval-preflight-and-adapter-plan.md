# 训练机评测前置只读体检清单与推理适配器规划

> **决策状态（2026-11-25）：阶段 0 决策项已拍板，见 [DEC-006](../decisions/0006-eval-frame-sampling-and-model-lineup.md)。** 8 帧抽帧口径（`evenly_spaced_inclusive` / 短片 `fail_closed` / L3 `resize: null`）、首轮第一梯队 3+1 基座名单、`MiniCPM-V-4.5` 首轮官方风格参数（并登记为后续对照/优化项）以及 `GLM-4.1V` 主榜原生格式罚分（不预埋解包分支）均已定案；下文 §2.2 训练机只读体检与 §3 代码适配规划按此口径推进。

**定位：**本文是基座模型测评落地前的工程实施专题文档，涵盖三项工程事项：（1）现有评测代码与输入契约的接口缺口核对；（2）训练机启动前可直接复制执行的严格静态只读体检清单（Pre-flight Runbook）；（3）供用户审批后实施的最小双后端（OpenAI-compatible `http` + 薄本地 `transformers`）推理适配器落地路线。8B/9B 模型选型横评另见 [vlm-8b-9b-model-comparison.md](vlm-8b-9b-model-comparison.md)，8 帧抽帧口径选型另见 [model-input-frame-sampling-options.md](model-input-frame-sampling-options.md)。

**调研日期：** 2026-11-24。

**基准与边界声明：**

- **仓内核对基线**：`feat/tensileagent-finetune` 提交 `07d9c8e6030f62ac604a186b777ab1b7dc280e42`（稀疏检出工作树，不含 `pipeline/`、`versioning/`）。
- **只规划、不改码、不启测**：本文不修改 `script/five_label_eval/` 或 `config/eval_paths.json`，不授权启动真实模型评测或训练。
- **证据分级纪律**：代码行号与关键文件 SHA-256 均为 `07d9c8e` 本机实读实算；训练机尚未现场核验项一律标注 **`待训练机实测核对`**，单条耗时估算一律标注 **`[推测/待训练机实测核对]`**。

---

## 1. 现状代码与契约缺口分析

本节逐项核对 `07d9c8e` 工作树中 [infer.py](../../script/five_label_eval/infer.py)、[frames.py](../../script/five_label_eval/frames.py)、[paths.py](../../script/five_label_eval/paths.py)、[eval_paths.json](../../config/eval_paths.json) 与 [inference-entry.md](../eval/inference-entry.md)、[input-record.md](../eval/input-record.md)、[output-contract.md](../eval/output-contract.md)、[prompt.md](../eval/prompt.md) 之间的接口缺口。

> 注：经实读核对，[inference-entry.md](../eval/inference-entry.md) §1–§2 引用 `infer.py` 行号（如 `main` 74 行、`--backend` 84 行）较当前工作树偏移 2 行（实际为 76 行、86 行）；下文均以 `07d9c8e` 实测行号为准。

### 1.1 `script/five_label_eval/infer.py` 与 `inference-entry.md` 缺口

| 维度 | 现状（`07d9c8e` 实读） | 契约/方案要求 | 缺口与影响 |
| --- | --- | --- | --- |
| `transformers` backend | `--backend` 在 `infer.py:86` 声明 `choices=("fake", "transformers")`，89–90 行直接 `raise NotImplementedError` | `DF-044` / `DEC-003` 第 9 条选定基座 `openbmb/MiniCPM-V-4_5` + `transformers` 加载 | 无模型加载、无处理器装配、无推理执行，无法运行 run A |
| `http` backend | CLI 未声明 `http`，无 `--endpoint`、`--api-model-name`、`--api-key-env`、`--timeout`、`--temperature`、`--max-tokens` 等参数 | [inference-entry.md](../eval/inference-entry.md) §8 规划 `http` 拟增；[agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md) §2.2 规划 OpenAI-compatible `POST /v1/chat/completions` | 无法对接 vLLM / SGLang 启动的 Qwen3-VL / InternVL3 / InternVL3.5 等多模型服务 |
| Prompt 正文传递 | `infer.py:97` 执行 `load_prompt(args.prompt_file)[1]`，丢弃正文、仅保留 `prompt_id` | [prompt.md](../eval/prompt.md) §3 要求送模型文本与算 `prompt_id` 字节为同一份原文（不 `strip`） | 真实 backend 必须消费 `load_prompt` 返回的 `(text, prompt_id)` 二元组 |
| L3 帧图路径解析 | `infer.py:98` 仅调用 `read_records(input_config)`；`records.jsonl` 中 `frames[].image` 只是裸文件名（如 `frame_001.png`，`frames.py:706`），记录内无 `--out-dir` 字段 | 真实推理需按 `display_order` 顺序读取对应 PNG 字节并送入模型 | 缺少 `--frames-dir`（或按 `records.jsonl` 父目录解析 + 文件存在性与逐帧 SHA-256 的 fail-closed 核对） |
| 推理前血缘复检 | `infer.py:98` 只 `read_records`，不调用 `verify_lineage`（仅拒绝旧 v2 schema 与遗留键名） | [input-record.md](../eval/input-record.md) §0 状态表 4 指出推理模式不重验 | 注意：`verify_lineage` 本身**只校记录 JSON 内部一致性、不重读磁盘视频媒体**；推理前除补上 `verify_lineage` 校记录外，还须独立核对 L3 PNG 盘面存在性与摘要 |
| 超时与三态映射 | `infer.py:67–72` 仅用 `CATEGORY_ORDER` 轮转伪造 `request_failed`/`timeout`；无真实超时控制与异常捕获 | [inference-entry.md](../eval/inference-entry.md) §5、§7 要求 600 s 超时（POSIX `SIGALRM`/`setitimer` 或可取消 HTTP 总 deadline）并显式落盘 `request_failed`/`timeout`/`unprocessed` + `"raw_output": null` | 缺少可执行超时守卫、单条异常隔离（单条 OOM/HTTP 错误不得打崩整批导致已跑结果丢失）及中断补齐 `unprocessed` 策略 |
| `model_id` 身份与防 `fake` 混入 | `infer.py:91–92` 仅在 `fake` 时强制 `--model-id fake`；非 `fake` 时无校验；跨模型报告拦截 `fake` 未实现（`DF-037`） | [inference-entry.md](../eval/inference-entry.md) §4 要求 `model_id` 含基础权重 + adapter/合并版本 + 权重摘要，不得只写模型名；`DF-037` 要求跨模型比较拦截 `fake` | 缺少 `model_id` 规范守卫与运行侧元信息落盘（记录推理引擎、解码参数、权重快照摘要与单条耗时） |
| 独占写与崩溃恢复 | `infer.py:112` 先全量构造列表再一次性 `open("x")` 写入 | [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §8.1 要求无中断崩溃且未处理数明确；[inference-entry.md](../eval/inference-entry.md) §6 禁止覆盖或原地追加 | 若 314 条评测在第 200 条崩溃，内存列表全部丢失；应采用启动即独占创建 `open("x")` + 逐条写入 `flush`，中断后换新 `run_id` 重跑 |

### 1.2 `script/five_label_eval/frames.py` 与 `config/eval_paths.json` 缺口

| 维度 | 现状（`07d9c8e` 实读） | 契约/决策要求 | 缺口与影响 |
| --- | --- | --- | --- |
| 默认抽帧数 | `frames.py:646` 与 `:887` 默认 `--clips-per-record 3` | `DF-044` / `DEC-003` 第 9 条定为**单请求 8 帧** | 默认 3 帧易误抽；待 [抽帧口径方案](model-input-frame-sampling-options.md) 拍板后统一对齐为 8 |
| L3 逐帧宽高与 PNG 摘要 | `_extract_frames`（`frames.py:632–643`）仅做 `select+showinfo`；`frames[]`（`:700–709`）**不含** `width`/`height` 与 PNG `sha256` | [input-record.md](../eval/input-record.md) §0 状态表 1/7 标为「实现较窄」 | 推理前无法直接从 `records.jsonl` 校验 L3 PNG 字节完整性 |
| `config/eval_paths.json` `gpu-train` | 9 个键全部为 `TODO_MIGRATION_FILL:<key>`（`eval_paths.json:15–26`）；`paths.py:20,58` 将其解析到 `/nonexistent/...` | 训练机运行评测前须核对并填入实际路径 | 当前在训练机调用 `--profile gpu-train` 会立即失败，须完成第 2 节核对后再更新 |
| Python 与依赖边界 | [pyproject.toml](../../pyproject.toml) 约束 `requires-python = ">=3.11,<3.12"`，核心依赖无 `torch`/`vllm`，开发依赖含 `httpx>=0.28.1` | 训练机 `agent` 环境为 Python 3.11.15（[training-machine-review-runbook.md](../training-machine-review-runbook.md) §2.1）；vLLM/PyTorch 可能在独立 conda 环境 | `http` backend 仅需 `httpx` 即可在 3.11 `agent` 环境中轻量运行，将重量级 GPU 依赖隔离在独立推理服务进程中；本地 `transformers` backend 须在目标 GPU 环境中执行 |

---

## 2. 训练机启动前资源与环境核对清单（Pre-flight Runbook）

> **硬红线：完成本节全部只读核对并把实测结果留存记录前，不得启动任何正式基座模型评测，也不得盲目填改 `config/eval_paths.json` 的 `gpu-train` 占位符。**

### 2.1 仓内已有训练机基线 vs 待现场核对项

| 核对类别 | 仓内已有记录（不可代替现场复核） | 本轮尚未核验（`待训练机实测核对`） |
| --- | --- | --- |
| 入口与工作区 | `ssh liuyang@100.70.83.68`（必须显式写用户名，主机名 `dell-Precision-3660` 不可省略用户名）；项目落点 `/home/liuyang/文档/TensileAgent-Finetune`（非 git 仓库），见 `DF-046` 与 [training-machine-review-runbook.md](../training-machine-review-runbook.md) §2 | 当前工作区 `script/five_label_eval/`、`docs/`、`data/sub_video/manifest.json`、`data/subvideo-review/reviews.json`、`data/splits/three-fold/test.json` 是否已与本机最新提交一致 |
| CPU / 内存 / 磁盘 / 媒体工具 | 32 核、可用内存约 122 GB、`~/文档` 所在分区可用 536 GB、`ffmpeg`/`ffprobe` 4.4.2、`/home/liuyang/miniconda3/envs/agent/bin/python3.11`（3.11.15），见 [training-machine-review-runbook.md](../training-machine-review-runbook.md) §2.1 | 当前实时磁盘余量（每套 8B–9B BF16 权重约需 16–20 GB `[外部文档/待训练机核实]`） |
| GPU 与驱动 | 仅在 `DF-044` / `DEC-003` 中提到「受 4090 显存限制」，**无本轮 `nvidia-smi` 实测记录** | GPU 确切型号、卡数、总显存、当前空闲显存、占用进程、驱动版本与支持的最高 CUDA 版本 |
| 推理框架与依赖 | 仅确认 `agent` 环境 Python 3.11.15 | 全部 conda/venv 环境列表；CUDA Toolkit、PyTorch（含 `torch.cuda.is_bf16_supported()`）、`transformers`、`vllm`、`sglang`、`accelerate`、`bitsandbytes`、`flash-attn`、`decord`、`av`、`qwen-vl-utils`、`httpx`、`pillow`、`opencv-python` 实际版本 |
| 本地模型权重 | `DF-044`（2026-11-14）核实 `/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5` 存在 4 分片共 17,391,890,184 B、bf16、36 层；历史记录显示该目录 `modeling_minicpmv.py` 较官方多 `self.post_init()`（[minicpm-video-loading.md](minicpm-video-loading.md) §1） | `minicpmv4_5` 关键源码/配置/分片当前 SHA-256；Qwen3-VL-8B、InternVL3-8B 及其他候选模型是否已存在于本地或 HF/ModelScope 缓存及离线可用性 |

### 2.2 可直接复制执行的核对命令清单

以下**步骤 1、2、3、4** 均为**严格静态只读查询**（不修改任何文件或 `.pyc` 缓存、不执行 `.pth` 启动钩子、不导入第三方库、不下载权重、不启动服务或训练）；**步骤 2b** 为单列的可选经授权运行期诊断（仅在需要实测 PyTorch CUDA/BF16 时执行，仍加 `-B` 禁写字节码且不加载模型权重）。命令均可直接在本机通过 SSH 发往训练机执行，并重定向保存日志到仓外目录（如本机 `/private/tmp/gpu-preflight-$(date +%Y%m%d).log`）：

#### 步骤 1：GPU、显存、当前进程与系统资源（严格静态只读）

```bash
ssh liuyang@100.70.83.68 '
echo "=== HOST & DATE ==="
hostname && date -Is
echo "=== NVIDIA-SMI ==="
nvidia-smi
echo "=== GPU CSV ==="
nvidia-smi --query-gpu=index,name,driver_version,memory.total,memory.used,memory.free,compute_cap --format=csv
echo "=== MEMORY & DISK ==="
free -h
df -h /home/liuyang /home/liuyang/文档 /tmp
'
```

#### 步骤 2：Conda / Python 环境与推理包版本盘点（严格静态只读）

> 注意：不使用 `conda env list`（其在 `~/.conda/environments.txt` 含失效路径时会清理并重写该文件），也不直接 `__import__` 第三方包或加载 `site`/`.pth` 钩子。下方命令通过列目录 + 读登记文件，并以 **`-I -S -B`** 隔离启动 Python（`-I` 隔离用户目录与环境变量、`-S` 禁用 `site` 与 `.pth` 启动钩子、`-B` 禁写 `.pyc`），**不把目标环境的 `site-packages` 加入 `sys.path`**，仅用标准库 `importlib.metadata.distributions(path=[...])` 显式只读扫描目标环境的 `lib/python*/site-packages` 元数据，保证不执行 `.pth` 启动钩子、不导入任何第三方库。

```bash
ssh liuyang@100.70.83.68 'bash -s' <<'EOF'
echo "=== CONDA ENVS (READ-ONLY) ==="
ls -la /home/liuyang/miniconda3/envs 2>/dev/null || echo "envs dir not found"
echo "--- ~/.conda/environments.txt ---"
cat ~/.conda/environments.txt 2>/dev/null || echo "no environments.txt"

echo "=== AGENT ENV METADATA CHECK (-I -S -B, NO SITE/PTH/IMPORT/PYC) ==="
ENV_ROOT="/home/liuyang/miniconda3/envs/agent"
"$ENV_ROOT/bin/python3.11" -I -S -B -c '
import glob, importlib.metadata as md, re, sys
print("python:", sys.version)
norm = lambda n: re.sub(r"[-_.]+", "-", n).lower()
sp = glob.glob(sys.argv[1] + "/lib/python*/site-packages")
found = {}
for d in md.distributions(path=sp):
    name = d.metadata["Name"]
    if name:
        found[norm(name)] = d.version
dists = (
    "torch", "torchvision", "transformers", "vllm", "sglang",
    "accelerate", "bitsandbytes", "flash-attn", "decord", "av",
    "qwen-vl-utils", "httpx", "pillow", "opencv-python",
)
for dist in dists:
    ver = found.get(norm(dist), "MISSING")
    print(f"  {dist:16s}: {ver}")
' "$ENV_ROOT"
EOF
```

> 若训练机存在其他专用推理环境（例如 `vllm`、`llamafactory`、`mvllm`），将上方 `ENV_ROOT` 及对应 Python 解释器路径替换为目标环境（保持 `-I -S -B`）重复扫描即可。

#### 步骤 2b（可选、经授权的运行期 CUDA/BF16 诊断）

上述步骤 2 仅读取包元数据，不初始化 GPU 上下文；若需在目标推理环境中实测 PyTorch 是否可用 CUDA 及 `bfloat16`，须在确认空闲显存充足后单独运行以下**运行期诊断命令**（仍加 `PYTHONDONTWRITEBYTECODE=1` 与 `-B` 避免写 `.pyc`，不加载任何模型权重）：

```bash
ssh liuyang@100.70.83.68 '
PYTHONDONTWRITEBYTECODE=1 /home/liuyang/miniconda3/envs/agent/bin/python3.11 -B -c "
import torch
print(\"torch          :\", torch.__version__)
print(\"cuda_available :\", torch.cuda.is_available())
print(\"cuda_version   :\", torch.version.cuda)
if torch.cuda.is_available():
    print(\"bf16_supported :\", torch.cuda.is_bf16_supported())
    print(\"device_count   :\", torch.cuda.device_count(), [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])
"
'
```

#### 步骤 3：本地模型权重目录与 MiniCPM-V-4.5 身份/差异核对（严格静态只读）

```bash
ssh liuyang@100.70.83.68 '
echo "=== CANDIDATE MODEL DIRS ==="
ls -lh /home/liuyang/文档/mVllm_2/base-models 2>/dev/null || echo "base-models dir not found"
du -sh /home/liuyang/文档/mVllm_2/base-models/* 2>/dev/null || true
ls -lh ~/.cache/huggingface/hub ~/.cache/modelscope/hub 2>/dev/null || echo "no default hf/modelscope cache"

echo "=== MINICPM-V-4.5 SMALL FILES & SHARDS SHA256 ==="
DIR="/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5"
if [ -d "$DIR" ]; then
  ls -la "$DIR"
  sha256sum "$DIR"/config.json "$DIR"/preprocessor_config.json \
    "$DIR"/processing_minicpmv.py "$DIR"/image_processing_minicpmv.py \
    "$DIR"/modeling_minicpmv.py "$DIR"/resampler.py 2>/dev/null || true
  grep -n "post_init" "$DIR"/modeling_minicpmv.py 2>/dev/null || true
  stat -c "%s %n" "$DIR"/*.safetensors 2>/dev/null || true
  # 注意：4 片合计约 17 GB，sha256sum 实算耗时约几十秒，严格只读
  sha256sum "$DIR"/*.safetensors 2>/dev/null || true
fi
'
```

对照基线（仓内已知）：
- 2026-11-10 官方固定 `openbmb/MiniCPM-V-4_5@daef484c...` 的两个处理器源码 SHA-256 见 [minicpm-video-loading.md](minicpm-video-loading.md) §5.3：
  - `processing_minicpmv.py`: `aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd`
  - `image_processing_minicpmv.py`: `52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7`
- 权重分片（`*.safetensors`）的 `sha256sum` 计算耗时约几十秒；在未对照可信官方分片基线清单前，该输出仅作为**本地权重快照身份留档**（供写入 `model_id` 与跨次复现核对），不得据此宣称与官方权重逐字节一致。
- 若训练机现场核出的小文件 SHA-256 与官方不一致（例如 `modeling_minicpmv.py` 存在本地 `self.post_init()` 修改），须在 `model_id` 身份说明与可信本地快照摘要清单中显式记录，不得谎称为官方原样权重。

#### 步骤 4：数据、审核库、划分与路径一致性核对（为填充 `config/eval_paths.json` 的 `gpu-train` 做准备）

```bash
ssh liuyang@100.70.83.68 '
ROOT="/home/liuyang/文档/TensileAgent-Finetune"
cd "$ROOT" || exit 1
echo "=== MEDIA COUNTS (PRELIMINARY SCREEN ONLY) ==="
printf "source_videos   : %s\n" "$(find data/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"
printf "roi_videos      : %s\n" "$(find data/roi/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"
printf "sub_video_videos: %s\n" "$(find data/sub_video/videos -maxdepth 1 -name "*.mp4" 2>/dev/null | wc -l)"

echo "=== KEY MANIFEST / REVIEW / SPLIT / PROMPT SHA256 ==="
sha256sum \
  data/annotation-table-full.csv \
  data/roi/manifest.json \
  data/sub_video/manifest.json \
  data/subvideo-review/reviews.json \
  data/splits/three-fold/test.json \
  data/splits/three-fold/*.json \
  docs/label.md \
  script/five_label_eval/prompts/five_label_v2.txt 2>/dev/null || true

echo "=== EVAL_PATHS CURRENT ==="
cat config/eval_paths.json 2>/dev/null || echo "config/eval_paths.json missing"
'
```

核对通过标准（全部 SHA-256 均为 `07d9c8e` 本机实算基线）：
- **关键文件逐一匹配**：
  - `data/annotation-table-full.csv`: `c928bea3d769eb16ad55ed7d872a877a3b4fd327d0af5422bc2bb682c1ec354c`
  - `data/roi/manifest.json`: `24b2dfa3019462dbef27fc00314901d30ad308802a458b31d95a90e4dc6948b3`
  - `data/sub_video/manifest.json`: `c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`
  - `data/subvideo-review/reviews.json`（`review_store`）: `c2a0ab5df72023de2527a3bf0a35ade758ffd3da994eac5563d4a21bb38cb3c8`
  - `data/splits/three-fold/test.json`（固定 test 划分）: `26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc`（其余 6 份三折划分及 `manifest.json` 须与本机逐行一致）
  - `script/five_label_eval/prompts/five_label_v2.txt`: `cf299d672281e12ea5f3964bb08ffbe2d237e1dfad3503861e7e21a5872cc4cf`（[prompt.md](../eval/prompt.md) §5）
- **媒体文件完整性红线（必读）**：
  - 上方 `find ... | wc -l`（期望 `110 / 110 / 1,633`）**仅为目录数量初筛，绝不能替代逐文件 SHA-256 核对**。
  - 在启动正式评测抽帧前，须对照可信清单（[data/sub_video/manifest.json](../../data/sub_video/manifest.json) 中 `sources[].source_sha256`、`sources[].roi_sha256`、`candidates[].output.sha256` 及 `data/roi/manifest.json`）对训练机上的 `data/videos/*.mp4`、`data/roi/videos/*.mp4` 与 `data/sub_video/videos/*.mp4` 做**全量逐文件 `sha256sum` 核对**（严格只读，零缺失、零不符方可通过）。
  - **严禁将 `frames.py:665–667` 或 `verify_lineage` 当作上述逐文件 `sha256sum` 核对的等价替代**：① 对于缺少声明 L0/L1 摘要的 `unverified` 候选，`frames.py:509–513` 会主动跳过 L0/L1 声明摘要比对；② `verify_lineage` 仅校验输入记录 JSON 内部字段一致性，**不会重读磁盘上的视频媒体文件**。
- **输出目录边界**：`config/eval_paths.json` 中 `gpu-train` 的 `output_dir` 与 `score_output_dir` 应指向项目工作区之外（例如 `/home/liuyang/tensile-eval-runs/...`），避免把大规模 PNG 帧图与预测产物写入项目目录。

### 2.3 单条推理耗时与超时预算估算方法

- **既有超时契约**：`DEC-003` 第 4 条与 [inference-entry.md](../eval/inference-entry.md) §7 沿用单请求超时上限 **`600.0` 秒**（性能与超时本轮只记录、不设门槛）。
- **整批耗时估算（`[推测/待训练机实测核对]`）**：
  - 按 [design-test.md](../design-test.md) §7.2，首轮不默认并发，逐条串行推理，且**首次冷启动加载耗时**与**稳定态单条耗时**分开记录。
  - 在 B1 固定 test 314 条规模下（8 帧输入、非思考模式输出约 120–200 tokens）：
    - 若单卡 24 GB 上 8B–9B 非思考模型稳定态单条耗时在 `3–10 s` `[外部文档/待训练机核实]`，314 条总耗时约 `16–52 min`（不含模型加载与预抽帧）；
    - 若使用 4-bit 量化、高切片数或 Thinking 变体（输出 800–2,000+ tokens）导致单条耗时升至 `15–40 s` `[外部文档/待训练机核实]`，314 条总耗时约 `1.3–3.5 h`。
- **实测标定规程**：正式启动 314 条 B1 前，须先在 **5–10 条开发集候选**（覆盖三个画幅档 `w_le_200` / `w_200_400` / `w_gt_400` 与 2 s / 20 s 两种时长）上跑冒烟，实测 `cold_load_seconds`、`p50`/`p95`/`max` 单条延迟、峰值显存（`nvidia-smi`）与超时触发行为，再确认是否维持 `600.0 s`（任何调整须写入运行元数据，不得静默忽略预算）。

---

## 3. 最小适配器落地路线（供用户审批后实施）

> 本节为实施方案提案，**待用户审批 [8B/9B 模型选型](vlm-8b-9b-model-comparison.md) 与 [抽帧口径方案](model-input-frame-sampling-options.md) §5 待决项、并在训练机完成 §2.2 核对后再立项实施**。

### 3.1 核心设计原则与推荐模块边界

1. **契约不变项严格锁定**：`fake` / `http` / `transformers` 三个 backend 共用同一套 `infer.py` CLI 身份校验、`predictions.jsonl` 行结构、`STATUS` 四态语义（`success` / `request_failed` / `timeout` / `unprocessed`）与独占不覆盖输出约束（[inference-entry.md](../eval/inference-entry.md) §8、[output-contract.md](../eval/output-contract.md) §3）。
2. **输入先落盘、再推理**：所有 backend 均消费 `frames.py` 产出的 `records.jsonl`（`five-label-input-record/3`）+ 8 张 L3 PNG，绝不在 `infer.py` 内静默重抽 MP4。
3. **重依赖隔离**：`infer.py` 主框架与 `http` backend 仅依赖标准库 + `httpx`（已在 [pyproject.toml](../../pyproject.toml) 开发依赖中）；`transformers` backend 采用惰性导入（仅在 `--backend transformers` 时导入），保证本机 Mac 与 CI 全量 `pytest` 无 GPU/无 `torch` 负担。

```text
script/five_label_eval/
├── frames.py                  # [小幅补齐] 对齐默认 8 帧、记录抽帧口径参数与 L3 PNG 宽高/SHA-256
├── infer.py                   # [扩展] 保留 main(argv=None) -> int；新增 --backend http、--frames-dir、超时与逐条落盘
└── backends/                  # [新增薄目录]
    ├── __init__.py            # InferenceRequest / InferenceResult 数据类与统一 Protocol
    ├── fake_backend.py        # 迁移现有 deterministic fake 逻辑，行为与测试 100% 等价
    ├── http_backend.py        # 优先落地：OpenAI-compatible POST /v1/chat/completions（覆盖 vLLM / SGLang）
    └── transformers_backend.py # 薄本地适配：直连 MiniCPM-V-4.5（含 temporal_ids / max_slice_nums / SIGALRM 超时）
```

#### 统一 Backend 接口契约（草案）

- **输入 `InferenceRequest`**：`candidate_id`、`record`（已通过 `read_records` 与推理前 `verify_lineage` 记录结构校验——注意 `verify_lineage` 不重读磁盘媒体，因此推理前还须对 `frame_paths` 盘面文件独立执行存在性与逐帧 SHA-256 校验）、`frame_paths`（按 `display_order` 排好序的 `list[Path]`）、`frame_pts_seconds`（`list[float]`）、`prompt_text`（`load_prompt` 原文不 `strip`）、`timeout_seconds`、`decode_config`（`temperature`、`max_tokens`、`seed`、`extra_body` 等）。
- **输出 `InferenceResult`**：`status`（`"success" | "request_failed" | "timeout"`）、`raw_output`（`str | None`，非 `success` 强制 `None`）、`latency_seconds`、`error_detail`（写入独立 `run_meta.jsonl`，不污染 `predictions.jsonl`，严格遵守 [output-contract.md](../eval/output-contract.md) §3 禁止旁挂结构化标签字段的红线）。

### 3.2 双后端实现要点

#### 路线 1：OpenAI-compatible `http` backend（优先落地，覆盖多模型服务）

- **适用对象**：vLLM / SGLang 启动的 Qwen3-VL-8B（Instruct / Thinking）、InternVL3-8B、InternVL3.5-8B、Keye-VL-1.5-8B、Ovis2.5-9B、GLM-4.1V-9B-Thinking、MiMo-VL-7B-RL 及未来 `TensileAgent` HTTP 服务（衔接 [agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md) §2.2）。
- **请求构造**：将 8 张 L3 PNG 编码为 `data:image/png;base64,...` 的有序 `image_url` 项，按 `display_order` 排列，与 `prompt_text` 组成单轮 `user` 消息；通过 `--api-model-name` 指定服务端路由名，与严格权重身份 `--model-id`（含快照摘要）分离；认证密钥仅通过 `--api-key-env` 指定环境变量名读取，严禁命令行明文传 key。
- **可选契约探测**：支持 `--contract-endpoint`（如 `GET /v1/tensile/contract`），配置时在请求前 fail-closed 核对服务端声明的模型/契约身份。
- **端到端超时与三态映射**：
  - 注意：`httpx.Timeout` 是**分阶段超时**（connect / read / write / pool），并非整请求墙钟总时限——若服务端响应头返回极慢或持续缓慢吐字节（如慢速 chunked body），可能总耗时超过 `600.0 s` 却不触发单次读超时。因此 `http_backend` 必须用**可取消的端到端墙钟总 deadline（默认 `600.0 s`）包住完整 HTTP 调用**（同时覆盖连接、发送、**慢响应头**与**慢响应体**全过程；超限立即取消/中止连接并判 `timeout`）；
  - `httpx.TimeoutException` 或触达端到端总 deadline → `status="timeout"`, `raw_output=None`；
  - `httpx.RequestError` / HTTP 非 2xx / 响应 JSON 异常 / `choices` 为空 / `message.content` 非字符串或空串 → `status="request_failed"`, `raw_output=None`；
  - 正常返回非空字符串 → `status="success"`, `raw_output=<原文不做 strip 或围栏剥离>`（若服务端配置 `--reasoning-parser` 产生独立 `reasoning_content` 字段，须将其写入独立 `run_meta.jsonl` 并在批次元数据显式记录 `reasoning_parser` 标识；**注意**：如 `GLM-4.1V-9B-Thinking` 搭配 `--reasoning-parser glm45` 时，`message.content` 仍保留非 special token 的 `<answer>...</answer>` 包裹标签，默认须原样写入 `raw_output` 并承受 `score.extract` 的 `surrounding_text_or_fence` / `strict_format_valid=False` 罚分——严禁在 `http_backend` 内静默剥离 `<answer>` 标签；若后续确需解包，必须经批准作为独立标明身份的新 run 模式显式启用，详见 [vlm-8b-9b-model-comparison.md](vlm-8b-9b-model-comparison.md) §3.2）。

#### 路线 2：薄本地 `transformers` backend（覆盖 MiniCPM-V-4.5 专属 `temporal_ids`）

- **适用对象**：直接落实 `DF-044`（`openbmb/MiniCPM-V-4_5` + `transformers`），并支持对 `temporal_ids`、`max_slice_nums`、`max_pixels` 像素规整做精确受控实验（这些参数无法通过标准 OpenAI `image_url` 接口完整透传）。
- **加载与身份保护**：强制 `local_files_only=True`、`trust_remote_code=True`（与历史 `model_runtime.py` 一致）。**注意：`local_files_only=True` 仅禁止联网拉取，不阻止 `trust_remote_code=True` 执行本地目录中的 Python 代码**；因此在调用 `from_pretrained` 加载之前，必须先对照人工确认的可信本地快照摘要清单，对将被执行的模型/处理器源码及配置文件逐一做 **fail-closed SHA-256 校验**（任一文件缺失或摘要不匹配即拒绝加载并退出，而不是仅记录摘要后继续执行），校验通过后再把完整快照摘要写入 `run_meta.json`。
- **超时与异常隔离**：复用 [inference-entry.md](../eval/inference-entry.md) §7 的 POSIX `SIGALRM` + `signal.setitimer(ITIMER_REAL)` 机制，非主线程或缺 `SIGALRM` 时 fail-closed 抛 `RuntimeError`（不静默忽略超时）；触发超时记 `status="timeout"`，捕获 `torch.cuda.OutOfMemoryError`（清理显存缓存后继续下一条）或其他单条推理异常记 `status="request_failed"`，确保单条失败不中断整批。

### 3.3 分阶段实施与测试策略

| 阶段 | 范围与交付物 | 验收与测试策略（严格区分合成测试与训练机实跑） |
| --- | --- | --- |
| **阶段 0（决策与体检）** | 用户确认模型梯队与抽帧口径（DEC-005 前置条件 1）；在训练机执行 §2.2 只读体检并留档；完成媒体全量逐文件 `sha256sum` 核对 | 产出训练机 Pre-flight 核对记录；确认无文件缺失或哈希不符 |
| **阶段 1（本机开发与单测）** | 1. 补齐 `frames.py` 8 帧默认口径与 L3 宽高/SHA-256；<br>2. 实现 `backends/` 抽象层 + `http_backend` + `transformers_backend` 骨架 + `infer.py` 逐条落盘与前置校验；<br>3. 补齐 `DF-037` 跨模型报告拦截 `fake` 的守卫 | **本机纯单测/mock 与本地回环集成测试（无 GPU、无真实权重）**：<br>- `http_backend`：用 `httpx.MockTransport` 覆盖 200 正常、4xx/5xx、空 content、连接断开、8 帧 base64 顺序保真、`prompt_text` 字节零修改、严禁泄露 `candidate_id`/文件路径；**并补充本地真实 HTTP 测试服务（监听回环）验证慢响应头与慢响应体均被端到端总 deadline 可取消中止并映射 `timeout`**；<br>- `transformers_backend`：用 stub processor/model 覆盖加载前可信快照 SHA-256 fail-closed 拒接、`temporal_ids` 透传、帧序一致、`SIGALRM` 超时、OOM 映射 `request_failed`；<br>- 回归全量 `pytest` + `script.checks.facts`（`gone == 0`, `ambiguous == 0`） |
| **阶段 2（训练机冒烟验证）** | 填充并核对 `config/eval_paths.json` 的 `gpu-train`；在 **5–10 条开发集片段**上实跑 MiniCPM-V-4.5（`transformers`）与 Qwen3-VL-8B / InternVL3-8B（`http`/vLLM） | 核对冷启动耗时、单条 P50/P95、显存峰值、`predictions.jsonl` 通过 `score.py` 评分，并验证 `DEC-005` 按次抽帧取证闭环；开发集冒烟结果不得混作正式 test 结论 |
| **阶段 3（授权后正式 run A）** | 取得用户正式评测授权后，在已审完的 B1 固定 test（314 条）上按 [base-model-eval-plan.md](../eval/base-model-eval-plan.md) §4、§8.1 执行 run A | 按 §8.1 (a) 类判据验收 run 完整性，按画幅三档与来源级/片段级并列报告，再由用户决定是否进入 run B/C 及确定后续微调与阈值 |

---

## 4. 来源与失效条件

- **仓内依据**：[docs/TODO.md](../TODO.md)、[DEC-003](../decisions/0003-five-label-eval-scope.md)、[DEC-005](../decisions/0005-frame-correspondence-evidence.md)、[docs/facts.yaml](../facts.yaml)（`DF-037`、`DF-044`、`DF-046`、`DF-051`、`DF-052`）、[docs/training-machine-review-runbook.md](../training-machine-review-runbook.md)、[docs/design-test.md](../design-test.md)、[docs/eval/base-model-eval-plan.md](../eval/base-model-eval-plan.md)、[docs/eval/inference-entry.md](../eval/inference-entry.md)、[docs/eval/input-record.md](../eval/input-record.md)、[docs/eval/output-contract.md](../eval/output-contract.md)、[docs/eval/prompt.md](../eval/prompt.md)、[docs/eval/agent-handoff-contract-draft.md](../eval/agent-handoff-contract-draft.md)、[docs/research/minicpm-video-loading.md](minicpm-video-loading.md)、[script/five_label_eval/infer.py](../../script/five_label_eval/infer.py)、[script/five_label_eval/frames.py](../../script/five_label_eval/frames.py)、[script/five_label_eval/paths.py](../../script/five_label_eval/paths.py)、[config/eval_paths.json](../../config/eval_paths.json)、[pyproject.toml](../../pyproject.toml)。
- **同系列关联专题**：[vlm-8b-9b-model-comparison.md](vlm-8b-9b-model-comparison.md) · [model-input-frame-sampling-options.md](model-input-frame-sampling-options.md)。

**失效条件：**当 `script/five_label_eval/infer.py`、`frames.py` 或 `paths.py` 的 CLI 参数、行号、校验逻辑或 `five-label-input-record/3` schema 发生变更；当训练机完成 §2.2 体检并更新 `config/eval_paths.json` 的 `gpu-train` 配置；当训练机入口、解释器路径、模型权重路径或第 2 批关键文件（`manifest.json`、`reviews.json`、`test.json`、`five_label_v2.txt`）摘要发生变化；或当任一真实推理 backend 落地实现时，本文受影响的缺口分析、只读体检命令与规划条目须重新核对。本文仅作前置核对与实施规划，不构成评测或实施授权。
