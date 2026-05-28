# MiniCPM 视频验证 Runbook

## 1. 前置条件

- 仓库位于远端：`~/mVllm/finetune`
- 视频目录：`/hy-tmp/videos`
- 模型目录：
  - `fold0 -> /hy-tmp/model/train/test01/sft_3k0`
  - `fold1 -> /hy-tmp/model/train/test01/sft_3k1`
  - `fold2 -> /hy-tmp/model/train/test01/sft_3k2`
- 先安装视频解码依赖：

```bash
pip install decord
```

## 2. 生成 GT JSON

在远端仓库根目录执行：

```bash
cd ~/mVllm/finetune
python AAA-TS-Video/validation/prepare_ground_truth.py
```

生成文件：

- `AAA-TS-Video/data/all_videos_tag.json`

## 3. 当前阶段复测约束

- 当前复测继续固定 `8` 帧，不调整抽帧数。
- 旧结果保留在 `AAA-TS-Video/validation/results/`。
- 这轮快修复测统一输出到 `AAA-TS-Video/validation/results_v2/`，避免覆盖旧结果。
- `--prompt-preset` 共有 3 档：
  - `baseline`：旧提示词，对照组。
  - `strict`：默认，用闭集标签和严格时间格式约束。
  - `fewshot`：仅建议用于 `type` 和 `joint`；`time` 会自动回退到 `strict`。

## 4. 先做 dry-run

先对 `fold0` 抽 3 条样本检查环境、prompt 和解析结果：

```bash
cd ~/mVllm/finetune

python AAA-TS-Video/validation/run_inference.py \
  --task time \
  --fold 0 \
  --prompt-preset strict \
  --output AAA-TS-Video/validation/results_v2/time/fold0.strict.dryrun.jsonl \
  --max-samples 3

python AAA-TS-Video/validation/run_inference.py \
  --task type \
  --fold 0 \
  --prompt-preset fewshot \
  --output AAA-TS-Video/validation/results_v2/type/fold0.fewshot.dryrun.jsonl \
  --max-samples 3

python AAA-TS-Video/validation/run_inference.py \
  --task joint \
  --fold 0 \
  --prompt-preset fewshot \
  --output AAA-TS-Video/validation/results_v2/joint/fold0.fewshot.dryrun.jsonl \
  --max-samples 3
```

如果 dry-run 正常，再跑全量。

## 5. 跑全量推理

### 推荐复测矩阵

- `type`: `baseline` / `strict` / `fewshot`
- `joint`: `baseline` / `strict` / `fewshot`
- `time`: `baseline` / `strict`

### 时间任务

```bash
cd ~/mVllm/finetune

python AAA-TS-Video/validation/run_inference.py --task time --fold 0 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/time/fold0.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task time --fold 1 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/time/fold1.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task time --fold 2 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/time/fold2.baseline.jsonl

python AAA-TS-Video/validation/run_inference.py --task time --fold 0 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/time/fold0.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task time --fold 1 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/time/fold1.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task time --fold 2 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/time/fold2.strict.jsonl
```

### 类型任务

```bash
cd ~/mVllm/finetune

python AAA-TS-Video/validation/run_inference.py --task type --fold 0 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/type/fold0.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 1 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/type/fold1.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 2 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/type/fold2.baseline.jsonl

python AAA-TS-Video/validation/run_inference.py --task type --fold 0 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/type/fold0.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 1 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/type/fold1.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 2 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/type/fold2.strict.jsonl

python AAA-TS-Video/validation/run_inference.py --task type --fold 0 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/type/fold0.fewshot.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 1 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/type/fold1.fewshot.jsonl
python AAA-TS-Video/validation/run_inference.py --task type --fold 2 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/type/fold2.fewshot.jsonl
```

### 联合任务

