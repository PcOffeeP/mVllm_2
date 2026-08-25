# finetune 脚本

根目录只保留当前训练链路和公共运行时。

| 文件 | 作用 |
| --- | --- |
| `train_build_dataset.py` | 构建当前固定 Prompt 实验数据 |
| `train_prepare_run.py` | 冻结当前实验配置 |
| `train_with_contract.py` | 启动当前 LLaMA-Factory 训练 |
| `eval_run.py` | 运行严格 V4.1 评测 |
| `train_monitor_run.py` | 查看训练进度 |
| `eval_audit_effective_views.py` | 审计模型实际采样帧 |
| `release_validate.py` | 校验冻结数据发布 |
| `train_build_source_aware_dataset.py` | 当前实验复用的数据构建模块 |
| `v4_1_runtime.py` | 公共校验与运行时模块，不直接执行 |

已完成、已替代和历史复现入口统一放在 [`archive/`](archive/README.md)。
