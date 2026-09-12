# V4.1 中间推理服务运行手册

> **历史操作与效果证据。** 下文裸模型路径、旧current.json和开发发布例外不能用于现行服务启动。现行服务必须经MLflow alias及service-mode校验，参数见[pipeline服务说明](../pipeline/SCRIPTS.md)；没有合格模型时明确拒绝。本文旧模型的真实运行结果不授予新体系模型资格，当前状态见[项目TODO](project-todo.md)。


> 当前状态：`v4.1-agent-pipeline-fold0-r1` 已在训练机完成模型哈希校验、真实媒体
> service smoke 和 TensileAgent 调用验证。它是 loopback-only 中间开发服务，不是
> production deployment。

本文用于在训练机 `100.70.83.68` 上启动、检查和停止当前 V4.1 推理服务。所有命令均在
`/home/liuyang/文档/mVllm_2` 下执行。

## 1. 当前部署身份

| 项目 | 值 |
| --- | --- |
| 模型名 | `v4.1-agent-pipeline-fold0-r1` |
| 模型入口 | `workspace/models/current/merged` |
| 发布目录 | `workspace/models/releases/v4.1-agent-pipeline-fold0-r1` |
| 契约 | `tensile-vlm/v4.1` |
| 契约 hash | `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab` |
| merged aggregate | `1f75e4f91db487273588c1e1c8bf867b20acdfc565c191d914915b366c4c1b1c` |
| Python | `/home/liuyang/miniconda3/envs/cpm45/bin/python` |
| 服务地址 | `127.0.0.1:8002` |
| 访问策略 | loopback / SSH tunnel only |
| production alias | 否 |

部署配置：

`pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json`

配置文件名保留原 Stage B 来源身份，文件内容中的当前模型身份已经更新为
`v4.1-agent-pipeline-fold0-r1`。历史报告中的旧路径和 acceptance ID 不做回写。

## 2. 启动前检查

```bash
cd '/home/liuyang/文档/mVllm_2'

git status --short
nvidia-smi
ss -ltnp | grep ':8002 ' || true

python3 scripts/serve_manage_model_registry.py validate --verify-hashes

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pytest \
  tests/test_model_registry.py \
  tests/test_serve_validate_delivery.py \
  tests/test_v4_1_service_contract.py -q
```

必须确认：

1. 没有训练、merge 或评测进程占用模型目录；
2. `workspace/models/current` 指向注册表声明的 release；
3. adapter 和 merged aggregate hash 与 release manifest 一致；
4. 8002 没有被其他服务占用；
5. GPU 空间足以加载 BF16 merged 模型。

不要从 `LlamaFactory/saves/` 选择“看起来最新”的目录启动服务。

## 3. 前台启动

```bash
cd '/home/liuyang/文档/mVllm_2'

export CUDA_VISIBLE_DEVICES=0
export DISABLE_VERSION_CHECK=1
export PYTHONPATH="$PWD/LlamaFactory/src:$PWD"
export API_KEY='替换为随机长字符串'

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pipeline.server_proxy \
  --model workspace/models/current/merged \
  --deployment-manifest pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json \
  --contract-version tensile-vlm/v4.1 \
  --host 127.0.0.1 \
  --port 8002
```

API key 只能保存在训练机权限 `0600` 的运行环境文件或当前 shell 中，不能提交到 Git。

## 4. 后台启动

当前运行目录：

`finetune/run_logs/v4_1_agent_pipeline_fold0_r1`

先创建凭据文件：

```bash
cd '/home/liuyang/文档/mVllm_2'
mkdir -p finetune/run_logs/v4_1_agent_pipeline_fold0_r1
umask 077
printf 'API_KEY=%s\n' '替换为随机长字符串' \
  > finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env
chmod 600 finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env
```

使用 tmux 启动：

```bash
tmux new-session -d -s v4-1-agent-pipeline-r1 \
  "cd '/home/liuyang/文档/mVllm_2' && \
   set -a && source finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env && set +a && \
   export CUDA_VISIBLE_DEVICES=0 && \
   export DISABLE_VERSION_CHECK=1 && \
   export PYTHONPATH='/home/liuyang/文档/mVllm_2/LlamaFactory/src:/home/liuyang/文档/mVllm_2' && \
   exec /home/liuyang/miniconda3/envs/cpm45/bin/python \
   -m pipeline.server_proxy \
   --model workspace/models/current/merged \
   --deployment-manifest pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json \
   --contract-version tensile-vlm/v4.1 \
   --host 127.0.0.1 --port 8002 \
   2>&1 | tee finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.log"
```

