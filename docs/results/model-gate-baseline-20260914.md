<!-- DOCUMENT-CONTRACT
Purpose: 为后续模型诊断、训练和晋级提供可核查的实际模型背景。
Scope: 现存模型资产、历史效果、证据缺口及模型门禁依赖。
Must Preserve:
- 区分本轮现场文件事实、历史报告和未知项；存在不等于验签或可加载。
- 工程迁移通过不等于模型质量通过，不将旧身份或历史分数补写为新体系passed。
- train与test数据分支用途、原七门及单独执行授权不变。
Non-goals:
- 不替代项目TODO，不授权训练、受限测试或产物删除。
-->

# 模型资产与门禁现场核查（2026-09-14）

本文是当日现场核查档案，保留原始摘要与未知项。今天的工程状态和操作入口分别见[项目现状](../project-status.md)与[模型流程](../model-workflow.md)，不按本档案判断当前服务或文件是否在场。

核查日期：2026-09-14。范围为训练机 `/home/liuyang/文档/mVllm_2` 的 `models`、`workspace/models/releases`、`workspace/runs`，以及新正式 store `/data/mVllm_2` 的目录状态。调查时正式代码为 `f1b7d8a3`；工程候选已验证的业务代码为 `61effebd`。本次仅读取文件身份、路径、大小和非评测manifest，没有读取权重内容、预测或受限测试语义，没有加载模型或跑分。

**当前可以保留使用的资产背景是旧 Fold0 中间发布及若干实验产物；没有证据证明已经拥有满足新体系最终模型门禁的真实模型。** 保留文件不等于本轮验证了模型可用。工程分支合并只交付版本身份、DVC、MLflow及入口链路，模型质量任务继续独立推进。

## 1. 唯一旧发布模型

| 项目 | 本轮确认事实 |
| --- | --- |
| 历史发布身份 | `v4.1-agent-pipeline-fold0-r1`；本轮 `workspace/models/releases` 仅有该发布目录 |
| 旧 current 指向 | `workspace/models/current` 解析到 `workspace/models/releases/v4.1-agent-pipeline-fold0-r1`，目标存在；仅是历史指针，不作为新服务准入 |
| 原训练来源 | `v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`；coverage-first、seed3407、1125 optimizer steps、fold0 |
| 原数据身份 | `v4.1.0-ecb5aeb9657c`，对应迁移后的 train 数据版本背景；不因此自动生成新train/model身份 |
| 训练范围与批准 | `training_scope=fold0`、`full_data_final=false`、`production_approved=false` |
| 实体权重 | `adapter/adapter_model.safetensors` 为460430776字节；`merged/`下10个safetensors分片共17391890080字节；adapter/config及merged/config存在 |
| 身份文件 | `release-manifest.json` SHA256为`3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`，与前轮身份核查记录一致 |

历史报告记载该模型曾完成旧工程链路的合并权重验签、loopback服务、视频smoke及Agent调用；本次没有复跑这些步骤。另做只读现场检查，历史端口8002当时无TCP监听；GPU计算进程查询仅列出gnome-remote-desktop-daemon。未检查其他端口或请求模型API，不能据此断言整台机器没有其他服务。旧报告的工程通过不能迁移为新alias、production批准或新的正式eval passed。

