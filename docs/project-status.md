# 项目现状

项目已确认新一轮断裂标签基准，正在进行人工标注，评价体系尚待设计；新标签尚未接入现有数据和模型链路。

## 下一步

1. 按[断裂标签说明](label.md)完成人工标注，实际完成范围尚未核验。
2. 以新标签为基础设计评价体系，并结合标注结果确认具体评价要求。

任务进度、完成条件和限制见 [TODO](TODO.md)。数据接入、契约升级和代码适配需要后续设计；当前 v4.1 契约及运行时保持冻结。

## 历史信息

项目已建立视频数据处理、人工审查、版本管理、模型训练、评测和服务的工程链路，也有旧 v4.1 模型的开发侧结果。已有结果和工程验证不能代表新标签的模型效果或真实服务验收；旧评价指标不能直接用于新标签。更多细节见[数据流程](data-workflow.md)、[模型流程](model-workflow.md)和[模型清单](results/model-inventory.md)。

### 已记录的机器与资产位置

本机用于开发、文档和轻量检查；训练、GPU 推理、完整评测及长时间数据处理在训练机进行。以下位置来自历史记录，使用前须核对实际状态。

| 位置 | 路径或地址 |
| --- | --- |
| 训练机 | `liuyang@100.70.83.68:22` |
| 训练机代码目录 | `/home/liuyang/文档/mVllm_2` |
| 正式 store | `/home/liuyang/文档/mVllm_2/store` |
| 基座 | `/home/liuyang/文档/mVllm_2/base-models/minicpmv4_5` |
| 训练机 Python | `/home/liuyang/miniconda3/envs/mvllm2/bin/python` |
| 备份总目录 | `/data/mVllm_2-backups/`；每次备份使用独立子目录 |

### 项目本地目录布局

项目已取消本地 `workspace/` 根段；历史路径与当前目录的对应关系如下。`store` 是独立存储根，不属于此映射；历史记录中的旧路径不代表当前磁盘状态。

| 历史路径 | 当前路径 |
| --- | --- |
| `workspace/data` | `data` |
| `workspace/runs` | `trains` |
| `workspace/models` | `models` |
| `workspace/mlflow` | `mlflow` |
| `workspace/evaluations` | `evaluations` |
| `workspace/base-source-audit` | `audits/base-source-audit` |
| `workspace/review-environment` | `audits/review-environment` |
| `workspace/data-staging` | `data-staging` |
| `workspace/data-rebuild` | `data-rebuild` |
| `models/minicpmv4_5`、`models/minicpm-v-4.5`（旧基座目录） | `base-models/minicpmv4_5` |
