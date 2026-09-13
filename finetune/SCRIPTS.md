<!-- DOCUMENT-CONTRACT
Purpose: 索引 finetune 中的执行器、校验模块与历史入口。
Scope: 文件职责及公开CLI的现行或退役状态。
Must Preserve:
- 业务函数保留与公开CLI可执行性分开说明。
Non-goals:
- 不保存实验质量结论和完整运行参数。
-->

# finetune 脚本

正式编排使用 `python -m versioning train/eval`，参数见 [versioning/SCRIPTS.md](../versioning/SCRIPTS.md)。本目录保留执行器、校验原语及历史业务；文件存在不代表CLI仍可执行。

| 文件 | 作用 |
| --- | --- |
| `train_build_dataset.py` | 公开CLI已停用；build_versioned_datasets供新入口冻结原三折或去重全量开发输入，历史构建函数保留 |
| `train_prepare_run.py` | 公开CLI已停用；版本化prepare/verify/execute函数供新训练入口调用 |
| `holdout_metrics.py` | 复用原Stage D七项冻结门槛与私有指标定义；输出公开二值gate，不读取数据或模型 |
| `eval_holdout.py` | 新入口full媒体推理及显式score授权评分；逐样本细节仅存受限目录，公开aggregate证据 |
| `train_with_contract.py` | 直接YAML启动CLI已停用；run_training接收新入口已冻结的内存配置 |
| `eval_run.py` | 裸model-dir CLI已停用；版本化评测函数与严格评分器供新入口调用 |
| `train_monitor_run.py` | 查看训练进度 |
| `eval_audit_effective_views.py` | 审计模型实际采样帧 |
| `release_validate.py` | 校验冻结数据发布 |
| `train_build_source_aware_dataset.py` | 历史source-aware采样及共享辅助函数，无独立main；新三折不扩大该采样 |
| `v4_1_runtime.py` | 公共校验与运行时模块，不直接执行 |

其他历史复现脚本见 [`archive/`](archive/README.md)。
