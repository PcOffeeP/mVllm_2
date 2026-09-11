# versioning 入口与模块索引

统一入口为 `python -m versioning`；正式版本参数必须使用完整
`<kind>-v<协议>-r<N>` 身份，缺失或非法引用会以非零状态停止。

| CLI 领域 | 主要模块 | 作用 |
| --- | --- | --- |
| `data` | `data_pipeline.py`、`data_release.py`、`holdout.py` | 七阶段 DVC 数据 pipeline、封存、训练引用门、预注册冻结与 holdout claim |
| `prompt` | `prompts.py` | 注册不可变 Prompt，并冻结/校验训练 input 副本 |
| `train` | `mlflow_train.py` | 训练父 Run、三折子 Run、汇总与完成门 |
| `eval` | `mlflow_eval.py`、`manifest.py` | 测评父子 Run、Registry 精确引用、holdout 消费、结论门与 eval manifest 单向导出 |
| `model` | `registry.py`、`manifest.py`、`materialize.py` | `mVllm2` 两阶段 register/finalize、model manifest、唯一部署目标 gate、alias 与 `models/current` 原子物化 |
| `backup` | `backup.py` | 离线备份 catalog、完整性验证与显式目标恢复 |
| `migration` | `migration.py` | 从显式 object mapping 执行 Prompt/Data 只读预检或迁移，从声明 entry 纯构建或固定路径发布 history-summary |

`cli.py` 只编排上述领域模块，不实现第二套状态或身份规则；`__main__.py` 仅转发统一入口。
完整参数运行 `python -m versioning <领域> --help` 查看。
迁移命令不会扫描 sibling 或选择“当前”对象：Prompt/Data 动作必须显式给出
`tensile-migration/object-mapping/v1` 映射文件，history 动作必须显式给出 entry YAML 列表，
六个 migration 动作都必须显式给出 `--root`。映射或 entry 中的重复 YAML 键会被拒绝；
预检报告为 `blocked` 时保留 JSON 拒因并以非零状态退出。

所有正式写入都要求显式版本；CLI 的项目数据根必须显式传入，Registry、eval、alias 与
manifest 在操作时在线复验其 train/data/eval 血缘。测试中的临时 store 推断不属于正式入口。
服务物化必须显式给出 `service_mode` 与 alias；三折模型组不具备唯一 `deploy_target`，只能用于
比较和聚合测评，不能成为 candidate、production 或 `models/current`。

模型备份按 `offline_backup_scope` 实际裁剪文件：`adapter` 只包含
`materialized.yaml` 与 Registry 声明的 adapter 路径；`production_bundle`
包含声明的 adapter 与 merged 路径。每个作用域模型的严格 manifest 一并恢复到
`records/models/<id>/manifest.yaml`；MLflow store 仅保存 SQLite、上述声明训练产物
和已绑定正式测评产物，不通过整树复制夹带 adapter 模型的 merged。
