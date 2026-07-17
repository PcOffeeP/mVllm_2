# Project Agent Instructions

关联文档：

- [docs/DATA_PROCESSING_RUNBOOK.md](docs/DATA_PROCESSING_RUNBOOK.md)
- [finetune/README.md](finetune/README.md)
- [README.md](README.md)

## 双机工作机制

- 当前电脑用于项目开发、代码查看、结果文件检查、静态分析、文档整理和结论汇总。
- 实际模型训练、GPU 推理、评测跑分、长时间数据处理，以及任何依赖 4090 显卡的任务，必须在另一台训练电脑上执行。
- 当前电脑上看到的训练目录、日志、指标、预测文件和报告，视为从训练电脑同步或复制过来的结果产物；Agent 可以基于这些产物做效果分析，但不得默认当前电脑能复现实验。
- 当需要判断模型实际效果时，优先使用训练电脑产出的真实评测结果、预测样例、指标文件和日志，而不是仅凭本机可运行的轻量检查。
- 如果当前电脑缺少 checkpoint、LoRA adapter、merged model、预测样例或评测指标，应将结论标记为“证据不足”，并明确需要在训练电脑上补跑或补同步的内容。
- 不要在当前电脑上启动重训练、GPU 推理或长评测任务；如需这些操作，应生成可在训练电脑执行的命令、任务单或检查清单。

## 训练机 SSH 连接

- SSH 目标：`100.70.83.68`
- SSH 用户：`liuyang`
- SSH 端口：`22`
- 系统主机名：`dell-Precision-3660`
- 远程用户目录：`/home/liuyang`
- 远程项目目录：`/home/liuyang/文档/mVllm_2`
- 本机 `~/.ssh/config` 已配置上述目标和用户；认证使用本机已有的 OpenSSH 密钥或 SSH agent，不在仓库中保存私钥、口令或其他凭据。
- 交互连接命令：`ssh 100.70.83.68`
- 在项目目录执行单条命令：`ssh 100.70.83.68 "cd '/home/liuyang/文档/mVllm_2' && <command>"`
- 需要训练、GPU 推理、完整评测或长时间数据处理时，通过该 SSH 连接在训练机执行；连接前先明确命令、输入、输出位置和预计资源占用。
- 默认只操作远程项目目录及明确指定的训练产物。删除或覆盖远程文件、修改系统配置、安装系统级依赖、停止已有任务等高风险操作，必须先获得用户明确授权。

## 训练结果验收口径

- `train_loss` / `eval_loss` 下降只能证明训练目标收敛，不能单独证明模型任务效果好。
- 断裂检测模型的实际验收应至少查看：JSON/schema 合法率、`has_fracture` 准确性、type/location 指标、interval/time 命中率、joint success rate、典型预测样例和失败样例。
- 对 LoRA/merged 模型做结论前，应确认实际加载的模型路径、checkpoint step、adapter 文件、metadata 和评测结果彼此一致。
- 如果训练目录中的 metadata 指向旧实验、缺少 adapter/checkpoint，或评测结果无法对应到当前模型，应优先指出产物链路问题，而不是给出正向效果结论。
