# 迁移证据：训练机只读调研与完整 payload hash 验证

任务：`2026-09-07-readable-version-control-migration` · M0 证据固化
本文件记录训练机只读调研与两个 legacy data release 的完整 payload hash 验证证据。
只记录已核实事实；不定义迁移行为契约，不判定真实迁移写入已完成。

## 1. 训练机只读调研

- 训练机主机名：`dell-Precision-3660`
- 远程项目路径：`/home/liuyang/文档/mVllm_2`
- 远程 HEAD：`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`
- 远程工作区状态：干净（clean）
- 命令类型：SSH 只读命令；目录检查采用有限深度 `find`/`ls`；文件大小与软链接检查不读取权重内容；Git 状态、活动指针与少量身份元数据被读取。
- 退出状态：只读调研命令均成功返回（exit 0）；初次连接超时，用户恢复 Tailscale 后调查成功。
- 限制：未读取受限测试真值与逐样本语义结果；未执行训练、推理、权重哈希或远端写入。

## 2. 两个 legacy data release 存在性与结构

| release | 路径 | 结构 |
| --- | --- | --- |
| r1 | `workspace/data/releases/v4.1.0-760050fad303` | 存在且结构完整 |
| r2 | `workspace/data/releases/v4.1.0-ecb5aeb9657c` | 存在且结构完整 |

- manifest schema 完整：`path` / `sha256` / `size_bytes` 均无缺失。
- 无 unsafe paths；无 symlink。

## 3. 完整 payload hash 验证

对两个 release 的 manifest 声明文件逐一做 SHA-256 校验，结果如下。

| release | 声明文件数 | 总字节数 | 全部 SHA-256 匹配 | manifest sha256 |
| --- | --- | --- | --- | --- |
| r1 `v4.1.0-760050fad303` | 9 | 9,819,900 | 是 | `c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036` |
| r2 `v4.1.0-ecb5aeb9657c` | 11 | 13,743,509 | 是 | `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b` |

- 无缺失文件、无未声明文件、无 hash mismatch。
- 校验命令退出状态：成功（exit 0）。

## 4. 活动指针验证

- `finetune/active_data_release.json` 指向 r2（`v4.1.0-ecb5aeb9657c`）。
- `expected_manifest_sha256` 与实际 manifest SHA-256 完全一致（`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`）。

## 5. Q4 数据根选择与准备（用户确认）

- 用户已确认 Q4 数据根选择 A：`/data/mVllm_2`。
- 目录准备由用户手动 sudo 完成：
  - `sudo mkdir -p /data/mVllm_2`
  - `sudo chown -R liuyang:liuyang /data/mVllm_2`
- 随后以只读 SSH 验证（exit 0）：
  - `ls -ld /data/mVllm_2 && test -w /data/mVllm_2 && test -x /data/mVllm_2`
  - 输出：`drwxr-xr-x 2 liuyang liuyang 4096 9月 9 09:45 /data/mVllm_2`
- 结论：`/data/mVllm_2` 存在、属主正确、可写、可进入。
- 限制：真实迁移写入仍未执行；receipt 具体实现仍待 TDD；模型/run/训练/评测仍未验证。

## 6. 未执行项（明确保留）

- 本机与训练机均未执行真实迁移写入、训练、评测、push/merge。
- 凭证（receipt）的具体格式/存储位置仍待实现确认；未裁决凭证格式/位置。
- 模型/训练/run 的权重完整性与哈希仍未验证（本文件仅覆盖两个 data release 的 payload hash）。

## 7. coverage-first seed3407 merged 软链接来源链

2026-09-11 经用户授权，对训练机执行只读 SSH 核查（无文件写入、同步、训练、推理或权重哈希）：

- run：`workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0`
- `merged` 链接文本：`../../../models/releases/v4.1-agent-pipeline-fold0-r1/merged`
- 解析目标：`workspace/models/releases/v4.1-agent-pipeline-fold0-r1/merged`
- 目标目录存在 10 个顶层 `model-*-of-00010.safetensors` 分片；本轮只核对文件类型、名称与大小，未读取或复算权重内容哈希。
- `fold0/model_identity.json` 声明同一 `model_name`、当前 run 的 `merged_path`；`source_adapter_path` 与 `source_merged_path` 是同一 LlamaFactory 来源对（后者严格为前者加 `_merged`），共同带有实验 ID 与 seed3407。
- `pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json` 与发布目录内 `release-manifest.json` 字节 SHA-256 均为 `3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`，内容完全一致。
- release manifest 的 `origin.experiment_id` 与上述来源目录名精确对应，并绑定 coverage-first、release `v4.1.0-ecb5aeb9657c`、fold 0、seed 3407；adapter/merged 的 `path_at_freeze` 分别与 identity 来源路径一致，`artifacts.merged.managed_path` 与链接解析目标一致，并声明 10 个分片。
- 对 run、fold0、identity、adapter、Registry manifest、发布目录 manifest 和 managed merged 目标从仓库根逐级执行 `lstat`；各级均为普通目录/文件，只有声明的 `fold0/merged` 是预期软链接，发布目录顶层权重分片也不是软链接。
- 结论：该 run 的 merged 链接来源链在路径、run 本地身份、Registry manifest 和发布目录 manifest 四层一致，可作为“观察到权重存在”的来源证据；这不证明权重内容哈希、可加载性、训练完成或质量通过。
- 远端核查基线仍为干净 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。

## 8. 关键 hash 汇总

- r1 manifest sha256：`c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`
- r2 manifest sha256：`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`
- coverage-first seed3407 model identity sha256：`83cc641cdb441cb3766694fe1916da3d4d3325009409df3edab565528020ef5b`
- `v4.1-agent-pipeline-fold0-r1` Registry / release manifest sha256：`3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`
- 远程 HEAD：`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`

## 9. 历史训练参数证据边界

- H9 只从 `docs/results/model_evidence/<run_id>/MANIFEST.json` 声明且经 size/SHA-256 验证的文件提取参数；归档包身份、schema、run seed 和三层 epoch 证据必须一致。
- 当前可提取字段为 seed、epochs、effective batch size、LoRA rank、LoRA alpha、LoRA target modules；每个字段分别记录实际取值文件和交叉验证文件。
- LoRA 参数取自声明 run 的 `adapter_config.json`，并以归档 MANIFEST 中记录的 size/SHA-256 验证；归档目录本身没有该文件副本。epochs/effective batch 由归档 training manifest、trainer state 和包摘要交叉核对。
- learning rate、optimizer、precision 继续保持字段级 unknown：现有证据包未提供足够稳定的历史执行配置链，当前 active 配置可能已漂移，不得据此反推。
- 训练机当前 `main@f1b7d8a3` 尚无 `docs/results/model_evidence`，因此本轮仅完成本地合成行为、实际归档布局静态核对和训练机文件盘点；尚未在训练机对真实历史 run 执行端到端参数提取。