确认启动：

```bash
tmux ls
tail -n 50 finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.log
ss -ltnp | grep ':8002 '
nvidia-smi
```

## 5. 契约预检

```bash
set -a
source finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env
set +a

curl --fail --silent --show-error \
  -H "Authorization: Bearer ${API_KEY}" \
  http://127.0.0.1:8002/v1/tensile/contract \
  | /home/liuyang/miniconda3/envs/cpm45/bin/python -m json.tool
```

返回值必须同时包含正确的：

- `contract_version` 和 `contract_hash`；
- `model_version=v4.1-agent-pipeline-fold0-r1`；
- merged aggregate hash；
- processor、transformers、LLaMA-Factory、device 和 dtype 身份。

任何身份漂移都应 fail closed，不能只依据 HTTP 200 判断服务可用。

## 6. 真实媒体 smoke

```bash
set -a
source finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env
set +a

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pipeline.scripts.serve_smoke \
  --base-url http://127.0.0.1:8002 \
  --video data/archive/.compat/workspace/data/08_incremental_review/round_01/03_subvideos/video_0029_focus_3s_80pct.mp4 \
  --contract-version tensile-vlm/v4.1
```

成功必须同时证明：

- 输出满足 V4.1 严格四字段；
- request ID 存在；
- 实际帧表存在；
- tensor digest 和 tensor shape 存在；
- 响应中的 deployment identity 与预检一致。

Smoke 只验证服务与契约链路，不是模型任务效果验收。

## 7. TensileAgent 接入

TensileAgent 预验收配置：

`agent/config.v4_1.pre_acceptance.yaml`

当 Agent 与服务在同一训练机上运行时：

```bash
cd '/home/liuyang/文档/TensileAgent-acceptance'

set -a
source '/home/liuyang/文档/mVllm_2/finetune/run_logs/v4_1_agent_pipeline_fold0_r1/service.env'
set +a
export INFERENCE_API_KEY="${API_KEY}"

/home/liuyang/miniconda3/envs/agent/bin/python \
  -m agent.doctor \
  --config agent/config.v4_1.pre_acceptance.yaml
```

跨机器接入必须通过 SSH tunnel，不能把 8002 直接暴露为生产接口。Agent doctor 成功后
才允许启动任务；不得自动回退到 V2。

## 8. 停止与重启

正常停止：

```bash
tmux send-keys -t v4-1-agent-pipeline-r1 C-c
tmux ls
```

等待会话正常退出后确认：

```bash
ss -ltnp | grep ':8002 ' || true
nvidia-smi
```

更换 current 模型时，先停止服务，再验证新 release 的完整 hash、deployment manifest 和
Agent 兼容性；不能在服务运行中原地覆盖 release 目录。

## 9. V2 历史回滚

V2 只作为历史回滚对象：

- merged：
  `workspace/models/archive/v2/v2.0.0-1dab1e5e-20260719/full/merged`
- manifest：pipeline/deployments/full_training_v2.json（已归档，见 git 历史）
- contract：`tensile-vlm/v2`

回滚时必须停止 V4.1、释放 GPU，再用独立端口和 V2 契约启动；不能同时把 V2 权重声明为
V4.1，也不能在同一个 Agent 任务中静默降级。

## 10. 当前限制

当前部署只证明：

- 模型文件完整；
- V4.1 Prompt/schema 身份闭合；
- 服务可以处理真实视频；
- TensileAgent 可以调用该服务。

它不证明：

- 模型通过 Stage B、Stage D 或 Stage G 质量门；
- 模型是完整三折最优结果；
- 模型使用全量 development data 训练；
- 模型通过独立测试；
- 模型可作为生产模型发布。

当前证据见
[V4.1 Agent pipeline Fold0 R1](results/v4_1_agent_pipeline_fold0_r1/README.md)。
