# Project Agent Instructions

关联文档：

- [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)
- [finetune/README.md](finetune/README.md)
- [README.md](README.md)

## 双机工作机制

- 当前电脑用于项目开发、代码查看、结果文件检查、静态分析、文档整理和结论汇总。
- 实际模型训练、GPU 推理、评测跑分、长时间数据处理，以及任何依赖 4090 显卡的任务，必须在另一台训练电脑上执行。
- 当前电脑上看到的训练目录、日志、指标、预测文件和报告，视为从训练电脑同步或复制过来的结果产物；Agent 可以基于这些产物做效果分析，但不得默认当前电脑能复现实验。
- 当需要判断模型实际效果时，优先使用训练电脑产出的真实评测结果、预测样例、指标文件和日志，而不是仅凭本机可运行的轻量检查。
- 如果当前电脑缺少 checkpoint、LoRA adapter、merged model、预测样例或评测指标，应将结论标记为“证据不足”，并明确需要在训练电脑上补跑或补同步的内容。
- 不要在当前电脑上启动重训练、GPU 推理或长评测任务；如需这些操作，应生成可在训练电脑执行的命令、任务单或检查清单。

## 双机 Git 提交纪律

- 两台机器是同一项目的独立 Git 工作区。操作或同步前分别检查分支、`HEAD`、`git status` 和两端独有提交，禁止覆盖未提交修改或未经检查强制对齐。
- 每完成一个可独立验证步骤，在实际产出机器完成必要校验并原子化 `git commit`；提交前检查范围、`git diff --check` 和必要测试。跨机步骤分别提交代码/流程与轻量 manifest、哈希或报告，大型及敏感产物不入 Git。
- 默认禁止 `git push`；仅在用户明确授权并确认两端状态、提交内容及目标远端分支后推送，不默认强制推送。

## 训练机 SSH 连接

- SSH 目标：`100.70.83.68`
- SSH 用户：`liuyang`
- SSH 端口：`22`
- 系统主机名：`dell-Precision-3660`
- 远程用户目录：`/home/liuyang`
- 远程项目目录：`/home/liuyang/文档/mVllm_2`
- 本机 `~/.ssh/config` 已配置上述目标和用户；认证使用本机已有的 OpenSSH 密钥或 SSH agent，不在仓库中保存私钥、口令或其他凭据。
- 交互连接命令：`ssh 100.70.83.68`
- 在项目目录执行单条命令：`ssh 100.70.83.68 "cd '/home/liuyang/文档/mVllm_2' && <command>"`
- 需要训练、GPU 推理、完整评测或长时间数据处理时，通过该 SSH 连接在训练机执行；连接前先明确命令、输入、输出位置和预计资源占用。
- 默认只操作远程项目目录及明确指定的训练产物。删除或覆盖远程文件、修改系统配置、安装系统级依赖、停止已有任务等高风险操作，必须先获得用户明确授权。

## 训练结果验收口径

- `train_loss` / `eval_loss` 下降只能证明训练目标收敛，不能单独证明模型任务效果好。
- 断裂检测模型的实际验收应至少查看：JSON/schema 合法率、`has_fracture` 准确性、type/location 指标、interval/time 命中率、joint success rate、典型预测样例和失败样例。
- 对 LoRA/merged 模型做结论前，应确认实际加载的模型路径、checkpoint step、adapter 文件、metadata 和评测结果彼此一致。
- 如果训练目录中的 metadata 指向旧实验、缺少 adapter/checkpoint，或评测结果无法对应到当前模型，应优先指出产物链路问题，而不是给出正向效果结论。

## 命名规范

总原则：会"被修改"的东西不带版本号；只"新增不修改"的不可变产物必须带版本号/标识。历史版本一律从 git 历史获取，禁止 `_old`/`_v2`/`_bak` 类后缀。

1. 脚本命名：`<阶段前缀>_<动作>_<对象>.py`，阶段前缀对应项目主流程：
   - `source_`（初始数据划分）、`roi_`（ROI 标注/冻结/物化）、`subvideo_`（子视频生成）、`review_`（人工审查）、`release_`（数据发布）、`train_`（Prompt 准备与训练）、`eval_`（测评）、`serve_`（模型发布与推理）；
   - 动作用词表：build_ / prepare_ / run_ / validate_ / audit_ / freeze_ / materialize_ / monitor_ / smoke_ / route_ / rebuild_ / manage_；
   - 脚本服务哪个契约由代码内加载的契约文件声明，不由文件名声明；
   - 被取代的脚本直接删除（git 历史即归档）；
   - 每个脚本目录配同目录 SCRIPTS.md 索引。
2. 分支命名：`<类型>/<主题>[-<补充>]`，全小写连字符；类型限定：feat/ fix/ refactor/ data/ exp/ docs/ chore/；数据轮次用 `data/<yyyymm>-round<N>`（日期+轮次，不挂协议版本）；main 是唯一长期分支，其余短命合并即删。
3. 不可变产物 ID（沿用现有格式）：
   - 数据 release：`v<协议版本>-<内容哈希>`（如 v4.1.0-ecb5aeb9657c）
   - 契约：`tensile_vlm_v<版本>.json`
   - Prompt revision：`v<协议>-<描述>-r<N>`
   - 模型 release：`v<协议>-<描述>-fold<N>-r<N>`
   - 实验：`v<协议>-<主题>-v<N>-seed<N>`
4. 不可变产物集合目录必须配 `index.json`（由生成脚本自动维护）；全局总览由 `build_artifact_index.py` 扫描各集合目录的 `index.json` 生成。同一集合目录同一时刻只允许一个写入进程（当前调用链为顺序执行），并发写入会导致条目静默丢失。当前索引覆盖 staging 侧与 `roi_manifests`/`roi_videos`；`promote` 尚未把 `index.json` 从 source/split 快照传播到正式 workspace 集合，为已知待办。

## 文档与审查纪律

1. 权威操作类文档（如 RUNBOOK、部署手册）的新建或整体重写，必须执行两段式：撰写 → 独立核查（由不同 Agent 对照实际代码逐条验证），不得仅凭作者自验入库。
2. 派发任务时，上下文分为「背景事实」与「验收标准」两个区域；结构性、完整性要求必须写入验收标准，不得只放在背景事实中。
3. 重写/新建流程类文档的验收标准必须包含链路完整性检查：目标流程每个环节的入口脚本与产物在文档中可追溯（无"从天而降"的参数或产物）。
