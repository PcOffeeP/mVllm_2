# 项目现状与证据

本页说明项目做到哪一步、已有证据能支持什么，以及机器和资产的已记录位置。当前任务及进度只在 [TODO](TODO.md) 维护；人工标注按[断裂标签说明](label.md)执行。

## 当前阶段

本轮主线是人工标注与新标签评价体系设计。新标签尚未接入数据或模型链路，v4.1 契约及运行时保持冻结；新版本实施当前仍暂停。实际人工标注完成范围尚未核验。

以下工程与资产结论来自既有记录：现场核查主要发生于 2026-10-13 至 2026-10-18，目录搬迁记录更新到 2026-10-21。本次文档整理未刷新训练机、加载模型或复跑评测。历史服务成功不表示今天同一服务仍在运行。

## 工程能力与真实验收

| 范围 | 已有证据 | 结论边界与详细来源 |
| --- | --- | --- |
| 数据处理与版本管理 | 数据七阶段、人工审查交接、封存、五类完整身份及引用校验已实现，保留真实小样本和迁移验签记录 | 不证明新标签数据已重建；见[迁移验证](results/version-control-migration/verification.md)及[入口清单](results/version-control-migration/entrypoint-map.md) |
| 训练与评测接线 | 逐折/full 训练、开发与独立语义评分、性能事件和准入绑定已有工程及合成验证 | 不等于新一轮真实训练、最终质量或真实性能通过；见[开发接线记录](results/evaluation-development-implementation-20261015.md)及[独立评分与性能记录](results/evaluation-independent-performance-admission-20261015.md) |
| 模型与服务 | Registry 绑定、alias、部署目标、冻结 Prompt 校验和受控加载器已有实现 | 历史批准不自动授予新版本资格；真实 GPU/HTTP 服务须有对应证据 |
| 环境与恢复 | 保留两平台依赖锁、环境检查入口和小对象/异根恢复记录 | 历史环境检查不证明今天仍合格，也不证明模型负载或大型权重组合恢复可用；操作入口见[模型流程](model-workflow.md) |

旧评测设计、已实现接口和本轮新标签分开理解：[模型评测设计](model-evaluation.md)针对 v4.1，新标签的评价口径仍待设计。旧 strict 记录保留原义；新准入统一要求新质量与性能证据，既有批准/alias 仅按原绑定读取与幂等恢复。本次不运行真实模型评测或使用 test。

## 已记录的机器与资产位置

以下是已记录位置，使用前应核对机器状态、当前分支和文件，不能直接据此同步或覆盖。

| 位置 | 记录值与用途 |
| --- | --- |
| 本机 | macOS：开发、审查 UI、轻量核验和结果复核；使用已部署的 Mac Python 3.11.x |
| 训练机 | `liuyang@100.70.83.68:22`，主机名 `dell-Precision-3660`；GPU 训练、推理、评测与长时间数据处理在此执行 |
| 训练机代码目录 | `/home/liuyang/文档/mVllm_2` |
| 正式 store | `/home/liuyang/文档/mVllm_2/store`；2026-10-17 归位记录，使用时显式指定根目录 |
| 备份总目录 | `/data/mVllm_2-backups/`；单次 `--backup-root` 使用其中独立子目录，不使用总目录本身 |
| 基座目录 | `/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5` |
| 已记录的正式 Conda 解释器 | `/home/liuyang/miniconda3/envs/mvllm2/bin/python`；历史环境名不能代替当前依赖和源码来源核验 |

连接使用已有 OpenSSH 密钥或 SSH agent：`ssh liuyang@100.70.83.68`。连接与操作约束见 [AGENTS.md](../AGENTS.md)，环境核验及执行入口见[模型流程](model-workflow.md)。历史 Conda 检查原始凭证已随前次清理移除，需要确认当前可用性时须重新核验。

## 项目本地目录布局

2026-10-21 起，项目本地布局取消 `workspace/` 根段。双端搬迁记录已完成，收口版本为 `316a1975`；这描述当时状态，不是本次重新检查。数据、训练、模型、基座、MLflow、评测、审计、暂存与重建落在仓库根目录下，均不入 Git。`store` 是独立存储根，不与这些目录互相替代。

