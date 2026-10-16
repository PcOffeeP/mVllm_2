# 项目现状与证据

## 如何理解这里的“当前”

本页更新日期为 **2026-10-13**，只读核查起始 Mac 基线为 `59dee2d1`，训练机为 `main@3f200461`，详见[现场报告](results/remote-state-refresh-20261013.md)。工程能力依据代码及仓库验收记录；环境、数据引用和限定模型文件位置已刷新，模型质量仍依据历史结果。同日后续新建正式Conda环境并通过检查，见[部署记录](results/conda-environment-setup-20261013.md)。没有加载模型或重新评测，过去的服务成功不表示今天有同一服务在运行。

项目任务仍由[唯一台账](project-todo.md)维护。本页是现状与证据摘要，不另列一套执行任务、优先级或授权。

**2026-10-15 实施增量**：按已确认[模型测评方案](model-evaluation.md)及[实施计划](plans/model-evaluation-implementation.md)，本机已实现批次 A/B 的纯语义评分、冻结判读导入、base/成功折来源登记和正式开发接线，独立合成复核通过，整体验证证据见[实施记录](results/evaluation-development-implementation-20261015.md)。后续 C/D/E 续接独立语义评分、匿名发包/封存、性能事件导入/受控 session 和按用途准入；实际合成验证与独立核查状态以[唯一台账](project-todo.md)为准。旧 strict 协议保留原定义，semantic-v4.1 / semantic-holdout-v4.1 / performance-v1 分别显式选择；真实独立 holdout、评审模型隔离和五分钟性能验收尚未完成。用户已选新准入统一新质量加性能，停止旧 strict 新晋级/服务写入，既有批准/alias只按原绑定读取与幂等恢复。本轮没有刷新训练机、模型或数据，上列现场事实日期仍为 2026-10-13。

同日续补的设计选择已确认：base/trained 真实来源分支、成功折不可变快照且父训练保持 partial、匿名受限多 Agent 评审，以及不授正式服务资格的受控性能加载。评审默认两个独立 Agent 加分歧第三仲裁，可预先配置更多；不再要求双真人。执行配置现已确认：评审在当前Mac使用本地Ollama Qwen3.5 9B＋Ornith-1.5 9B，仅匿名回答、不外发；基座沿用当前项目并现场核验。统计、视频规格、超时和预算见[测评方案](model-evaluation.md)。来源登记、开发与独立评分入口、受控性能 session/事件证据和准入绑定已接线；受控评审 worker/固定 broker 与全局 ambiguous 拒绝机制已接线；当前 sandbox 探针和评审 receipt 仍为合成，部署/tokenizer receipt 与实际 runtime collector 工程已接线，真实资产和独立审计映射未验真时请求前拒绝；显示端双签名接收/核验工程也已接入，外部可信客户端/测点、GPU测量和现场运行 attestation 仍未验收。本轮全synthetic不得passed。本轮没有启动评审模型判读、模型加载或使用真实 test。

## 已记录的机器与资产位置

2026-10-13已通过SSH核对训练机、代码目录、正式store和基座的指定位置。训练机工作区与LlamaFactory子模块干净；只读核查起始版本59dee2d1比现场main领先5提交；之后的本地文档提交由Git追溯，本轮没有同步。后续连接仍先核对状态，不直接同步覆盖。

| 位置 | 记录值与用途 |
| --- | --- |
| 本机 | macOS 开发、审查 UI 及结果复核；用 uv 调用已部署的 Mac Python 3.11.x |
| 训练机 | `liuyang@100.70.83.68:22`，主机名 `dell-Precision-3660` |
| 训练机代码目录 | `/home/liuyang/文档/mVllm_2` |
| 正式store | `/data/mVllm_2`，与代码checkout分开 |
| 基座位置 | `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`；2026-10-16四片SHA已对应官方固定HF revision；配置/tokenizer已核，但构造代码有1处偏差、加载可用性未验 |

通过已有OpenSSH配置、密钥或SSH agent连接：`ssh liuyang@100.70.83.68`。在该机器项目根目录直接使用已按 Linux GPU 锁核验、匹配 checkout 的 Conda Python 3.11.x 执行数据及模型说明中的命令；连接前明确命令、输入/输出和资源。凭据不入Git，删除/覆盖远端文件、切换环境、停止已有任务或push/merge仍按项目授权处理。同日用户追加授权新环境部署，已单独验收；后续同步和模型运行仍需对应授权。

## 工程能力与真实验收

