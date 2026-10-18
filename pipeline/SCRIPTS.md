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
- 2026-07 数据与视觉诊断工具放在 `scripts/diagnostics/`：14 个脚本于 2026-10-18 从 `codeup/diagnostics/data-visual-audit` @ `bcdf4f36` 迁入，仅供历史证据复核，当期未接入主链（不属现行数据/服务入口）；这些脚本原先读写 `finetune/results/diagnostics/` 下的数据，数据未随迁，正文路径可能已失效，见各文件顶部「迁入说明」。

日常操作只需要查看 `scripts/SCRIPTS.md`。

## 候选规划与媒体物化的契约边界

- [`v3_candidate_plan.py`](v3_candidate_plan.py) 校验 `tensile-vlm/v3`，负责候选窗口与标签规划，不读写媒体。legacy [`rebuild_data.py`](scripts/rebuild_data.py) 在此阶段加载 `tensile_vlm_v3.json`。
- [`v3_candidate_media.py`](v3_candidate_media.py) 消费候选计划，物化子视频与 MiniCPM 帧映射，并将计划、处理器指纹及编码配置绑定到媒体身份。后续 V4.1 审查和训练发布复用这些候选与媒体，分别加载 `tensile_vlm_v4_1.json`。

两个模块的 `v3` 名称对应候选层职责，不能据此推断最终发布契约。现行正式数据入口仍是 `python -m versioning data`，显式使用完整 `data-v<协议>-r<N>` 身份；legacy 重建入口仅用于理解上述复用关系。流程说明见[数据指南](../docs/data-workflow.md#候选层与发布契约)。

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
