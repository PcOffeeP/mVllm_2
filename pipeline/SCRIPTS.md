<!-- DOCUMENT-CONTRACT
Purpose: 定位pipeline模块与命令，并说明服务入口的显式Registry接入步骤。
Scope: 模块索引、已合格模型物化、服务配置、启动和HTTP smoke。
Must Preserve:
- 服务使用显式root/alias/service-mode，production仅production，不接受原始模型路径回退。
- 资格验证、受控测试与真实推理证据分开，GPU操作遵守训练机授权边界。
Non-goals:
- 不替代模型登记、测评、备份和生产批准的权威规则。
-->

# pipeline Python 文件

- 根目录 `.py` 是当前数据、审核和服务共享模块，一般不直接执行。
- 当前可执行命令放在 [`scripts/`](scripts/SCRIPTS.md)。
- 历史命令放在 [`scripts/archive/`](scripts/archive/README.md)。

日常操作只需要查看 `scripts/SCRIPTS.md`。

## 服务入口（M5）

新服务必须显式选择store根、alias与模式。先完成正式train/eval、Registry登记与所需备份/批准，在store的records/models/保留该模型的正式manifest及records/prompts/中的训练Prompt，然后显式物化alias：

```sh
python -m versioning model current --root /absolute/store --alias candidate --service-mode development
```

模型登记与备份的模块索引、训练及评测用法见versioning/SCRIPTS.md；登记/备份的完整命令参数分别查python -m versioning model --help与python -m versioning backup --help；current从已通过资格门的Registry取权重。服务启动不会自行补资格或修复缓存。

用以下命令读取已通过资格和内容校验的绑定：
```sh
python scripts/serve_manage_model_registry.py --root /absolute/store resolve-current --alias candidate --service-mode development
python scripts/serve_validate_delivery.py --root /absolute/store --alias candidate --service-mode development
```
两者的runtime_verified=false表示没有启动推理。resolver会复制声明的MLflow artifact到临时目录并扫描缓存、源权重与基座内容，需要相应磁盘空间和读取时间。

复制server_deployment_manifest.example.json到明确的配置位置；从上述绑定填model_version、adapter_version（均为完整model身份）、base_model_version和fingerprint对应的config_fingerprint，其余字段填真实安装版本、processor类与运行设备/精度，不得保留占位值。模型Prompt的system/user/output_fields须与所选固定生产契约一致。

在训练机取得实际推理授权后启动：
```sh
python -m pipeline.server_proxy --root /absolute/store --alias candidate --service-mode development --contract-version tensile-vlm/v4.1 --deployment-manifest /absolute/startup.json
python -m pipeline.scripts.serve_smoke --root /absolute/store --alias candidate --service-mode development --contract-version tensile-vlm/v4.1 --video /absolute/authorized-video.mp4
```
production模式必须同时使用production alias。旧--model路径不再可用。preflight与分析响应携带model_registry，包含完整模型身份、数值Model Version和内容指纹；smoke核对这些信息后才接受结果。现有响应契约的11字段deployment_manifest保持原结构。当前验证仅覆盖合成小产物与受控loader，不证明真实模型推理或运行中进程已经切换。
