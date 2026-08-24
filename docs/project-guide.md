# mVllm_2 Project Guide

<!-- explain-project
verified_commit: ca6311dd3def65aa3dee2081cbe31de2770c5439
verified_worktree: HEAD 加 8 个清理文件已暂存删除：tensile_vlm_v1.json、v4_review_decisions.py、v4_review_workflow.py、3 个 scripts/archive 迁移脚本、2 个对应测试
-->

mVllm_2 把材料拉伸试验视频治理为来源可追踪、标签可审查的 V4.1 视觉训练样本，并基于 MiniCPM-V-4.5 完成 LoRA 微调、严格评测与可复现的模型服务交付。

## 核心链路

```text
原始视频与标注
    ↓
数据快照 / ROI 子视频重建
    ↓
候选帧窗口计划与物化（v3 命名遗留）
    ↓
人工审查队列与决策
    ↓
不可覆盖的 training release 发布
    ↓
Prompt revision 注册 + 固定 Prompt 训练集构建
    ↓
训练准备 + 受控 LoRA 微调
    ↓
严格评测
    ↓
模型注册表晋级 + delivery 门禁校验
    ↓
推理服务交付
```

## 承重规则

1. **release 不可覆盖**：workspace 中 `data/releases/<release-id>/` 一旦发布即只读；后续训练/评测必须绑定到已冻结的 release identity。
2. **registry 是模型身份唯一事实源**：服务加载、交付校验、Agent 对接全部通过 `pipeline/model_registry/current.json` 解析当前模型，不能从目录名或实验文件名推断。
3. **工程链路与模型质量分开验收**：训练成功、服务启动、Agent 调通只证明链路可运行；最终模型仍需通过 Stage B/D/G 质量门，当前尚未通过。

## 链路节点

### 1. 原始视频与标注

- **拥有**：workspace/data/source 下的源视频、源标注和 split 定义。
- **产出**：经 `source_bootstrap` 形成的内容寻址 source snapshot 与 split snapshot。
- **下一站**：ROI 重建脚本消费 snapshot，保证后续所有子视频可回溯到源。

### 2. 数据快照 / ROI 子视频重建

- **拥有**：`pipeline/scripts/rebuild_v4_1_data.py` 主导整个 rebuild 流水线。
- **接收**：source snapshot、ROI manifest。
- **产出**：ROI 子视频、帧目录、各阶段 state/artifact 记录。
- **下一站**：进入候选计划。

### 3. 候选帧窗口计划与物化

- **拥有**：`pipeline/v3_candidate_plan.py`、`pipeline/v3_candidate_media.py`、对应 `scripts/build_v3_candidate_plan.py` 与 `scripts/materialize_v3_candidate_media.py`。
- **接收**：ROI 子视频、原始视频 split、标签规则。
- **产出**：候选帧窗口计划、物化的子视频/帧、媒体门禁结果。
- **命名说明**：模块名中的 `v3` 是 provenance 遗留，V4.1 继续复用这些物化机制，不代表契约回退到 V3。
- **下一站**：满足门禁的候选进入 V4.1 审查队列。

### 4. 人工审查队列与决策

- **拥有**：`pipeline/v4_1_review_workflow.py`、`pipeline/v4_1_review_decisions.py`、Streamlit 审查 UI 辅助脚本。
- **接收**：候选媒体与自动分流结果。
- **产出**：review queue、review evidence、人工决策结果。
- **下一站**：决策结果汇入 training release。

### 5. 不可覆盖的 training release 发布

- **拥有**：`pipeline/v4_1_training_release.py`。
- **接收**：审查后的标签、源 snapshot binding、媒体清单。
- **产出**：`workspace/data/releases/<release-id>/` 下的 manifest、dataset_info、媒体文件；当前活跃发布为 `v4.1.0-ecb5aeb9657c`（1678 条）。
- **下一站**：由 `finetune/build_v4_1_fixed_prompt_dataset.py` 绑定到具体 Prompt revision。

### 6. Prompt revision 注册 + 固定 Prompt 训练集构建

- **拥有**：`pipeline/prompt_control/` 提供 active prompt 校验与发布；`pipeline/prompt_registry/` 存放不可变 revision。
- **接收**：training release、已发布 Prompt revision（当前活跃 `v4.1-concise-evidence-json-v2`）。
- **产出**：固定 Prompt 的语义实验输入目录，含 experiment contract。
- **下一站**：`finetune/prepare_v4_1_fixed_prompt_run.py` 生成训练配置。

### 7. 训练准备 + 受控 LoRA 微调

- **拥有**：`finetune/prepare_v4_1_fixed_prompt_run.py`、`finetune/train_with_contract.py`。
- **接收**：固定 Prompt 训练集、LLaMA-Factory 基线配置、contract 校验。
- **产出**：workspace/runs/<experiment-id>/ 下的 adapter、merged 模型、日志。
- **下一站**：`finetune/run_v4_1_evaluation.py` 在验证集上做严格评测。

### 8. 严格评测

- **拥有**：`finetune/run_v4_1_evaluation.py`。
- **接收**：release、experiment contract、merged/adapter 模型。
- **产出**：schema 合法率、四字段准确率、`clip_state` 混淆矩阵、失败样例等。
- **下一站**：只有跨 fold 稳定且质量门通过的方案才晋级发布；当前多数实验停留在 workspace/runs/。

### 9. 模型注册表晋级 + delivery 门禁校验

- **拥有**：`pipeline/model_registry.py`、`scripts/validate_delivery_components.py`、`delivery/model_component.json`、`delivery/service_component.json`。
- **接收**：人工确认的模型目录、评测证据、契约身份。
- **产出**：`pipeline/model_registry/releases/<model-name>.json` 与 `current.json`。
- **当前发布**：`v4.1-agent-pipeline-fold0-r1`（Fold0 中间模型，质量门未通过）。
- **下一站**：推理服务从 registry 加载该模型。

### 10. 推理服务交付

- **拥有**：`pipeline/server_proxy.py`。
- **接收**：registry 指向的 merged 模型、production contract、服务启动配置。
- **产出**：loopback-only 的 OpenAI 风格 API，输入 MP4 base64，输出 V4.1 四字段 JSON。
- **约束**：当前服务只绑定 `tensile-vlm/v4.1` contract，禁止对外暴露 production alias。

## 关键细节

### V4.1 输出字段

`clip_state`、`fracture_mechanism`、`fracture_site`、`special_case`。权威契约见 `pipeline/contracts/tensile_vlm_v4_1.json`，运行时校验见 `pipeline/v4_1_labels.py`。

### 双机工作流

- Mac（本机）：uv + Python 3.11，负责代码检查、文档、Streamlit 审查 UI、轻量校验。
- 训练机（Linux/GPU，SSH 100.70.83.68）：Conda，负责训练、GPU 推理、完整评测、重数据处理。
- 本机看到的大量训练产物是从训练机同步过来的结果，不应默认本机能复现实验。

### workspace 是产物层

`workspace/` 被 Git 忽略，存放数据、实验运行、模型资产。代码与轻量 manifest 入 Git，大型产物与一次性评测记录不入 Git。

## 当前限制与未知

- 当前唯一发布模型 `v4.1-agent-pipeline-fold0-r1` 已通过工程链路，但 Stage B/D/G 质量门未通过，不是 production-ready 最终模型。
- 最新三折实验 `v4.1-prompt-concise-cv-v1-seed3411` 已跑通全流程，但出现类别坍缩、契约非法和断裂状态召回不足，未晋级 release。
- 本机无法运行训练、GPU 推理和完整评测；缺少产物时应标记为“证据不足”。
