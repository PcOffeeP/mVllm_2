# 全量模型推理服务运行手册

本文用于在训练机 `100.70.83.68` 上手动启动、验证和停止
`tensile-vlm/v2` 推理服务。所有命令均在
`/home/liuyang/文档/mVllm_2` 下执行。

## 1. 固定部署对象

- Python 环境：`/home/liuyang/miniconda3/envs/cpm45/bin/python`
- merged 模型：
  `LlamaFactory/saves/minicpmv4_5/lora/sft_interval_v2_0_0_1dab1e5e_full_20260719_merged`
- 部署 manifest：`pipeline/deployments/full_training_v2.json`
- 服务入口：`pipeline.server_proxy`
- 默认端口：`8001`
- 契约：`tensile-vlm/v2`
- 契约 hash：
  `d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102`

manifest 中的 `config_fingerprint` 是 merged 模型 `config.json` 的 SHA256。
更换模型、checkpoint、框架版本、运行精度或显卡后，必须新建 manifest，不能沿用
当前部署身份。

## 2. 启动前检查

```bash
cd '/home/liuyang/文档/mVllm_2'

git status --short
nvidia-smi

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pipeline.production_contract

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pytest tests/test_production_contract.py \
  tests/test_smoke_tensile_vlm_service.py -q
```

必须确认：

1. 没有其他训练、merge 或评测进程占用 GPU；
2. Git 工作区没有不明确的修改；
3. 契约命令输出的版本和 hash 与本文一致；
4. 模型目录和 manifest 均存在。

## 3. 前台启动

首次验证建议只监听本机：

```bash
cd '/home/liuyang/文档/mVllm_2'

export CUDA_VISIBLE_DEVICES=0
export API_KEY='替换为随机长字符串'

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pipeline.server_proxy \
  --model LlamaFactory/saves/minicpmv4_5/lora/sft_interval_v2_0_0_1dab1e5e_full_20260719_merged \
  --deployment-manifest pipeline/deployments/full_training_v2.json \
  --host 127.0.0.1 \
  --port 8001
```

模型加载完成并出现 Uvicorn listening 日志后，再打开另一个 SSH 终端进行验证。
不要把 `API_KEY` 写入 Git、命令日志或本文。

## 4. 后台启动

先建立仅当前用户可读的环境文件：

```bash
cd '/home/liuyang/文档/mVllm_2'
mkdir -p finetune/run_logs
umask 077
printf 'API_KEY=%s\n' '替换为随机长字符串' \
  > finetune/run_logs/tensile_vlm_service.env
```

然后使用 `tmux`：

```bash
tmux new-session -d -s tensile-vlm \
  "cd '/home/liuyang/文档/mVllm_2' && \
   set -a && source finetune/run_logs/tensile_vlm_service.env && set +a && \
   export CUDA_VISIBLE_DEVICES=0 && \
   exec /home/liuyang/miniconda3/envs/cpm45/bin/python \
   -m pipeline.server_proxy \
   --model LlamaFactory/saves/minicpmv4_5/lora/sft_interval_v2_0_0_1dab1e5e_full_20260719_merged \
   --deployment-manifest pipeline/deployments/full_training_v2.json \
   --host 0.0.0.0 --port 8001 \
   2>&1 | tee finetune/run_logs/tensile_vlm_service.log"
```

查看日志和会话：

```bash
tmux ls
tmux capture-pane -pt tensile-vlm -S -100
nvidia-smi
```

`0.0.0.0` 仅用于让另一台机器上的 TensileAgent 访问。此模式必须设置
`API_KEY`，并通过主机防火墙或可信内网限制端口 `8001`。

## 5. 预检

```bash
set -a
source finetune/run_logs/tensile_vlm_service.env
set +a

curl --fail --silent --show-error \
  -H "Authorization: Bearer ${API_KEY}" \
  http://127.0.0.1:8001/v1/tensile/contract \
  | /home/liuyang/miniconda3/envs/cpm45/bin/python -m json.tool
```

返回值必须包含：

- `contract_version=tensile-vlm/v2`
- 固定 `contract_hash`
- `analysis=true`、`evidence=true`
- 完整 11 字段 `deployment_manifest`

TensileAgent 在正式调用前也会执行同样的预检；身份不一致时应 fail closed。

## 6. 真实视频冒烟

仓库提供了自动构造固定 Prompt 和 Base64 MP4 请求的脚本：

```bash
set -a
source finetune/run_logs/tensile_vlm_service.env
set +a

/home/liuyang/miniconda3/envs/cpm45/bin/python \
  -m pipeline.scripts.smoke_tensile_vlm_service \
  --base-url http://127.0.0.1:8001 \
  --video data/08_incremental_review/round_01/03_subvideos/video_0029_focus_3s_80pct.mp4
```

成功输出必须同时包含：

- 四字段模型原始 JSON；
- `request_id`；
- 真实采样帧和时间戳；
- `tensor_digest`、`tensor_shape`；
- 与预检一致的部署身份。

训练 loss 或 HTTP 200 不能单独证明服务可用；以上证据链缺失时不得接入 Agent。

## 7. TensileAgent 接入

在 TensileAgent 运行环境中配置：

```bash
export INFERENCE_BASE_URL='http://100.70.83.68:8001/v1'
export INFERENCE_API_KEY='与训练机 API_KEY 相同的值'
export INFERENCE_MODEL='tensile-vlm'
```

也可以在 TensileAgent 配置的 `backend.api_url` 和 `backend.model` 中写入同样的
URL 与模型名；配置文件优先于 `INFERENCE_BASE_URL`。服务 URL 必须包含 `/v1`，
并指向本服务，不能直接指向未包装的 LLaMA-Factory OpenAI 接口。

## 8. 停止和重启

正常停止：

```bash
tmux send-keys -t tensile-vlm C-c
tmux kill-session -t tensile-vlm
```

确认端口和 GPU 已释放：

```bash
ss -ltnp | grep ':8001' || true
nvidia-smi
```

重启前必须先确认旧服务已退出。不要同时启动第二个服务实例，也不要用 `kill -9`
作为常规停止方式。

## 9. 常见故障

- 预检 `401`：客户端没有使用与服务端一致的 `API_KEY`。
- 预检 `422`：运行代码过旧或路由注入异常，先检查 Git 是否位于最新主线。
- 启动时报 manifest 字段错误：不要删除字段；重新基于当前模型生成完整 10 字段配置。
- CUDA OOM：确认没有训练/评测进程占卡；停止旧服务后再启动。
- 请求 `422`：视频必须是一个 Base64 `video/mp4`，Prompt 必须与契约逐字一致。
- 请求 `500`：查看 `finetune/run_logs/tensile_vlm_service.log`，同时检查模型加载日志、
  视频解码和采样证据；不要在对外响应中暴露视频内容或本机路径。
- Agent 拒绝响应：比较预检和响应中的 `contract_version`、`contract_hash`、
  `deployment_manifest`、帧表与 tensor 证据，禁止绕过校验。
