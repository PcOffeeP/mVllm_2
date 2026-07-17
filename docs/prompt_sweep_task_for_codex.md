# Prompt Sweep 验证任务 — 给 Codex

## 3.1 背景（简述）

- **项目**：mVllm_2 — 拉伸试验视频断裂检测
- **本地已完成**：Protocol 改造、新 Prompt 替换、Normalizer 模块、评估适配
- **远程需要**：用微调后模型跑 Prompt Sweep，验证 `has_fracture` Recall 不下降

## 3.2 任务步骤

### Step 1：进入项目目录

```bash
cd /home/liuyang/文档/mVllm_2
```

### Step 2：确认微调后模型路径

```bash
ls finetune/output/
```

如果没有结果，再检查：

```bash
ls LlamaFactory/saves/
```

找到最近一次微调合并后的模型目录，记下**完整路径**。

### Step 3：运行 Prompt Sweep

```bash
python -m finetune.validation.run_prompt_sweep prompt \
    --model-dir <上一步确认的模型路径> \
    --dataset fold_0_val
```

注意事项：

- `--prompt` 参数已废弃，**不要加**
- 这是子命令模式，第一个位置参数是 `prompt`
- 脚本会自动对比 `light` / `medium_relaxed` / `medium` 三个 Prompt 变体
- 结果输出到 `finetune/results/prompt_sweep/prompt/` 下自动生成的带时间戳目录

### Step 4：确认结果文件存在

```bash
ls -la finetune/results/prompt_sweep/prompt/
```

查看产物——应有 summary 文件或 JSON 结果。

### Step 5：通过 Git 同步回 Mac

```bash
git add -f finetune/results/prompt_sweep/prompt/
git commit -m "prompt sweep results: relaxed prompt v2 validation"
git push
```

> `-f` 是因为 `.gitignore` 忽略了该目录，需要 force add。

## 3.3 关键判断指标

| 指标 | 说明 | 期望 |
|---|---|---|
| `has_fracture_recall` | 主要指标 | **不低于旧协议 baseline** |
| `has_fracture_precision` | 辅助指标 | 不应显著下降 |
| `type_null_rate` | 诊断指标 | 查看模型是否过度使用 null |
| `location_null_rate` | 诊断指标 | 同上 |
| `interval_null_rate` | 诊断指标 | 同上 |

对比对象：三个变体（`light` / `medium_relaxed` / `medium`）之间的指标差异。

## 3.4 遇到问题时的处理

- **`--model-dir` 找不到模型**：列出 `finetune/output/` 和 `LlamaFactory/saves/` 的内容，让用户选择
- **ModuleNotFoundError**：确保在项目根目录下用 `python -m` 执行，不要用 `cd` 到子目录再跑
- **其他报错**：截图或复制报错信息，返回给主 Agent

## 3.5 完成后

结果同步回 Mac 后，主 Agent 会做最终分析。
