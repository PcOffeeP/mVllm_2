# 2026-10-13 训练机只读现状核查

## 范围与证据口径

执行者为 Codex；Mac 负责发起 SSH、保存结果及维护本地文档，现场查询在 `dell-Precision-3660` 执行。目标为 `liuyang@100.70.83.68:22`，项目 `/home/liuyang/文档/mVllm_2`，正式 store `/data/mVllm_2`。本轮未执行业务文件写入、fetch、同步代码、安装或激活环境、加载模型、启动训练、推理或评测。一次Git查询存在下述索引刷新限制，不能宣称远端所有文件元数据绝对未变化。

开始时本机 Tailscale 为 Stopped，SSH 在认证前关闭；用户连接已有网络后，状态为 Running、本机及训练机 peer 在线，SSH 查询成功。这不构成训练机服务故障的证据。

SSH 使用 `BatchMode=yes`、`StrictHostKeyChecking=yes`、`ConnectTimeout=10`；Python 查询使用 `-B`，从 stdin 执行只读脚本。读取发行包元数据，不导入 torch、项目或 MLflow；Git环境核查和末尾检查使用 `--no-optional-locks`，但模型盘点脚本的一次普通 `git status --short --branch` 漏用了该选项，也没有外层 `GIT_OPTIONAL_LOCKS=0` 证据。普通status可能刷新 `.git/index`；未采集索引前后元数据，不能证明或排除写入。这是对严格只读约束的执行偏差，后续查询统一禁用可选锁；末尾porcelain为空只证明工作区内容干净。本轮 JSON 数据整体解析并检查过首行字段结构，最终媒体审计仅处理 `videos[0]`；没有检查或输出消息、标签的文本语义，也没有访问 sealed-test 内容。

本轮返回的只读查询结果已汇总保存到[现场快照](remote-state-refresh-20261013.json)。原始脚本、命令、退出码与结果保存在 Mac `/private/tmp/mvllm2-readonly-20261013/`：`remote_audit.{py,json}`、`remote_command.txt`、`historical_env_audit.{py,json}`、`historical_source_stat.json`、`data-command-scripts/`、`data-reference-audit.json`、`data-remote-check.json`、`data-dvc-configs.json`、`model_inventory.py`、`model-inventory.json`。临时目录不是长期备份；本报告保存可追溯摘要，不把空输出或首轮探索结果当作完成证据。

## Git

| 位置 | 分支与 HEAD | 工作区 / 比较 |
| --- | --- | --- |
| Mac 检查开始时 | `docs/consolidate-project-status@59dee2d1b31d76c4a26365b8875c5369e48eba8e` | 干净；本地 `main...HEAD` 为 `0 5` |
| Mac main | `3f200461026a59676aaac7ea864f8fadb599688d` | 文档分支的祖先 |
| Codeup 实时 main | `3f200461026a59676aaac7ea864f8fadb599688d` | `git ls-remote codeup refs/heads/main`，exit 0；没有 fetch |
| 训练机 | `main@3f200461026a59676aaac7ea864f8fadb599688d` | porcelain 为空；LlamaFactory checkout 与 gitlink `4447137e` 一致且干净 |

训练机不含 Mac 候选提交 `59dee2d1`（`git cat-file -e` exit 128），未传输对象。本机提交图证明文档分支领先现场基线 5 个提交；不把这一结果写成训练机执行了候选版本。训练机 `origin/main` 是未 fetch 的本地 tracking ref；实时 Codeup main 是另一次服务器只读查询结果。本报告及台账的后续本地提交不属于上述起始快照。全部查询结束后，主Agent再次只读执行训练机 porcelain status，exit0且输出为空；现场工作区仍干净。

## Python 与环境来源

| 环境 | 现场事实 | 结论 |
| --- | --- | --- |
| Conda `agent` | Python 3.11.15；对当前 GPU 锁 241 个精确版本项，发行包元数据缺 85 项、版本不同 2 项；LlamaFactory editable 指向正式项目子模块 | Python 版本满足声明，依赖尚不符合锁 |
| Conda `cpm45` | Python 3.11.15；缺 143 项、版本不同 20 项；editable 指向旧 `/home/liuyang/文档/mVllm/LlamaFactory` | 依赖和源码来源均不符合当前目标 |
| 历史 `deployment-gpu-mirror-20260914` | Python 3.11.15 venv，`include-system-site-packages=false`；所查关键依赖元数据在场；editable 指向隔离 `deployment-check-20260914/LlamaFactory`，路径存在 | 保留的历史部署环境；没有绑定正式项目的 Conda 验收证据 |
| 历史 `deployment-gpu-20260914` | venv 在场，但所查关键包元数据缺失 | 与历史中断安装记录相符，不作为运行环境 |

两处历史 GPU venv 位于 `/home/liuyang/文档/mVllm_2-migration-7eeb93a7/`；`pyvenv.cfg` 的基础解释器来自 Conda agent，不改变它们是独立 venv 的事实。镜像环境所查版本包括 accelerate 1.11.0、peft 0.18.1、trl 0.24.0、datasets 4.0.0、av 16.0.0、pandas 2.3.3、DVC 3.67.1、MLflow 3.15.2；没有全锁比对或重新执行 doctor。torch 的发行包元数据为 2.5.1，不能单凭该字段推断 CUDA wheel 或运行可用性。

本次非交互 shell 的 `command -v python` 无路径，`CONDA_PREFIX` 为空；不能据此认定用户交互 shell 的默认环境。正式 Conda 环境绑定任务仍待处理。Mac 使用 uv，训练机使用获验收的对应 Conda Python 3.11.x 的平台分工保持。

