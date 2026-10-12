<!-- DOCUMENT-CONTRACT
Purpose: 解释项目业务链路、双机角色及主要实现之间的关系。
Scope: 业务流程、模块与产物关系、训练机连接及实现背景。
Must Preserve:
- 历史实现说明与现行操作入口分开。
- 双机路径和真实模型证据边界明确。
Non-goals:
- 不替代项目任务台账或领域运行手册。
-->

# mVllm_2 Project Guide

mVllm_2 将材料拉伸视频治理为来源可追踪、标签可审查的 V4.1 样本，基于 MiniCPM-V-4.5 进行 LoRA 训练、严格评测和模型服务交付。正式数据工程迁移已经交付；真实模型质量、独立测试使用资格和整机恢复分别验收，不能由工程交付状态推定。

## 项目入口

- [项目台账](project-todo.md)：唯一现状、执行次序、阻塞条件和交接入口。
- [数据运行手册](DATA_PROCESSING_RUNBOOK.md)：输入准备、七阶段、人工审查交接、封存及 test 数据边界。
- [versioning 索引](../versioning/SCRIPTS.md)：五类完整身份、数据输入契约、Prompt、训练、评测、Registry 及备份接口。
- [训练手册](../finetune/README.md)：冻结配置、真实训练、逐折评测和 full/holdout 验收规范。
- [服务手册](INFERENCE_SERVICE_RUNBOOK.md)：显式 alias、service-mode、冻结 Prompt 和服务验证。
- [架构说明](../ARCHITECTURE.md)：模块关系与系统边界；[迁移入口清单](results/version-control-migration/entrypoint-map.md)记录实际切换范围。

## 业务链路与实现

| 环节 | 现行入口及输入 | 主要产物与下游 |
| --- | --- | --- |
| 原始输入冻结 | `versioning data source`；显式视频、tags/mapping、既定 split | store 内 `data/working/BATCH/source/`，供 ROI 使用；不重新随机划分 |
| ROI 人工决定与物化 | 显式 metadata/output/project-root 的 ROI UI；`versioning data roi` | 完整人工决定及裁剪媒体、冻结决定；供子视频使用 |
| 子视频与采样帧 | `versioning data subvideo`；ROI、候选契约、历史参考、真实处理器 | 候选视频、采样帧、实际映射和排除证据；供审查导出使用 |
| 人工审查 | `review_export` → 完整包 UI → `review_import` | 完整回收文件、标签与证据绑定；供发布使用 |
| 数据发布 | `versioning data release/release_validate`；原 inputs、批次、完整 data 身份 | 不可覆盖的 `data/releases/<data>/payload/` 与 release 元数据，供训练绑定 |
| Prompt 与训练准备 | `versioning prompt create` 或已确认 mapping 复制迁移；`train prepare/validate` | `records/prompts/<prompt>.yaml`、`workspace/runs/<train>/input/`，固定数据、Prompt、配置、环境、媒体和基座摘要 |
| 真实模型训练 | 训练机 `versioning train run/export`；冻结输入 | MLflow Run、真实 adapter、training-evidence 和 `records/training/<train>/manifest.yaml` |
| 模型登记与严格评测 | `versioning model register`；`eval prepare/validate/run/export`，full 另有授权 score | Registry 数值 Model Version、正式评测 Run 与 `records/evaluations/<eval>/manifest.yaml`；验签后 finalize/alias |
| 服务物化与交付 | `versioning model current`；显式 root/alias/service-mode | `workspace/models/current` 权重及 materialized 绑定；服务再次在线验签并加载 |
| 备份与恢复 | `versioning backup create/verify/transfer/restore`；显式源、快照及隔离目标 | catalog 和验签快照；恢复不重置身份、holdout 消费或自动选择服务 current |

数据工作阶段目录由 `versioning/data_pipeline.py` 管理，test 分支由 `holdout_pipeline.py` 隔离路由。新生成开发数据的 payload 自包含媒体；已迁移的历史发布仍可能引用旧 workspace 外部媒体，复制迁移不等于媒体全量搬运。训练准备必须核对对应 receipt 或原 data-inputs 与真实媒体根。