| 历史路径 | 现行路径 |
| --- | --- |
| `workspace/data` | `data` |
| `workspace/runs` | `trains` |
| `workspace/models` | `models` |
| `workspace/mlflow` | `mlflow` |
| `workspace/evaluations`（含 `staging/`） | `evaluations` |
| `workspace/base-source-audit` | `audits/base-source-audit` |
| `workspace/review-environment` | `audits/review-environment` |
| `workspace/data-staging` | `data-staging` |
| `workspace/data-rebuild` | `data-rebuild` |
| `models/minicpmv4_5` / `models/minicpm-v-4.5`（基座） | `base-models/minicpmv4_5` |

`.compat/workspace` 与 `store/workspace/**` 不属此映射；`models/*` 的忽略规则仍只排除子项。历史报告、训练记录及冻结元数据保留路径原文，阅读时按上表换算，不把旧路径文本当作磁盘现状。

搬迁过程、验收数字、别名链接及人工回滚说明可在 Git 提交 `2f8cf09` 的本文件中查阅；对应仓库外材料位于 `~/pi-workspace/mVllm_2-relayout-20261021/`。历史回滚步骤与当时版本绑定，不能作为当前工作区的直接操作指令。

## 数据与 Prompt 的落点

已记录的旧版本包括：`data-v4.1-r1` 为 superseded，`data-v4.1-r2` 为 active，`prompt-v4.1-r1` 已登记正式定义。这不是默认版本清单；使用时仍须在线校验状态、许可、内容与完整身份，不能由历史状态推定当前状态。

- 版本映射、正式记录位置与迁移血缘见[对象映射](results/version-control-migration/object-mapping.yaml)和[迁移验证](results/version-control-migration/verification.md)。冻结记录含外部媒体路径，按上面的布局映射理解。
- 候选、来源视频、三折划分、试件分组及耗时外推集中见[训练数据台账](results/training-data-ledger-20261017.md)。用户已确认每个试样只对应一个来源视频；这是用户确认依据，不是独立物理验真。
- 基座固定 revision 的配置、tokenizer、processor 和权重身份见[固定来源核验](results/minicpm-fixed-source-audit-20261016.md)。实际构造代码新增 `self.post_init()` 的框架用途已静态核定，历史来源追查按用户要求取消；实际运行影响仍未验证，见[核验收口](results/minicpm-postinit-origin-purpose-20261016.md)。

## 历史模型成果

历史 Fold0、concise 三折和 visual 三折的结果分别对应不同实验、数据及处理口径。统一从[模型清单](results/model-inventory.md)、[R1 效果分析](results/model-r1-effect-profile-20261018.md)及[历史结果索引](results/INDEX.md)查阅，不在本页重复维护数值。

这些开发侧结果不能当作本轮新标签的质量或最终 test 成绩。历史可加载、已有预测和当前权重完整是不同结论；限定目录未找到文件也不能推断全盘丢失。原始现场范围见[训练机核查](results/remote-state-refresh-20261013.md)。旧 current/Registry 身份不自动授予新 alias 或 passed。

## 历史证据与后续设计

此前未结事项已按用户决定移除，后续遇到问题再按实际情况设计，不从历史记录自动恢复任务。旧测试来源曾暴露的限制仍是历史事实；将其改名不能恢复盲性，2026-10-17 用户决定的重建结论口径为非盲参考性，完整记载见 Git 提交 `2f8cf09` 的本文件。

规则依据见[版本体系设计](plans/2026-09-01-readable-version-control-design.md)、[ADR](adr/ADR-0001.md)与[迁移 Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)；实际发生的事见[历史摘要](results/version-control-migration/history-summary.yaml)和[迁移验证](results/version-control-migration/verification.md)。归档、备份和删除资格须有各自证据，本页压缩不构成资产删除许可。

本页随实际阶段或资产布局变化更新；被后续记录取代的过程细节留在 Git 历史，原始结果与必要证据继续保留。
