# 项目内 Workspace 迁移与训练前检查报告

> 日期：2026-07-28
> 实验：`v4.1-prompt-minimal-v1-seed3411`
> 结论：迁移和启动前检查通过；训练未启动

## 数据迁移

训练机已将旧 `/home/liuyang/文档/tensile-data/current` 的受管目录物理复制到
`/home/liuyang/文档/mVllm_2/workspace/data`：

| 旧目录 | 新目录 |
| --- | --- |
| `source/` | `source/` |
| `derived/` | `derived/` |
| `training_releases/` | `releases/` |

校验结果：

- 文件数：20,718；
- 总字节数：7,516,223,269；
- 全部受管文件逐文件 SHA-256 一致；
- 新目录无软链接；
- 旧根未删除、未重命名；
- development release manifest SHA-256：
  `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`；
- 基础 release manifest SHA-256：
  `c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`。

## 实验重建

新实验输入位于：

`workspace/runs/v4.1-prompt-minimal-v1-seed3411/input`

Git 配置位于：

`finetune/experiments/v4.1-prompt-minimal-v1-seed3411`

身份与一致性：

- 训练 3,000 条，验证 425 条；
- 新旧 seed3411 视频顺序一致；
- 新旧 seed3411 视频多重集一致；
- 新旧 assistant 标签逐条一致；
- Prompt content SHA-256：
  `2e4e0ad6503dfabab6239028060164edaf0c04cf98923687ddb273e7a21d34d3`；
- input identity SHA-256：
  `a6f74dfc88ed4a17a023b55fbf8959a080b952a43142acd2ac66927cd70aa1ae`。

旧 `v4_1_fixed_prompt_8fe58f171667_seed3411` Git 配置已移入 archive；旧数据 bundle
保留为迁移参考，没有删除。

## 启动前检查

训练机实际检查结果：

- 3,425 条训练和验证媒体引用全部存在，共 1,678 个唯一媒体；
- 基础模型目录存在；
- `torch 2.5.1+cu124`、`transformers 4.56.1`、`peft 0.19.1`、
  `bitsandbytes 0.49.2` 可导入；
- LLaMA-Factory 从当前仓库
  `LlamaFactory/src/llamafactory/__init__.py` 加载；
- GPU：NVIDIA GeForce RTX 4090，总显存 24,564 MiB，检查时空闲 23,957 MiB；
- 检查时项目磁盘空闲 180,903,686,144 字节；
- `adapter/`、`merged/`、`evaluation/`、`logs/` 均不存在；
- `workspace/` 已被 Git 忽略；
- 没有训练、合并或评测进程。

训练机与本机的迁移相关针对性测试通过。训练机可运行的非 Streamlit 测试为
561 passed；完整收集还需要该训练环境安装 `streamlit`，此依赖不属于训练启动门禁。

## 停止点

未执行 `manifest.json` 中的训练命令。下一步只有在用户明确授权后，才可将实验状态改为
`training` 并启动 LoRA 训练。