新体系使用 `<kind>-v<协议>-r<N>` 完整身份，kind 仅为 data/prompt/train/model/eval。摘要校验内容，不成为版本身份。根目录、输入和版本缺失或漂移即停止，不选择隐式当前版本。数据 release、Prompt 及冻结输入不能原地改写。

## 业务规则与证据边界

ROI 保留原时间轴；fixed_roi 精确 3:4 裁剪，no_crop 通过 padding 保留全画面。子视频模块中的 v3 是保留的算法/provenance 名称，V4.1 发布与四字段校验仍由现行业务契约负责。候选包括事件附近、事件前、事件后与稳定未断裂窗口；具体数量由真实时长、事件和采样门决定，不能把历史数量作为每批固定要求。算法与参数见 `pipeline/v3_candidate_plan.py` 和 `pipeline/v3_candidate_media.py`。

train 数据分支使用开发成员进行三折训练/验证，独立 full 训练另冻结开发全集；test 数据分支要求独立来源清单、全量人工审查和 owner-only 真值。数据存在不等于未暴露或具有独立测试资格；test 发布拒绝训练引用，claim 与 score 遵守一次性授权边界。具体规则由运行手册和训练规范定义。

模型登记依据实际训练执行证据，正式评测保存真实逐样本记录并验签，服务依据 MLflow Registry alias、模型 manifest 和唯一 deploy_target。三折模型组只能比较/聚合，不能自动成为唯一部署目标。`pipeline/model_registry/current.json` 与旧哈希模型名是历史记录，不再作为新服务身份权威。

服务 analysis 的 system/user 正文来自所选模型的训练冻结 Prompt，正式定义、训练 artifact 与 passed eval 必须一致。输出为 `clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`；权威业务契约为 `pipeline/contracts/tensile_vlm_v4_1.json`。CPU 合成用例、轻量验签和旧中间服务成功都不能证明新体系真实模型合格或 GPU 服务可用。

## 双机工作流

Mac 用于代码检查、文档、ROI/完整包审查 UI 和轻量核验；训练机用于训练、GPU 推理、完整评测及长时间数据处理。当前电脑上的权重/指标/日志视为同步结果，缺少模型与评测匹配证据时结论为证据不足。

训练机连接信息：

- SSH 用户与端口：`liuyang@100.70.83.68:22`，系统主机名 `dell-Precision-3660`。
- 远程用户目录：`/home/liuyang`；远程项目目录：`/home/liuyang/文档/mVllm_2`。
- 交互连接：`ssh 100.70.83.68`。
- 在项目目录执行已明确的单条命令：`ssh 100.70.83.68 "cd '/home/liuyang/文档/mVllm_2' && <command>"`。
- 使用本机现有 OpenSSH 配置、密钥或 SSH agent，不把凭据保存到仓库。

连接前明确命令、输入/输出和资源预算；两端分别检查分支、HEAD、未提交修改与独有提交，不强制覆盖或对齐。push/merge、远程删除或覆盖、停止已有任务等依照 [AGENTS](../AGENTS.md) 的明确授权规则。上述主机信息是连接配置，不能据此推定训练机当前在线、工作区干净或环境已切换。

`workspace/` 是 Git 忽略的产物层；代码、小型 manifest 和报告入 Git，大型媒体/权重与受限 test 材料不入 Git。新体系 store 的 `workspace/mlflow/` 保存执行与 Registry；冻结证据、数据 payload 及外部基座/媒体分别核对。恢复 store 不证明外部依赖可用。

## 历史与待验收事项

[迁移设计](plans/2026-09-01-readable-version-control-design.md)与[实施台账](plans/2026-09-01-readable-version-control-implementation.md)保存已确认架构和决定；[验证记录](results/version-control-migration/verification.md)、[交接记录](results/version-control-migration/handoff.md)保存实际执行范围。旧业务函数仍可能被调用，公开 CLI 退役不代表整个 pipeline/finetune 包可删除。

历史 `v4.1-agent-pipeline-fold0-r1` 中间模型曾有真实媒体服务与 Agent 链路证据，见[历史报告](results/v4_1_agent_pipeline_fold0_r1/README.md)；其质量限制和旧路径不授予新 alias 服务资格。正式模型质量、独立 test 资格、真实服务成功路径、外部媒体自包含和大型组合恢复的剩余事项以台账为准。本文不保存临时 HEAD、活动实验或将旧调查写成今天现场状态。
