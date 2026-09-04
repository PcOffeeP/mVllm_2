# versioning 入口与模块索引

统一入口为 `python -m versioning`；正式版本参数必须使用完整
`<kind>-v<协议>-r<N>` 身份，缺失或非法引用会以非零状态停止。

| CLI 领域 | 主要模块 | 作用 |
| --- | --- | --- |
| `data` | `data_pipeline.py`、`data_release.py`、`holdout.py` | 七阶段 DVC 数据 pipeline、封存、训练引用门、预注册冻结与 holdout claim |
| `prompt` | `prompts.py` | 注册不可变 Prompt，并冻结/校验训练 input 副本 |
| `train` | `mlflow_train.py` | 训练父 Run、三折子 Run、汇总与完成门 |
| `eval` | `mlflow_eval.py`、`manifest.py` | 测评父子 Run、Registry 精确引用、holdout 消费、结论门与 manifest 单向导出 |
| `model` | `registry.py` | `mVllm2` 两阶段 register/finalize、备份范围、批准、alias 与物化 |
| `backup` | `backup.py` | 离线备份 catalog、完整性验证与显式目标恢复 |

`cli.py` 只编排上述领域模块，不实现第二套状态或身份规则；`__main__.py` 仅转发统一入口。
完整参数运行 `python -m versioning <领域> --help` 查看。

所有正式写入都要求显式版本；CLI 的项目数据根必须显式传入，Registry、eval、alias 与
manifest 在操作时在线复验其 train/data/eval 血缘。测试中的临时 store 推断不属于正式入口。
