# 仓库规范

## 项目结构与模块组织

- `data/01_videos/`：原始视频，命名为 `video_XXXX.mp4`。
- `data/02_annotations/`：CSV 标注文件、`video_mapping.csv` 和 `all_videos_tag.csv`。
- `data/03_splits/`：分层 3 折（stratified 3-fold）数据划分定义。
- `data/04_merged/`：用于微调的最终训练/验证 JSON。
- `pipeline/scripts/`：数据集准备脚本；从仓库根目录运行这些脚本。
- `pipeline/config/`、`pipeline/templates/`：问题池和 JSON 模板。
- `finetune/`：项目专属 LLaMA-Factory 训练配置、验证脚本与数据集注册表。LLaMA-Factory 框架源码位于仓库根目录 `LlamaFactory/` submodule。
- `docs/`：设计笔记、接口和领域参考资料。

## 构建、测试与开发命令

准备数据：

```bash
python3 pipeline/scripts/dataset_manager.py
python3 pipeline/scripts/generate_questions.py -s data/03_splits/stratified_3_fold_0.json -b stratified_3_fold_0
python3 pipeline/scripts/fill_answers.py -b stratified_3_fold_0
python3 pipeline/scripts/merge_batches.py --source answered
```

安装 LLaMA-Factory（在 `LlamaFactory/` submodule 中执行一次即可）：

```bash
cd LlamaFactory/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

训练一个折（fold，在 `finetune/` 下执行）：

```bash
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml
```

## 代码风格与命名约定

使用 Python 3.11。遵循 `LlamaFactory/pyproject.toml` 的代码风格：4 空格缩进、双引号、每行 119 字符，并在需要时使用 Google 风格文档字符串。确保 pipeline 脚本可从仓库根目录通过 `python3` 运行。保留 `video_XXXX.mp4` 和 `stratified_3_fold_N` 的命名方式。

## 测试规范

不再在 `finetune/` 中维护 LLaMA-Factory 框架测试。项目级测试（如有）请在仓库根目录运行 `pytest tests/`。修改 pipeline 后，在一个折上运行受影响的脚本并检查生成的 JSON。

## 提交与拉取请求规范

近期提交摘要使用英文或中文：`docs: ...`、`Update ...` 或 `第二批提交：...`。保持提交聚焦任务。PR 应说明目的、变更路径、已运行的命令和硬件假设。验证可视化结果请附上截图或图表。

## Git 工作流与并行实现

以 `main` 作为稳定集成分支。如需并行工作，优先使用 `git worktree`，而非在一个目录中切换分支。先合并一个小的共享契约（contract）分支，然后独立开发微调和 Agent 运行时：

```bash
git checkout main
git checkout -b feat/agent-model-contract
git worktree add ../TensileAgent-finetuning -b feat/finetuning-pipeline main
git worktree add ../TensileAgent-agent -b feat/agent-runtime main
```

`feat/agent-model-contract` 仅定义 schema、adapter、prompt/message 格式、评估 fixture 和配置。`feat/finetuning-pipeline` 负责训练数据、脚本、配置、评估和 checkpoint。`feat/agent-runtime` 负责工具调用、执行循环、状态、记忆/上下文、调度和接口。在契约合并到 `main` 之前，不要依赖未合并分支的代码；使用 mock 或 fixture。通过 `git fetch` 加 `git rebase main` 同步长期分支，或在需要保守协作时使用 `git merge main`。

## 安全与配置提示

不要提交 checkpoint、密钥、token 或大型输出文件。在 PR 中记录本地模型路径和 GPU 相关的 YAML 设置。标注时间保持为 `XXX.XXs` 格式，不要嵌入空格。