| 范围 | 已有事实 | 尚不能证明的内容 |
| --- | --- | --- |
| 数据处理 | 显式七阶段、ROI/采样媒体、完整审查包、封存和数据引用门；有真实小样本与迁移验签证据 | 全量新批次已重建，或所有媒体已进入新 store |
| 正式身份与记录 | 五类完整身份；DVC数据管理、Git/YAML输入定义、MLflow实际运行与模型记录 | 旧模型目录自动成为新completed或passed对象 |
| 训练与评测 | 逐折/三折、独立full、validation、holdout推理及授权评分已接线并有合成验证；当前训练执行证据绑定adapter | 新体系真实GPU训练或最终独立test通过；另备merged不能直接成为正式登记产物 |
| 模型与服务 | Registry评测绑定、alias、唯一部署目标及冻结Prompt准入；受控加载器验证 | 新体系合格真实模型已加载并成功提供GPU/HTTP服务 |
| 部署环境 | 两平台锁与doctor已有验收；2026-10-13新Conda mvllm2全锁、依赖、CUDA可见及正式源码绑定检查通过；既有Linux部署脚本仍创建venv | 真实媒体和模型工作负载、训练成功或模型质量通过 |
| 备份恢复 | 小对象跨机与store级异根恢复有证据 | 真实硬盘、大型权重、SQLite及外部媒体/基座组合灾难恢复可用 |

正式运行环境：已建立Conda `mvllm2`（Python3.11.17），解释器为 `/home/liuyang/miniconda3/envs/mvllm2/bin/python`；GPU锁241项一致、依赖检查和doctor通过，LlamaFactory绑定正式main@3f200461。agent/cpm45及历史mirror venv保留，但不作为此次正式环境验收目标。Mac继续使用独立Mac锁及uv；本次CUDA可见与模块导入不证明实际模型或训练工作负载成功。 详见[本轮部署验收](results/conda-environment-setup-20261013.md)。

工程迁移已按确认范围合并并同步正式代码，证据见[最终集成记录第66–67节](results/version-control-migration/verification.md)。原公共CLI的退役范围见[入口清单](results/version-control-migration/entrypoint-map.md)；共享业务库和历史读取依赖仍有用途，不能删除整个旧包。

## 数据与Prompt的落点

| 正式身份 | 已确认迁移状态 | 历史来源 | 使用边界 |
| --- | --- | --- | --- |
| `data-v4.1-r1` | superseded | `v4.1.0-760050fad303` | 恢复历史引用，不建立新训练引用 |
| `data-v4.1-r2` | active | `v4.1.0-ecb5aeb9657c` | 新引用仍须在线校验许可、状态与内容 |
| `prompt-v4.1-r1` | 已登记正式定义 | 已确认历史Prompt复制迁移 | 实际训练按完整身份冻结，不任意换Prompt复用评测结论 |

这不是隐式“默认版本”清单。r1/r2生命周期、划分计数及外部媒体路径已于2026-10-13只读核对；Prompt仍依据历史迁移证据，本轮未重验内容。r1/r2复制保留原payload及划分，其中仍有外部媒体引用；不能按迁移完成删除旧workspace。正式记录在 `<store>/data/releases/<完整身份>/` 与 `records/prompts/`，映射和生命周期决定见[对象映射](results/version-control-migration/object-mapping.yaml)，内容验签见[验证第20–24及43节](results/version-control-migration/verification.md)。

Phase2历史train发布有1678个唯一媒体，三折train/validation记录为1253/425、1014/664、1186/492。基础发布有1275条，三折为850/425、830/445、929/346。数据来源和详细统计见[Phase2发布记录](results/v4_1_phase2_development_release/README.md)及[有效视图审计记录](results/v4_1_phase1_effective_view_audit/README.md)；不同发布分数不能直接作单变量因果比较。

## 历史模型成果

以下均为开发侧历史证据，不能当作最终test成绩或本轮新推理。

| 对象 | 样本口径 | 历史结果 | 结论 |
| --- | --- | --- | --- |
| Fold0中间发布 `v4.1-agent-pipeline-fold0-r1` | Phase2 Fold0 validation，425条 | strict valid 100%；joint 41.18%；clip_state 56.00% | 输出结构与旧服务/Agent链路已有基础，任务质量与production资格未通过 |
| concise三折 | Phase2 validation，1581条 | valid 79.63%；joint 32.07%；clip_state 35.80% | 322条非法输出，临界未断裂及已断裂召回均0%，类别坍缩和契约退化未解决 |
| visual三折的merged BF16路线 | 基础发布开发侧，1216条 | valid 97.12%；joint 40.21%；clip_state 49.67% | 已有预测曾按严格解析器复算一致，不表示对应权重今天可加载 |

