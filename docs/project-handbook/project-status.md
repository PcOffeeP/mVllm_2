# 项目现状与证据

## 如何理解这里的“当前”

本页整理日期为 **2026-10-12**，本批修复所据本地代码起点为 `389c797e`，具体ROI/支持声明修复提交由 `git log -- pipeline/scripts/roi_annotation_app.py` 追溯。工程能力依据当前代码及仓库验收记录；训练机文件、模型和运行环境的最近现场记录来自 **2026-09-14**，本轮没有 SSH 刷新，也没有加载模型或重新评测。过去的服务成功不表示今天有同一服务在运行。

项目任务仍由原[唯一台账](../project-todo.md)维护。本页是证据摘要，不再另列一套执行任务、优先级或授权。

## 已记录的机器与资产位置

这些位置来自已有双机配置和2026-09-14记录，本轮未验证在线状态、目录存在性或工作区干净程度。首次连接先核对两端分支、HEAD、未提交修改和独有提交，不直接同步覆盖。

| 位置 | 记录值与用途 |
| --- | --- |
| 本机 | macOS 开发、审查 UI 及结果复核；用 uv 调用已部署的 Mac Python 3.11.x |
| 训练机 | `liuyang@100.70.83.68:22`，主机名 `dell-Precision-3660` |
| 训练机代码目录 | `/home/liuyang/文档/mVllm_2` |
| 正式store历史落点 | `/data/mVllm_2`，与代码checkout分开 |
| 基座历史位置 | `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`；来源修订与加载可用性仍需核定 |

通过已有OpenSSH配置、密钥或SSH agent连接：`ssh liuyang@100.70.83.68`。在该机器项目根目录直接使用已按 Linux GPU 锁核验、匹配 checkout 的 Conda Python 3.11.x 执行数据及模型说明中的命令；连接前明确命令、输入/输出和资源。凭据不入Git，删除/覆盖远端文件、切换环境、停止已有任务或push/merge仍按项目授权处理。上述连接信息不授权本轮连接，也不表示已完成训练机刷新。

## 工程能力与真实验收

| 范围 | 已有事实 | 尚不能证明的内容 |
| --- | --- | --- |
| 数据处理 | 显式七阶段、ROI/采样媒体、完整审查包、封存和数据引用门；有真实小样本与迁移验签证据 | 全量新批次已重建，或所有媒体已进入新 store |
| 正式身份与记录 | 五类完整身份；DVC数据管理、Git/YAML输入定义、MLflow实际运行与模型记录 | 旧模型目录自动成为新completed或passed对象 |
| 训练与评测 | 逐折/三折、独立full、validation、holdout推理及授权评分已接线并有合成验证；当前训练执行证据绑定adapter | 新体系真实GPU训练或最终独立test通过；另备merged不能直接成为正式登记产物 |
| 模型与服务 | Registry评测绑定、alias、唯一部署目标及冻结Prompt准入；受控加载器验证 | 新体系合格真实模型已加载并成功提供GPU/HTTP服务 |
| 部署环境 | Mac 和 Linux GPU 的依赖锁及部署脚本、doctor 已有验收；部署脚本创建新环境，Linux 模式为 venv | 当前实际使用的 Conda 环境已按 Linux GPU 锁核验，或正式解释器已切换且绑定今天的正确 checkout |
| 备份恢复 | 小对象跨机与store级异根恢复有证据 | 真实硬盘、大型权重、SQLite及外部媒体/基座组合灾难恢复可用 |

工程迁移已按确认范围合并并同步正式代码，证据见[最终集成记录第66–67节](../results/version-control-migration/verification.md)。原公共CLI的退役范围见[入口清单](../results/version-control-migration/entrypoint-map.md)；共享业务库和历史读取依赖仍有用途，不能删除整个旧包。

## 数据与Prompt的落点

| 正式身份 | 已确认迁移状态 | 历史来源 | 使用边界 |
| --- | --- | --- | --- |
| `data-v4.1-r1` | superseded | `v4.1.0-760050fad303` | 恢复历史引用，不建立新训练引用 |
| `data-v4.1-r2` | active | `v4.1.0-ecb5aeb9657c` | 新引用仍须在线校验许可、状态与内容 |
| `prompt-v4.1-r1` | 已登记正式定义 | 已确认历史Prompt复制迁移 | 实际训练按完整身份冻结，不任意换Prompt复用评测结论 |

