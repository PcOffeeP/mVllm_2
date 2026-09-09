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

## 5. Q4 数据根选择（用户确认）

- 用户已确认 Q4 数据根选择 A：`/data/mVllm_2`。
- 当前 `/data/mVllm_2` 尚不存在；`/data` root 属主，普通用户无写权限。
- 正式写入前仍需一次性目录准备与权限确认。

## 6. 未执行项（明确保留）

- 本机与训练机均未执行真实迁移写入、训练、评测、push/merge。
- 凭证（receipt）的具体格式/存储位置仍待实现确认；未裁决凭证格式/位置。
- 模型/训练/run 的权重完整性与哈希仍未验证（本文件仅覆盖两个 data release 的 payload hash）。

## 7. 关键 hash 汇总

- r1 manifest sha256：`c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`
- r2 manifest sha256：`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`
- 远程 HEAD：`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`