来源为[旧发布身份](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[历史服务记录](results/v4_1_agent_pipeline_fold0_r1/README.md)、[concise报告](results/v4_1_prompt_concise_cv_v1_seed3411/README.md)、[visual报告](results/v4_1_0_760050fad303_20260724_visual/README.md)及[开发证据预检](results/model-diagnostics-preflight-20260913.json)。

2026-10-13现场核查：旧current仍指向Fold0发布，其adapter和merged索引10个分片在场；基座索引4个分片在场。限定run目录中concise缺权重、visual未找到，不代表全盘丢失。指定store的records/models、training、evaluations及默认MLflow路径未创建；用户说明尚未开展新体系正式业务流程，这符合阶段预期，不作为迁移失败。首次正式运行时仍需明确Registry配置根。旧current与旧Registry身份不授予新alias或passed。细节和限制见[现场报告](results/remote-state-refresh-20261013.md)；模型质量、旧预测及历史恢复调查仍以原证据日期为准。

2026-10-16补充限定只读核验：训练机仍为干净 `main@3f200461`，本轮起始Mac `a0f1e1ab` 比它多17个提交，未同步。基座23个白名单文件及旧Fold0 adapter完整SHA已核；前序已确认四片权重与官方main观察一致，后续固定revision比对及代码差异见下；未补造来源声明或登记模型。指定store的model/train/eval与默认MLflow仍未创建。minimal试点归档缺逐样本记录副本，原run只stat未读；未删除文件，真实备份/恢复仍缺准确根路径。该核验不刷新2026-10-13 GPU环境验收，不运行模型；见[本轮推进记录](results/todo-preparation-progress-20261016.md)。

2026-10-16后续固定来源比对已完成：HF `daef484c35ec93210ec93c5e901f8f3e9b78ee34`的配置、tokenizer、processor与四权重身份相符，官方ModelScope历史树解释了README和额外配置来源。唯一代码偏差为实际基座构造函数新增`self.post_init()`；后续已静态核定框架用途，历史来源/动机追查按用户要求取消，实际运行影响未验（见[核验收口](results/minicpm-postinit-origin-purpose-20261016.md)）；未覆盖原文件、补造来源声明或登记模型。7个仓内代码文件仅做AST闭包，没有执行远程代码。详见[固定来源核验](results/minicpm-fixed-source-audit-20261016.md)。

## 仍需独立解决的缺口

- **模型测评与诊断**：流程、质量门及四项前置选择已确认，见[测评方案](model-evaluation.md)；来源/成功折登记、纯语义评分、离线判读导入和逐折开发门已实现并经合成验证；独立最终语义评分、发包/封存、exposed/consumed、受控性能事件与按用途准入已接线；真实多 Agent 隔离判读、新独立 holdout、GPU性能采集与显示端可信证据仍未验收。执行配置已确认；现场来源摘要/交付参数及隔离须核验，实际执行另获授权；canary和任意替换训练Prompt不是现成接口。没有对应权重时不据历史报告安排推理。
- **独立test资格**：既定21个test source已找到，但旧测试发布曾暴露，20个source有媒体凭据关联；余下source也未证实具备独立使用资格。禁止用旧测试调参或仅改名重新获得资格。
- **真实质量与服务**：训练成功、严格评测通过、最终质量、production批准和GPU服务成功分别取得真实证据，不互相替代。
- **清理与恢复**：未完成引用、归档和备份证明的旧媒体/权重仍保留；大型及外部依赖组合恢复不能用小对象测试替代。

只读刷新和正式Conda环境绑定已完成；本轮 A/B 及后续 C/D/E 工程实施已获授权；接线和合成验证状态以 TODO 为准，用户当前明确禁止真实模型评测或使用 test。下一步核验候选模型来源、完整来源组映射、交付参数及运行预算，取得适用授权后按 baseline、完整单折、完整三折执行。真实模型任务尚未执行，具体任务和操作授权以唯一台账为准。

## 证据应怎样保留

[设计与决定](plans/2026-09-01-readable-version-control-design.md)、[ADR](adr/ADR-0001.md)、[已确认Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)描述确认的规则；[对象映射](results/version-control-migration/object-mapping.yaml)、[历史摘要](results/version-control-migration/history-summary.yaml)、[验证记录](results/version-control-migration/verification.md)描述实际发生的事实。

模型资料从[证据包索引](results/model_evidence/README.md)查找；本地五份轻量README/MANIFEST存在不等于训练机原始日志、预测和权重完整，也不是删除放行单。原始结果、摘要和证据不要因概览文档被替换而一起删除。