```bash
cd ~/mVllm/finetune

python AAA-TS-Video/validation/run_inference.py --task joint --fold 0 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/joint/fold0.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 1 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/joint/fold1.baseline.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 2 --prompt-preset baseline --output AAA-TS-Video/validation/results_v2/joint/fold2.baseline.jsonl

python AAA-TS-Video/validation/run_inference.py --task joint --fold 0 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/joint/fold0.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 1 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/joint/fold1.strict.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 2 --prompt-preset strict --output AAA-TS-Video/validation/results_v2/joint/fold2.strict.jsonl

python AAA-TS-Video/validation/run_inference.py --task joint --fold 0 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/joint/fold0.fewshot.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 1 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/joint/fold1.fewshot.jsonl
python AAA-TS-Video/validation/run_inference.py --task joint --fold 2 --prompt-preset fewshot --output AAA-TS-Video/validation/results_v2/joint/fold2.fewshot.jsonl
```

## 6. 跑评测

建议按 `prompt-preset` 分开评测，不要把 `baseline/strict/fewshot` 混在一起。

### 时间评测

```bash
cd ~/mVllm/finetune
python AAA-TS-Video/validation/evaluate_time.py \
  --inputs \
  AAA-TS-Video/validation/results_v2/time/fold0.strict.jsonl \
  AAA-TS-Video/validation/results_v2/time/fold1.strict.jsonl \
  AAA-TS-Video/validation/results_v2/time/fold2.strict.jsonl \
  --out-dir AAA-TS-Video/validation/results_v2/time_eval_strict
```

### 类型评测

```bash
cd ~/mVllm/finetune
python AAA-TS-Video/validation/evaluate_type.py \
  --inputs \
  AAA-TS-Video/validation/results_v2/type/fold0.fewshot.jsonl \
  AAA-TS-Video/validation/results_v2/type/fold1.fewshot.jsonl \
  AAA-TS-Video/validation/results_v2/type/fold2.fewshot.jsonl \
  --out-dir AAA-TS-Video/validation/results_v2/type_eval_fewshot
```

### 联合评测

```bash
cd ~/mVllm/finetune
python AAA-TS-Video/validation/evaluate_joint.py \
  --inputs \
  AAA-TS-Video/validation/results_v2/joint/fold0.fewshot.jsonl \
  AAA-TS-Video/validation/results_v2/joint/fold1.fewshot.jsonl \
  AAA-TS-Video/validation/results_v2/joint/fold2.fewshot.jsonl \
  --out-dir AAA-TS-Video/validation/results_v2/joint_eval_fewshot
```

如果要对比不同 preset，就分别替换 `--inputs` 和 `--out-dir` 再各跑一遍。

## 7. 结果位置

### 原始推理结果

- `AAA-TS-Video/validation/results/time/fold*.jsonl`
- `AAA-TS-Video/validation/results/type/fold*.jsonl`
- `AAA-TS-Video/validation/results/joint/fold*.jsonl`
- `AAA-TS-Video/validation/results_v2/time/*.jsonl`
- `AAA-TS-Video/validation/results_v2/type/*.jsonl`
- `AAA-TS-Video/validation/results_v2/joint/*.jsonl`

### 评测结果

- 时间：
  - `AAA-TS-Video/validation/results/time_eval/time_metrics.json`
  - `AAA-TS-Video/validation/results/time_eval/time_errors.csv`
  - `AAA-TS-Video/validation/results/time_eval/time_excluded_samples.csv`
- 类型：
  - `AAA-TS-Video/validation/results/type_eval/type_metrics.json`
  - `AAA-TS-Video/validation/results/type_eval/type_per_class.csv`
  - `AAA-TS-Video/validation/results/type_eval/type_confusion_matrix.csv`
- 联合：
  - `AAA-TS-Video/validation/results/joint_eval/joint_metrics.json`
  - `AAA-TS-Video/validation/results/joint_eval/joint_failures.csv`
- v2 复测：
  - `AAA-TS-Video/validation/results_v2/*`

## 8. 常见问题

### `No module named 'decord'`

执行：

```bash
pip install decord
```

### 推理脚本找不到视频

检查：

```bash
ls /hy-tmp/videos | head
```

### 想临时指定别的模型目录

可追加参数：

```bash
--model-dir /your/model/path
```

### 想切换提示词策略

可追加参数：

```bash
--prompt-preset baseline
--prompt-preset strict
--prompt-preset fewshot
```
