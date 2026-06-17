# 仓库规范

## 项目结构与模块组织

- `agent/`：Agent/模型接口契约实现、schema、prompt、采样、推理客户端和 `IterativeAgent` 状态机。
- `data/01_videos/`：原始视频，本地数据，命名为 `video_XXXX.mp4`，不要提交。
- `data/02_annotations/`：CSV 标注文件、`video_mapping.csv` 和 `all_videos_tag.csv`。
- `data/03_splits/`：旧 `stratified_3_fold_*.json` 基线保留；新 interval 方案会生成 `fold_*_{train,val}.json` 与 `test.json`。
- `data/04_merged/`：旧直接预测基线训练/验证 JSON，冻结保留。
- `data/02_subvideos/`、`data/03_frames/`、`data/04_new_merged/`、`data/metadata/`：新 interval pipeline 的本地生成产物，不提交。
- `pipeline/scripts/`：数据集准备、子视频生成、训练样本构建脚本；从仓库根目录运行。
- `pipeline/config/`、`pipeline/templates/`：旧问题池和 JSON 模板。
- `finetune/`：项目专属 LLaMA-Factory 配置、数据集注册表和验证脚本。
- `LlamaFactory/`：LLaMA-Factory git submodule，不在 `finetune/` 中维护框架源码副本。
- `docs/`：设计笔记、接口契约和领域参考资料。
- `tests/`：项目级 pytest 测试。

## 构建、测试与开发命令

初始化依赖：

```bash
git submodule update --init --recursive
cd LlamaFactory/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt
```

旧基线数据流程：

```bash
python3 pipeline/scripts/dataset_manager.py
python3 pipeline/scripts/generate_questions.py -s data/03_splits/stratified_3_fold_0.json -b stratified_3_fold_0
python3 pipeline/scripts/fill_answers.py -b stratified_3_fold_0
python3 pipeline/scripts/merge_batches.py --source answered
```

新 interval 数据流程：

```bash
python3 pipeline/scripts/dataset_manager.py
python3 pipeline/scripts/subvideo_builder.py
python3 pipeline/scripts/training_sample_builder.py
python3 scripts/validate_no_oob.py
```

训练一个旧基线 fold：

```bash
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml
```

训练一个新 interval fold：

```bash
cd finetune/
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1
llamafactory-cli train MiniCPM/config/minicpmv4_6_lora_sft_interval_fold0.yaml
```

项目级验证：

```bash
python3 -m pytest tests -q
python3 scripts/validate_no_oob.py
git diff --check
```

## 代码风格与命名约定

使用 Python 3.11。遵循 `LlamaFactory/pyproject.toml` 的基本风格：4 空格缩进、双引号、每行 119 字符，并在需要时使用 Google 风格 docstring。确保 `pipeline/scripts/`、`scripts/` 和 `finetune/validation/` 下脚本可从仓库根目录通过 `python3` 运行。保留 `video_XXXX.mp4`、`stratified_3_fold_N`、`fold_N_train`、`fold_N_val` 的命名方式。

## 标签治理与数据口径

CSV 标注是权威来源。发生冲突时，不覆盖 CSV 原字段；通过 `has_fracture_canonical`、`location_canonical`、`is_label_conflict`、`label_governance_reason` 等派生字段表达训练口径，并在下游样本构造中使用 canonical 字段。

旧基线文件继续留在索引里：

- `data/03_splits/stratified_3_fold_*.json`
- `data/04_merged/stratified_3_fold_*_{train,val}.json`

不要为了清理生成产物删除这些旧基线。若确实要废弃旧基线，需要同步更新 `finetune/dataset_info.json`、`finetune/validation/config.py` 和相关文档。

## 测试规范

项目级测试从仓库根目录运行 `python3 -m pytest tests -q`。真实生成产物不存在时，部分 `data/metadata/` 或 `data/04_new_merged/` 相关测试应 `skip`，不能依赖本机 ignored 产物才能通过。修改 pipeline 后，优先运行相关单测、一个小样本脚本链路和 `scripts/validate_no_oob.py`。修改 Agent runtime 后，重点覆盖 `tests/test_iterative_agent.py`、`tests/test_sampling*.py`、`tests/test_parser.py`、`tests/test_inference.py`。

## Agent Runtime 规范

Agent 使用 Native Function Calling，不引入 MCP。`IterativeAgent` 的状态转移、候选区间更新、边界哨兵处理、冲突处理和最终 `terminate` 输出聚合必须由代码层兜底，不能完全信任 LLM 参数。每轮 `sample_and_infer` 后必须把更新后的候选区间和历史追加到下一轮 user context。Agent 推理阶段动态生成的帧和临时 clip 写入 `data/runtime/`，不要提交。

## 提交与拉取请求规范

近期提交摘要使用英文或中文：`docs: ...`、`feat: ...`、`refactor(...): ...`、`Update ...` 或 `第二批提交：...`。保持提交聚焦任务。PR 应说明目的、变更路径、已运行的命令和硬件假设。验证可视化结果请附上截图或图表。

## Git 工作流与并行实现

以 `main` 作为稳定集成分支。如需并行工作，优先使用 `git worktree`，而非在一个目录中切换分支。长期分支通过 `git fetch` 加 `git rebase main` 同步，或在需要保守协作时使用 `git merge main`。

历史上的并行分支职责如下，后续拆分任务时仍按这个边界组织：

- contract 分支：schema、adapter、prompt/message 格式、评估 fixture 和配置。
- finetuning pipeline 分支：训练数据、pipeline 脚本、LLaMA-Factory 配置、验证和 checkpoint。
- agent runtime 分支：工具调用、执行循环、状态、记忆/上下文、调度和接口。

## 安全与配置提示

不要提交 checkpoint、模型权重、密钥、token、大型输出文件或本地视频数据。`.gitignore` 已覆盖 `data/01_videos/`、`data/02_subvideos/`、`data/03_frames/`、`data/04_new_merged/`、`data/metadata/`、`data/runtime/` 和验证结果目录。PR 中记录本地模型路径、GPU 相关 YAML 设置和 `DOWNSAMPLE_MODE`。标注时间保持为 `XXX.XXs` 格式，不要嵌入空格。