## 数据与外部媒体引用

| 身份 | 元数据与回执 | 去重引用 / 缺失 |
| --- | --- | --- |
| `data-v4.1-r1` | sealed、development、training_allowed=true；sample_count=1275；superseded，replacement 为 r2；receipt committed | 1275 / 0 |
| `data-v4.1-r2` | sealed、development、training_allowed=true；sample_count=1678；active；receipt committed | 1678 / 0 |

两版 receipt 的目标身份及相对 release 路径对应正确；receipt 的 `target_status/replacement` 为 null，最终生命周期来自 `release.yaml`。没有重算 source manifest 或目标目录摘要，因此不是完整迁移验签复跑。

迁移 release 的六份数组 JSON 直接位于 `datasets/train` 和 `datasets/validation`，逐折行数与 release 元数据一致：r1 为 850/425、830/445、929/346；r2 为 1253/425、1014/664、1186/492。六文件累计行数分别 3825、5034，重复来自三折分配，不是独立样本总数。有效计数证据为 `data-reference-audit.json`；首轮 `data-remote-check.json` 的 row_count=null 只是结构探索，不用于验收。

引用按 `pipeline/data_roots.py` 的历史路径映射规则落到 `/home/liuyang/文档/mVllm_2/workspace/data/`，所有映射路径均能 stat。没有全面验证普通文件类型、逐级软链、媒体内容哈希或解码能力；少量链接/大小样例不能代替完整媒体验证。正式数据仍依赖旧媒体根，不能据迁移完成清理该目录。

项目根及 store 根的 `.dvc/config`、`.dvc/config.local` 均不存在；只说明这四个位置未发现 DVC remote/cache 配置，不代表用户级配置、缓存或备份不存在。

## 模型资产与运行现场

`workspace/models/current` 仍指向 `releases/v4.1-agent-pipeline-fold0-r1`。其 adapter 有一个 safetensors 文件（460,430,776 bytes），merged 索引列出的 10 个分片均在场。小型 release manifest 关联 `tensile-vlm/v4.1`、旧 Fold0 模型身份、origin experiment `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3` 以及数据 `v4.1.0-ecb5aeb9657c`；该 manifest SHA-256 为 `3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`。

基座 `models/minicpmv4_5` 索引声明的 4 个 safetensors 分片均能 stat，合计 17,391,890,184 bytes；`models/minicpm_v_4_5` 是对应软链接。adapter_config 中主要基座引用为相对字符串 `../models/minicpm_v_4_5`，未确认加载器实际解析方式，因此不把相对引用写成运行时基座已验。

限定检查的 8 个顶层 run 中，5 个 phase run 有 fold0 adapter/merged，merged 索引各列出 10 个在场分片；coverage-first seed3407 的 merged 指向发布库，是共享资产而非独立副本。minimal v1 有根级 adapter/merged。concise v1/v2 的已查根级及 fold 位置未见 adapter/merged/checkpoint；所列顶层 run 没有 visual。没有搜索全盘或其他归档位置，不宣称这些权重已永久丢失。

按当前代码定义核对 `/data/mVllm_2/records/models`、`records/training`、`records/evaluations`，均未找到；records 的直接清单仅有 prompts。指定 store 下默认 `workspace/mlflow`、其 `mlflow.db/artifacts`、`workspace/models/materialized` 也未找到。这不排除其他配置根、数据库或隔离验证目录存在正式记录；本轮未连接数据库，尚不能认定真实模型已完成新 Registry 注册和物化。

`nvidia-smi` 返回 RTX 4090、驱动 580.159.03、显存总量 24564 MiB/使用 663 MiB；该瞬间 compute-process 列表只有 gnome-remote-desktop-daemon（392 MiB），8002 端口未监听。未检查全部 CPU 进程或其他端口，不据此断言整机没有任何任务。该结果不是本轮训练、CUDA 模块或服务推理验收。

权重仅核对名称、索引引用、stat 和大小；没有读取/哈希大型权重、加载模型或刷新效果指标。旧模型质量基线仍是[2026-09-14 历史证据](model-gate-baseline-20260914.md)。

## 下一步与验收限制

优先处理 [ENV-ACTIVATION](../project-todo.md#env-activation--正式解释器与最终-checkout-绑定)：先选定正式 Conda 环境及 checkout，准备锁依赖、子模块和 editable 来源的验收方案；实际环境创建、修复或切换另需实施授权。代码同步也须在确认提交内容和目标后另行授权，本轮不执行。

环境方案之后先核定正式 Registry 的实际配置根、旧 Fold0 与候选模型的来源/权重/基座关联及 concise、visual 的指定恢复位置，再准备开发侧 MODEL-DIAG 方案。不要在未确认正式运行环境和数据/模型身份时直接启动全量训练。数据内容验证、模型加载验证、独立 test 资格和真实恢复仍是分开的后续任务。当前检查不关闭这些效果或恢复门槛。

独立 reviewer 核查完成：现场快照7组queries与原始JSON逐对象一致，SSH传入241个精确版本项与当前GPU锁一致；本轮3份Markdown的83处本地文件/锚点链接有效，`git diff --check`通过，未检出凭据标记。首轮发现模型脚本普通git status遗漏禁用可选锁，已如实披露潜在索引刷新及证据限制；最终无其他可执行问题。复核只检查本地证据与脚本，没有另连训练机或重新运行模型。Tailscale状态、实时Codeup查询及末尾SSH结果来自主Agent工具记录，临时目录未完整保存这三项原始输出；不将它们表述为reviewer独立重放。
