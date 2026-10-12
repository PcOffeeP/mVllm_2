<!-- DOCUMENT-CONTRACT
Purpose: 提供现行训练与评测入口导航，并保留历史实验的身份与质量证据。
Scope: 新入口的输入输出与执行边界、历史训练配置和结果参考。
Must Preserve:
- 三折沿用原数据划分；历史采样与结果不能冒充新体系执行证据。
- 训练、合并、GPU推理在训练机执行；质量结论必须绑定真实产物。
- 明确已停用CLI和历史指针不得用于现行操作。
Non-goals:
- 不复制 versioning/SCRIPTS.md 的完整参数规范或项目任务台账。
-->

# V4.1 微调、合并与评测

本目录维护 MiniCPM-V-4.5 的 V4.1 三折及独立全量 LoRA 微调、模型合并和严格评测入口。
训练、模型合并和 GPU 推理必须在训练电脑执行；本机只复核代码和已同步的轻量结果。

## 现行训练与评测入口

正式入口为 `python -m versioning train` 和 `python -m versioning eval`，使用 `prepare / validate / run / export`；holdout 另以显式 `eval score --executor` 进入授权评分。完整参数与配置字段见 [三折训练说明](../versioning/SCRIPTS.md#三折训练准备与执行)、[正式验证集测评说明](../versioning/SCRIPTS.md#正式验证集测评)、[独立全量训练](../versioning/SCRIPTS.md#独立全量训练)及 [holdout 验收说明](../versioning/SCRIPTS.md#full-模型的独立-holdout-验收)。

| 环节 | 显式输入 | 产物与下一步 |
| --- | --- | --- |
| 训练准备、校验 | store、完整train/data/prompt身份、三折训练YAML、环境YAML、代码提交、实际媒体根；七阶段发布另给原data-inputs | `workspace/runs/<train>/input/`冻结六份数据、Prompt、配置及摘要；validate复验后才可run |
| 训练执行、导出 | 已验证的同一train及store；实际训练授权 | 真实执行器与MLflow父子Run、每折adapter；完成后导出`records/training/<train>/manifest.yaml` |
| 模型登记 | 完成的train及明确的model身份、scope和artifact声明；使用`versioning model register` | MLflow完整model身份与数值版本，作为评测准备输入；登记不等于质量通过 |
| 验证集评测准备、校验 | 完整eval/model/data身份、Registry数值版本、评价YAML、代码提交及实际媒体根 | `workspace/evaluations/<eval>/input/evaluation.yaml`冻结模型、Prompt、样本与评分器；validate复验 |
| 评测执行、导出 | 已冻结的eval及store；实际GPU评测授权 | 每折预测/失败/summary，MLflow父Run汇总；完成后导出`records/evaluations/<eval>/manifest.yaml` |

三折可以分次执行：prepare/validate 冻结同一个完整 train 版本后，在训练机按 fold0/1/2 逐次执行；命令及参数见[三折训练说明](../versioning/SCRIPTS.md#三折训练准备与执行)。

`--fold`仅接受0/1/2，且只用于run；full拒绝该参数。不带`--fold`执行整组，续办只执行未完成折。三折共享父Run，成功但缺折时为`partial`（沿用状态契约映射为MLflow原生`KILLED`，表示本次调用已结束、整组未完成；不表示已成功子Run失败）。每折的`execution-evidence.json`及子Run摘要绑定冻结输入、指标和adapter；续办时必须保留并验签本地输入/输出及MLflow副本。已完成折只返回核验结果，不重训；三折齐全后才汇总、标记completed并导出正式训练manifest。失败/中断、残留输出、篡改或并发冲突立即拒绝，不自动覆盖或续训；完整训练后的导出故障仍用`train export`恢复。工程合成验证不代表实际模型效果或真实训练获授权。

默认一个train包含原fold0/1/2，不扩大旧source-aware 3k采样。独立全量训练另建train版本，以 `train prepare --scope full` 冻结同一开发release的共同全集，每个候选仅训练一次，只产出full模型，不创建fold子Run或使用holdout选checkpoint。评测Prompt来自模型绑定；模型必须先登记，不能用裸目录绕过Registry。正式validation支持single_fold或cross_validation；full模型的holdout先绑定独立媒体清单、预注册和claim，run仅媒体推理，score核验同一executor及冻结规则后才读受限真值，完成时消费授权，普通导出仅含汇总。代码接线与合成CPU验证不等于真实训练或holdout验收通过；无合格模型时不能沿用旧模型的工程通过结论。

`train_build_dataset.py`、`train_prepare_run.py`、`train_with_contract.py`及`eval_run.py`的公开CLI已停用，`--help`仅给迁移提示；直接脚本和模块启动都会拒绝旧参数。新入口通过`build_versioned_datasets`、版本化准备/执行函数、`run_training`及严格评分器复用业务实现。私有历史测试函数不作为操作入口。

## 执行环境与模型晋级

训练、合并和 GPU 推理使用训练机的 Linux GPU 环境。环境准备、校验及双机角色见[项目指南](../docs/project-guide.md)；脚本职责见[环境脚本索引](../scripts/SCRIPTS.md)。实际执行前核对环境绑定的 checkout、冻结配置、基座、代码提交及输出位置，不能仅凭本机依赖检查宣布真实执行通过。

正式训练完成后，模型登记必须绑定实际 adapter/checkpoint、训练范围、冻结 Prompt 和权重身份；正式评测再精确绑定 model 身份与 Registry 数值版本。`model finalize` 单向绑定评测结论，candidate/production alias 均拒绝未 finalize 的模型。三折模型组不能作为单一部署目标；服务准入、人工批准、完整下载和 manifest 校验仍须分别满足。精确接口见 [versioning/SCRIPTS.md](../versioning/SCRIPTS.md)，服务入口见 [pipeline/SCRIPTS.md](../pipeline/SCRIPTS.md)。

训练与评测的公开 `create/fold-start/fold-end/summary/aggregate/complete/manifest` 记录 CLI 已停用；底层 Python 记录原语供正式执行器调用，手工状态或历史 summary 不能替代真实执行证据。正式 manifest 由执行器完成或显式 export 恢复导出，不得把旧实验目录改名后补写为 completed/passed。

## 评测口径

严格评测按被评模型冻结的契约解释字段，至少检查：

- 运行失败数与严格 JSON/schema 合法率；
- `clip_state`、`fracture_mechanism`、`fracture_site`、`special_case` 字段准确率及四字段联合准确率；
- `clip_state` 混淆表、类别分布和各状态召回，尤其是 `临界未断裂` 是否被错误当成已发生断裂；
- `inside_gauge`、`outside_gauge_non_root`、`grip_root` 的混淆；
- 典型成功、失败和非法输出样例。

训练 loss 和 eval loss 下降只能证明训练目标收敛。没有对应的逐样本预测和任务指标时，不得声称模型达到可部署效果；解析器不得自动补必填字段掩盖非法输出。不同 release、采样、Prompt、seed 或工具版本的历史分数不能直接作为单变量因果对比。

validation 的开发指标不替代最终 holdout 的七项冻结门槛。full 模型独立验收必须满足来源资格、封存、预注册、一次性 claim、同一 executor 授权评分及完整证据绑定；评分后无论质量通过或失败均消费授权。阈值与定义见[模型门禁背景](../docs/MODEL_GATE_BASELINE.md#4-新体系门禁的实际起点)，接口与受限输出规则见 [holdout 验收说明](../versioning/SCRIPTS.md#full-模型的独立-holdout-验收)。

## 历史实验参考

本节只索引已保存的实验身份和结果。旧哈希 release、实验目录、`active_data_release.json`、旧 registry `current.json` 及旧 current 指向均保留其原始语义；不能用于现行完整版本身份选择或服务准入。历史脚本与配置从 Git 历史查询，不在本文提供停用 CLI 的操作命令。

| 证据范围 | 历史身份与数据 | 已保存结论及来源 |
| --- | --- | --- |
| 基础开发数据 | `v4.1.0-760050fad303`，1275 条；契约 `tensile-vlm/v4.1` | [数据发布说明](../docs/V4_1_DATA_RELEASES.md)保留新旧身份映射；身份迁移不等于模型重新验收 |
| Phase2 开发数据 | `v4.1.0-ecb5aeb9657c`，1678 条 | 同上；现行训练显式选择封存 data 版本，不能通过旧活跃指针默认选取 |
| 旧 Fold0 中间发布 | `v4.1-agent-pipeline-fold0-r1`，coverage-first、seed3407；Phase2 Fold0 validation 425 条 | strict valid 100%、joint correct 41.18%、clip_state 56.00%；[模型门禁背景](../docs/MODEL_GATE_BASELINE.md)记录身份与资产限制，[历史服务证据](../docs/results/v4_1_agent_pipeline_fold0_r1/README.md)记录旧链路通过 |
| concise 三折 | `v4.1-prompt-concise-cv-v1-seed3411`；Phase2 validation 共1581条 | valid 79.63%、joint 32.07%、clip_state 35.80%；322 条严格非法，临界未断裂与已断裂召回均为 0%；[三折报告](../docs/results/v4_1_prompt_concise_cv_v1_seed3411/README.md)保留训练、配置和摘要哈希 |
| 固定字段 Prompt 实验 | `v4.1-prompt-minimal-v1-seed3411` | 历史 Prompt revision、训练输入及 experiment contract 见[模型证据包](../docs/results/model_evidence/v4.1-prompt-minimal-v1-seed3411/README.md)，不能用交叉 Prompt 建议替代模型绑定的冻结 Prompt |
| 语言层基线 | `v4.1-language-cv-v1-seed3407`，对应 `20260723` 运行 | 配置、旧路径及复现脚本由 Git 历史追溯；结果位置见[评测结果目录](results/README.md) |

历史 visual 三折运行 `v4_1_0_760050fad303_20260724_visual` 使用基础开发 release 的 1216 个唯一验证候选，各路线运行失败均为 0：

| 推理路线 | 严格合法率 | 联合准确率 | 状态准确率 | 机制准确率 | 位置准确率 |
| --- | ---: | ---: | ---: | ---: | ---: |
| merged BF16 | 97.12% | 40.21% | 49.67% | 50.66% | 56.66% |
| merged 后重新 4-bit | 98.19% | 34.87% | 47.53% | 48.68% | 51.23% |
| 4-bit 基座直挂 adapter | 100.00% | 37.42% | 47.37% | 49.92% | 53.45% |

BF16 的断裂相关三状态宏平均召回率为 24.54%，已断裂召回率为 9.00%；35 条严格非法输出全部漏掉 `special_case`，没有运行异常或 token 截断。验证目标中没有 `无法判断` 或非空 `special_case`，因此该运行不能证明这些能力。各条 4-bit 路线是独立模型变体，不能继承 BF16 的验收结论。完整逐折指标、非法输出、契约与模型哈希见[视觉证据冻结报告](../docs/results/v4_1_0_760050fad303_20260724_visual/README.md)。

以上均为历史开发侧报告，本文整理没有重跑训练、推理或评分。[模型门禁背景](../docs/MODEL_GATE_BASELINE.md)的资产调查日期为 2026-09-14：当时旧发布实体在场，但没有证据证明已有满足新体系最终门禁的真实模型，concise/visual 三折权重在约定位置未找到。历史报告称训练、合并或 checkpoint 保留完成，不等于现在这些权重仍可加载；本轮未刷新训练机。旧 Fold0 中间模型不能声明为 final、full-data、independent-test-passed 或 production-approved。

## 证据与资产保留

模型结果检索从[模型证据包索引](../docs/results/model_evidence/README.md)进入；实际模型资产、归档验收和删除边界见[模型清单](../docs/MODEL_INVENTORY.md)，轻量现场背景见[模型门禁背景](../docs/MODEL_GATE_BASELINE.md)。训练机的大型权重、逐样本记录和完整日志不入 Git；轻量 manifest 与完整 SHA-256 清单用于绑定身份，不能替代权重、媒体或原始预测。历史 `metadata` 哈希模式只用于单元测试，不构成权重身份。

历史部署报告记录过旧发布来源的 5 个 checkpoint 和 concise 三折的 15 个 checkpoint 保留政策；后续资产调查已有缺口，不能据旧数量假定全部仍在场或允许删除。新训练在任务分析完成前不得自动删除 checkpoint，归档与清理仍由项目台账的 MODEL-ARCHIVE 管理。

类别坍缩、契约退化、最终训练、test 使用资格及真实服务验收的当前状态和下一动作统一见[项目台账](../docs/project-todo.md)。历史报告中的 canary、交叉 Prompt、采样配额和早停建议属于诊断候选，不能直接转成当前执行步骤或已批准门槛。

## V2 历史复现

V2 的 Git 引用 `tensile-vlm-v2-final` / `archive/v2`、冻结数据 `data/archive/training_releases/v2.0.0-1dab1e5e` 及配置 `MiniCPM/config/archive/v2/` 仅用于封存版本追溯。复现须使用对应封存代码与 frozen 数据根，不在现行主分支混用 V2 活动指针或旧评测入口。

## 关联文档

- [仓库总览](../README.md)与[项目台账](../docs/project-todo.md)：当前入口、状态、依赖和下一步。
- [数据处理运行手册](../docs/DATA_PROCESSING_RUNBOOK.md)：输入准备、七阶段、审查往返及发布封存。
- [versioning 命令索引](../versioning/SCRIPTS.md)与[finetune 脚本索引](SCRIPTS.md)：正式接口及被复用模块职责。
- [现行服务入口](../pipeline/SCRIPTS.md)：Registry alias、冻结 Prompt 和服务准入。
- [模型门禁背景](../docs/MODEL_GATE_BASELINE.md)、[模型证据包](../docs/results/model_evidence/README.md)及[评测结果目录](results/README.md)：真实资产边界与历史质量证据。

历史数据隔离、模型资产生命周期与 checkpoint 清理文档在提交 `d964eeb5` 归档；需要详细决策时从 Git 历史查阅。
