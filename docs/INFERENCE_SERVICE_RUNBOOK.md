# 推理服务运行手册

现行服务通过 MLflow Registry 的显式 alias 和 service-mode 解析合格模型，绑定完整模型身份、唯一部署权重和训练冻结 Prompt。服务启动不补资格、不选择裸权重目录。当前工程证据覆盖门禁与受控加载；新体系真实合格模型加载和真实媒体推理成功路径尚未验收，具体状态见[项目台账](project-todo.md)。

## 适用范围与前置产物

所有 GPU 加载和实际推理在训练机执行，连接位置见[双机工作流](project-guide.md#双机工作流)。先明确输入、输出、设备和显存预算，核对 checkout、实际解释器及正在运行的任务。本手册提供操作接口，不授权启动推理或停止已有任务。

服务使用同一个 versioning `STORE`，必须已具备：

| 输入 | 来源与检查 |
| --- | --- |
| 完整 model 身份及数值 Model Version | `versioning model register/finalize` 与 Registry，绑定真实训练及正式评测证据 |
| `candidate` 或 `production` alias | 已按确认方案和资格门设置；development 显式 candidate，production 必须 production |
| 模型 manifest 与部署权重 | `records/models/<model>/manifest.yaml` 和声明的唯一 deploy_target；三折组不能直接部署 |
| 正式训练 Prompt | `records/prompts/<prompt>.yaml`；与训练 input 及 passed eval 的冻结正文/schema 内容一致 |
| 基座、MLflow artifact 与物化缓存 | 与绑定摘要和实际文件完整一致；adapter 还需原冻结基座可用 |
| 启动 JSON | 下文从 resolver 的真实绑定和运行依赖填写，不从旧 deployment 复制身份 |

登记、评测与批准接口见[versioning 索引](../versioning/SCRIPTS.md)和[训练手册](../finetune/README.md)。缺正式评测、备份范围或其他资格时停在对应前置工作，不能从 `LlamaFactory/saves/` 选最近模型绕过。历史 current.json 和旧中间服务报告不作为新服务身份源。

## 显式物化与静态门禁

由操作者在训练机设置 `PYTHON`（实际项目解释器绝对路径）、`STORE`（store 绝对路径），从代码仓库执行：

```sh
"$PYTHON" -m versioning model current --root "$STORE" --alias candidate --service-mode development
"$PYTHON" scripts/serve_manage_model_registry.py --root "$STORE" resolve-current --alias candidate --service-mode development
"$PYTHON" scripts/serve_validate_delivery.py --root "$STORE" --alias candidate --service-mode development
```

current 验签 alias 资格并原子物化 `workspace/models/current`。resolver/交付校验返回完整模型身份、数值 Model Version、base_model_version、内容 fingerprint 和冻结 Prompt。`runtime_verified: false` 表示只完成静态资格/内容检查，尚未执行推理。校验可能复制 MLflow artifact 到临时目录并扫描缓存、基座和源权重，磁盘及读取预算按实际产物核定。

production 操作须全部显式使用 `--alias production --service-mode production`，并已完成相应批准及备份门。不得自动晋级 candidate 或把 development 成功视为 production 批准。

## 准备部署配置

复制 [pipeline/server_deployment_manifest.example.json](../pipeline/server_deployment_manifest.example.json) 到明确的包外运行位置 `STARTUP`。依据上一步绑定填写：

- `model_version`、`adapter_version`：都为所选完整 model 身份。
- `base_model_version`：resolver 返回的真实基座身份/路径。
- `config_fingerprint`：该 root/alias/service-mode 的实际 fingerprint，包含冻结 Prompt 内容。
- `processor_version`、`transformers_version`、`llamafactory_version`、`max_frames`、`runtime_device`、`runtime_dtype`：实际安装/运行配置，不保留示例占位值；V4.1 采样上限为 8。

服务将训练 artifact、正式 Prompt 与 passed eval 的冻结 Prompt 逐字段核对，analysis 契约由其实际 system/user 正文派生，输出字段须与所选 V4.1 业务契约一致。客户端须使用对应动态契约，不能继续发送旧固定正文或旧 contract hash。部署字段结构不因迁移改变；启动参数和实际检查见 `pipeline/server_proxy.py`，完整服务绑定逻辑见 `pipeline/model_registry.py`。

## 训练机启动与预检

确认实际推理授权和可用资源后，设置包外 `STARTUP` 与明确 `PORT`，使用前台方式启动以保留加载错误。API key 来自受限运行环境文件或当前 shell，不能入 Git。V4.1 服务示例：

```sh
"$PYTHON" -m pipeline.server_proxy --root "$STORE" \
  --alias candidate --service-mode development \
  --contract-version tensile-vlm/v4.1 --deployment-manifest "$STARTUP" \
  --host 127.0.0.1 --port "$PORT"
```

服务先核验模型协议和部署身份，加载后重新解析绑定；加载期间 Registry 或内容漂移即拒绝。`--model` 裸目录接口已取消。端口由操作者核对，不能复用已占用端口或停止未知任务来腾资源。远程访问保持 loopback/SSH tunnel 边界。

在另一 shell 读取同一 API key 和 PORT 后预检：

```sh
curl --fail --silent --show-error \
  -H "Authorization: Bearer ${API_KEY}" \
  "http://127.0.0.1:${PORT}/v1/tensile/contract"
```

核对动态 `contract_version`、`contract_hash`、deployment_manifest 和 `model_registry`：完整 model 身份、数值 Model Version、fingerprint 均与启动绑定一致。HTTP 200 本身不证明身份正确、实际模型效果或可生产发布。

## 真实媒体 smoke 与客户端交接

`VIDEO` 来自已获使用授权且能追溯的实际视频绝对路径，不能为 convenience 读取受限 test 真值或使用未经授权测试材料。与服务选择同一 root、alias、模式、契约和 URL：

```sh
"$PYTHON" -m pipeline.scripts.serve_smoke --root "$STORE" \
  --alias candidate --service-mode development --contract-version tensile-vlm/v4.1 \
  --base-url "http://127.0.0.1:${PORT}" --video "$VIDEO"
```

smoke 通过同一 resolver 获取训练 Prompt 并构造请求，核对 preflight/response 的 Registry 身份与动态 contract hash。成功证据还应包含合法 V4.1 四字段、request ID、实际帧映射、tensor digest/shape 和部署运行身份。保留执行机器、代码版本、模型/Prompt/评测绑定、实际媒体来源、命令、日志及结果；smoke 证明服务链路，任务质量仍依据正式评测。

TensileAgent 或其他客户端须按同一绑定和动态契约配置，通过 doctor/兼容检查后交接；历史 `agent/config.v4_1.pre_acceptance.yaml` 及旧模型路径不自动适用于新模型。跨机使用 SSH tunnel，不能将开发端口直接当生产接口或静默回退到 V2。

## 停止、换模与故障处理

停止自己本次前台进程可用 Ctrl-C；既有服务或他人任务的停止必须有明确授权。换模前核对服务及任务状态，按批准的停止/启动顺序操作；新 alias、权重、Prompt 和部署 JSON 需一起复验，不能在运行中覆盖不可变 release 或假定设置 alias 后已运行进程自动切换。

| 失败 | 处理 |
| --- | --- |
| alias/模式、正式评测或唯一部署目标不合格 | 回到 Registry 前置任务；不加载裸路径绕过 |
| manifest、artifact、基座或 Prompt 漂移 | 停止使用并核对正式来源及冻结证据；不手改摘要让其通过 |
| config_fingerprint/协议/运行版本不一致 | 根据实际 resolver 与环境重核配置，不能沿用历史 deployment 身份 |
| GPU 加载、真实预处理或推理失败 | 保存真实错误和资源状态，保持未验收，不用 CPU 替身结果代替 |
| 预检成功但响应身份不一致 | 拒绝交付，核对实际端口、进程和加载模型 |

## 历史验证与当前限制

[历史 Fold0 中间服务报告](results/v4_1_agent_pipeline_fold0_r1/README.md)保留模型文件完整性、真实媒体 smoke 与 Agent 调用证据及质量门未通过的事实；旧裸路径、current.json、Stage B 开发例外和 V2 回滚命令退出当前操作正文。需要调查原命令时查 Git 历史，不据旧结果恢复宽松启动。

[迁移验证记录](results/version-control-migration/verification.md)保存新 Registry 门禁、受控 loader 和 CPU 合成验证范围；这些不证明真实模型加载、GPU HTTP 推理、运行进程切换或 production 质量。真实成功路径与剩余交接事项以[唯一台账](project-todo.md)为准。