来源：[历史交付配置](../../delivery/model_component.json)、[旧发布身份](../../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[前轮身份调查](model-recovery-targets-20260913.json)。

## 2. 其他实验资产与基座

以下实验目录均在训练机 `workspace/runs/` 下。本轮“adapter在场”仅为文件stat；“merged索引在场”不证明所有分片完整，更不证明当前可加载。

| 实验目录 | 本轮文件事实 | 后续定位 |
| --- | --- | --- |
| `v4.1-phase2-coverage-first-v1-seed3407` | fold0根adapter在场；另见checkpoint-250/1000/1050/1100/1125的adapter | 旧发布来源相关实验；训练终点1125与历史最佳checkpoint250是不同概念，不能混称 |
| `v4.1-phase2-coverage-first-v1-seed3411` | fold0 adapter、merged索引在场 | 历史采样对照 |
| `v4.1-phase2-coverage-fallback-v1-seed3413` | fold0 adapter、merged索引在场 | 历史回退采样对照 |
| `v4.1-phase2-source-aware-v1-seed3407` | fold0 adapter、merged索引在场 | 历史source-aware对照 |
| `v4.1-phase2-source-aware-v1-seed3411` | fold0 adapter、merged索引在场 | 历史source-aware对照 |
| `v4.1-prompt-minimal-v1-seed3411` | 根adapter、merged索引在场 | 历史Prompt实验；目录布局不同于fold0实验 |
| `v4.1-prompt-concise-v1-seed3411` | 仅input/reference，无本轮扫描的adapter或merged索引 | 不能代替concise三折产物 |
| `v4.1-prompt-concise-v2-seed3411` | 仅input，无本轮扫描的adapter或merged索引 | 同上 |
| concise-cv、visual-cv三折 | 本轮顶层运行目录未见对应实验；前轮约定三折merged路径均缺失 | “约定位置未找到”不等于证实全盘删除；不再持续全盘搜寻，不据报告虚构权重 |

MiniCPM-V-4.5基座位于 `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`，本轮4个safetensors分片在场。前轮已对29个文件做流式SHA256及分片结构核验：849个tensor与索引一致，内容清单摘要为`2ffb284ff1a0db561633e91c768c1a9732b33838147113004966c1ff112faa21`。这是[验证记录第61节](version-control-migration/verification.md)的历史验签，本轮未重算。下载备注的`master`不是可信固定上游修订，仍缺上游来源冻结证明；本地结构一致不等于模型可加载或来源可信。

本轮没有删除任何旧模型、checkpoint、索引、隐藏侧车或唯一源文件。清理继续归[MODEL-ARCHIVE台账](../project-todo.md)，本文不是删除放行单。

## 3. 已知效果：仅引用历史开发侧证据

| 模型／范围 | 数据与样本口径 | 历史结果 | 能得出的结论 |
| --- | --- | --- | --- |
| 旧发布r1，Fold0 | phase2 train数据分支的Fold0 validation，425条 | strict valid 100%；joint correct 41.18%；clip_state 56.00% | 输出契约稳定不等于任务效果达标，更不等于最终test通过 |
| concise-cv三折 | phase2三折validation，共1581条 | valid 79.63%；joint 32.07%；clip_state 35.80%；322条严格非法；临界未断裂、已断裂召回均0% | 类别坍缩及契约退化未解决，不晋级 |
| 历史visual三折 | 基础release的开发侧记录，共1216条 | valid 97.12%；joint 40.21%；clip_state 49.67% | 前轮按现行解析器复算已有预测与各折原摘要一致；没有新的模型推理 |

以上来源为[模型清单](model-inventory.md)、[concise三折报告](v4_1_prompt_concise_cv_v1_seed3411/README.md)和[开发记录预检](model-diagnostics-preflight-20260913.json)。concise原始逐样本预测尚未找回，不能将报告指标写成本轮独立复算结果。不同数据release、采样、Prompt、seed或工具版本下的指标不能直接作为单变量因果对比，也不能拿validation分数代替test评分。

旧交付配置中的Stage B/D/G质量未通过与production未批准事实继续保留。本文不读取或重述受限test逐样本内容。

## 4. 新体系门禁的实际起点

本轮确认 `/data/mVllm_2/workspace/mlflow` 和 `/data/mVllm_2/models` 不存在；该正式store仍以迁移数据、Prompt和轻量记录为主。验证目录里的MLflow Run、模型和passed结果使用合成对象，不能归入上述真实模型清单。旧发布manifest并未因此变成新体系的正式completed训练、model-v身份或可用alias。

后续必须区分以下事实：

1. **输入冻结**：显式选择完整data/prompt/train身份和实际媒体根，固定基座来源与内容、配置及代码。train数据分支用于三折训练/验证及全量训练；test数据分支仅用于最终独立测试。原字段值和历史身份不改名。
2. **训练执行证据**：已有单折入口可以按fold0/1/2分次执行；缺折保持partial，三折齐全才完成。full是独立训练范围。实际训练仍须单独授权，本次不启动。
3. **模型与正式评测绑定**：权重、adapter/checkpoint、训练配置、冻结Prompt、指标与模型身份必须对应；旧裸目录或历史报告不能直接补写为新completed／passed。单折或三折对照的开发门槛须在MODEL-DIAG方案获确认后冻结，不能自动套用test七门。
4. **最终test使用资格**：初始21个test source位置已找到；历史测试发布曾暴露，20个source有相关物化关联，余下source也未证实独立可用。既定划分不等于“未参与开发/调参”。新独立test的来源资格、完整人工审查、封存、预注册和一次性claim仍未就绪；旧已暴露测试不复测、不调参。
5. **晋级与服务**：正式eval、candidate/production及人工批准仍走原门禁。无合格alias时新服务入口拒绝启动，不因工程分支合并就给旧模型补发production资格。新服务真实加载/推理成功路径后续验收。

最终test沿用的七项冻结门槛如下，定义/分母/六位小数规则以[holdout_metrics.py](../../finetune/holdout_metrics.py)为准；这是未来验收要求，不是当前真实模型已通过的结果：

| 指标 | 比较方向与阈值 |
| --- | --- |
| 四状态macro recall | ≥0.4006 |
| 三种断裂相关状态macro recall | ≥0.3000 |
| joint correct rate | ≥0.3921 |
| runtime failure count | =0 |
| strict valid rate | =1.0000（实现为≥1，合法取值上界为1） |
| 已断裂 recall | ≥0.1500 |
| 未断裂 recall | ≥0.7000 |

七门不能只挑选一项通过；还须满足适用的输入、授权、身份和证据完整性条件。当前没有可据本次调查宣布这套最终test门禁通过的真实模型。

## 5. 后续工作与证据维护

当前分支按工程范围合并，不安排新的模型微调。后续由[项目TODO](../project-todo.md)继续管理MODEL-DIAG、HOLDOUT-BUILD、FINAL-TRAIN、MODEL-QUALITY：先明确诊断方案与所需原始证据，再按授权分次训练/开发验证；开发方案稳定、test就绪后才冻结full候选并做独立验收。实际命令以[训练与评测入口](../model-workflow.md)为准。

本轮现场探针及原始JSON只保存在本机临时目录，SHA和机器/退出记录见[迁移验证记录第67节](version-control-migration/verification.md)。本文保留必要摘要，不新建一份平行模型台账或复制大型结果文件。未来更新须标明哪些事实重新现场核实、哪些仍来自历史报告。