这不是隐式“默认版本”清单，也未刷新今天的在线状态。r1/r2复制保留原payload及划分，其中仍有外部媒体引用；不能按迁移完成删除旧workspace。正式记录在 `<store>/data/releases/<完整身份>/` 与 `records/prompts/`，映射和生命周期决定见[对象映射](../results/version-control-migration/object-mapping.yaml)，内容验签见[验证第20–24及43节](../results/version-control-migration/verification.md)。

Phase2历史train发布有1678个唯一媒体，三折train/validation记录为1253/425、1014/664、1186/492。基础发布有1275条，三折为850/425、830/445、929/346。数据来源和详细统计见[Phase2发布记录](../results/v4_1_phase2_development_release/README.md)及[有效视图审计记录](../results/v4_1_phase1_effective_view_audit/README.md)；不同发布分数不能直接作单变量因果比较。

## 历史模型成果

以下均为开发侧历史证据，不能当作最终test成绩或本轮新推理。

| 对象 | 样本口径 | 历史结果 | 结论 |
| --- | --- | --- | --- |
| Fold0中间发布 `v4.1-agent-pipeline-fold0-r1` | Phase2 Fold0 validation，425条 | strict valid 100%；joint 41.18%；clip_state 56.00% | 输出结构与旧服务/Agent链路已有基础，任务质量与production资格未通过 |
| concise三折 | Phase2 validation，1581条 | valid 79.63%；joint 32.07%；clip_state 35.80% | 322条非法输出，临界未断裂及已断裂召回均0%，类别坍缩和契约退化未解决 |
| visual三折的merged BF16路线 | 基础发布开发侧，1216条 | valid 97.12%；joint 40.21%；clip_state 49.67% | 已有预测曾按严格解析器复算一致，不表示对应权重今天可加载 |

来源为[旧发布身份](../../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[历史服务记录](../results/v4_1_agent_pipeline_fold0_r1/README.md)、[concise报告](../results/v4_1_prompt_concise_cv_v1_seed3411/README.md)、[visual报告](../results/v4_1_0_760050fad303_20260724_visual/README.md)及[开发证据预检](../results/model-diagnostics-preflight-20260913.json)。

2026-09-14资产记录表明旧Fold0发布文件与若干实验adapter在约定位置存在，但未加载验证；concise/visual三折权重的约定位置有缺口，concise原始预测也缺失。旧current与旧Registry只是历史身份，不授予新alias或passed。详细现场记录保存在[验证第67节](../results/version-control-migration/verification.md)，此前限定调查见[模型位置核查](../results/model-location-followup-20260913.json)及[恢复身份目标](../results/model-recovery-targets-20260913.json)。

## 仍需独立解决的缺口

- **模型诊断方案**：新单折基线方向、开发侧阈值及资源尚待确认；canary和任意交叉替换训练Prompt不是现成接口。没有对应权重时不据历史报告安排推理。
- **独立test资格**：既定21个test source已找到，但旧测试发布曾暴露，20个source有媒体凭据关联；余下source也未证实具备独立使用资格。禁止用旧测试调参或仅改名重新获得资格。
- **正式运行环境**：新环境历史验收通过，但该记录不证明当前 Conda 环境合格。训练机实际运行继续使用对应 Conda Python 3.11.x；其锁定依赖、editable 来源与最终 checkout 需刷新核定。Mac 使用独立 Mac 锁及 uv 调用方式，不能据轻量检查认定 GPU 环境可用。
- **真实质量与服务**：训练成功、严格评测通过、最终质量、production批准和GPU服务成功分别取得真实证据，不互相替代。
- **清理与恢复**：未完成引用、归档和备份证明的旧媒体/权重仍保留；大型及外部依赖组合恢复不能用小对象测试替代。

下一轮首先刷新训练机只读事实，具体任务和允许操作以唯一台账为准。本套文档没有启动上述工作。

## 证据应怎样保留

[设计与决定](../plans/2026-09-01-readable-version-control-design.md)、[ADR](../adr/ADR-0001.md)、[已确认Spec](../tasks/2026-09-07-readable-version-control-migration/spec.md)描述确认的规则；[对象映射](../results/version-control-migration/object-mapping.yaml)、[历史摘要](../results/version-control-migration/history-summary.yaml)、[验证记录](../results/version-control-migration/verification.md)描述实际发生的事实。

模型资料从[证据包索引](../results/model_evidence/README.md)查找；本地五份轻量README/MANIFEST存在不等于训练机原始日志、预测和权重完整，也不是删除放行单。原始结果、摘要和证据不要因概览文档被替换而一起删除。
