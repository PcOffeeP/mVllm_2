# 训练机项目内 Workspace 与语义实验目录设计

> 日期：2026-07-28  
> 状态：已实施，训练待单独授权
> 适用范围：训练机 `/home/liuyang/文档/mVllm_2` 中的活跃 V4.1 数据与后续实验

## 1. 目标

本设计解决两个维护问题：

1. 活跃训练数据当前位于仓库外的独立 `tensile-data/current`，路径和生命周期管理过重；
2. bundle、run 和目录名称以短 hash 为主，能够验证身份，但无法直接表达实验目的。

改造后：

- 活跃 V4.1 数据、模型、日志和运行结果统一保存在训练机项目内部；
- 大型和机器本地产物不进入 Git；
- 每个实验只使用一个简短、可读的实验 ID；
- hash 只保存在 manifest 中负责身份校验；
- 从目录名称即可判断实验版本、主要修改和 seed。

## 2. 非目标

本轮不包含：

- 迁移或重写已经冻结的历史 V2 数据；
- 把视频、模型权重、逐样本评测结果或运行日志提交到 Git；
- 引入数据库、DVC、对象存储或外部 artifact registry；
- 修改 V4.1 标签、development release 内容或训练样本真值；
- 启动训练、模型合并、GPU 推理或完整评测；
- 切换现有 V2 生产服务或 TensileAgent。

## 3. 设计原则

### 3.1 一个项目内本地 Workspace

训练机只使用：

```text
/home/liuyang/文档/mVllm_2/workspace
```

作为活跃 V4.1 大型数据和运行产物根目录。

整个 `workspace/` 必须被 Git 忽略。Git 只管理代码、实验说明、轻量配置和必要的身份
manifest。

### 3.2 一个实验 ID

同一个实验的配置目录和本地运行目录必须使用同一个 ID，不再分别生成 bundle ID 和
run ID。

当前 Prompt 对照实验使用：

```text
v4.1-prompt-minimal-v1-seed3411
```

ID 格式为：

```text
<protocol>-<changed-variable>-<revision>-seed<seed>
```

目录名称负责人类理解；内容 hash、Prompt hash、release hash 和模型 hash 继续由 manifest
记录。

### 3.3 语义说明与机器身份分离

每个实验只保留一份简短的 `experiment.yaml` 描述实验意义。详细文件 hash 和运行身份由
生成 manifest 保存，不能把大量 hash 再编码到目录名称。

## 4. 目录结构

### 4.1 训练机本地目录

```text
mVllm_2/
└── workspace/
    ├── data/
    │   ├── source/
    │   ├── derived/
    │   └── releases/
    │       └── dev-v4.1-20260728/
    └── runs/
        └── v4.1-prompt-minimal-v1-seed3411/
            ├── input/
            ├── adapter/
            ├── merged/
            ├── evaluation/
            └── logs/
```

目录职责：

- `workspace/data/source/`：当前 V4.1 原视频、标注和 split；
- `workspace/data/derived/`：ROI、子视频、帧、审查记录和派生 metadata；
- `workspace/data/releases/`：不可覆盖的训练 release；
- `workspace/runs/<experiment-id>/input/`：该实验解析后的训练和验证 JSON；
- `adapter/`、`merged/`、`evaluation/`、`logs/`：该实验的本地运行产物。

### 4.2 Git 管理的实验目录

```text
mVllm_2/
└── finetune/
    └── experiments/
        └── v4.1-prompt-minimal-v1-seed3411/
            ├── experiment.yaml
            ├── train.yaml
            ├── merge.yaml
            └── manifest.json
```

`manifest.json` 只保存轻量身份，不保存大型数据正文。

## 5. experiment.yaml

语义文件固定为：

```yaml
id: v4.1-prompt-minimal-v1-seed3411
status: prepared

purpose: 验证简化决策指令是否降低标签偏置
baseline: v4.1-coverage-first-seed3411

change:
  type: prompt
  summary: 只保留视频证据、四字段标签池和 JSON 输出要求

data_release: dev-v4.1-20260728
seed: 3411
prompt_revision: minimal-v1
```

允许的 `status`：

- `prepared`
- `training`
- `trained`
- `evaluated`
- `rejected`
- `accepted`

状态变化必须与实际产物一致，不能只修改状态而不验证对应文件。

## 6. 数据路径简化

main 分支的活跃 V4.1 路径解析改为：

```text
<repo>/workspace/data
```

活动链路不再依赖：

- `../tensile-data/current`
- `TENSILE_DATA_HOME`
- V2/V4.1 active/archive profile
- `.tensile-data-root.json`
- `.compat/workspace`

历史 V2 仍保存在原外部目录中，只由冻结 Git 引用和历史代码读取；main 不再初始化、
修改或校验 V2 数据根。

冻结 release 内已有的相对媒体路径保持不变。迁移不能修改 release 文件正文或重新计算成
一个内容不同但沿用旧名称的 release。

## 7. 当前实验替换

尚未启动训练的以下身份停止使用：

```text
v4.1-fixed-prompt-8fe58f171667
v4_1_fixed_prompt_8fe58f171667_seed3411
```

对应 Prompt 内容和 seed3411 样本顺序可以复用，但必须在新目录结构下重新生成轻量配置和
manifest：

```text
finetune/experiments/v4.1-prompt-minimal-v1-seed3411
workspace/runs/v4.1-prompt-minimal-v1-seed3411
```

旧目录在新实验完成预检前不得删除；它们只能作为未启动的迁移参考，不能与新实验混用。

## 8. 迁移流程

### 8.1 准备

1. 确认没有训练、合并、评测或数据写入进程；
2. 分别记录本机和训练机的 branch、HEAD 和 `git status`；
3. 冻结当前 `tensile-data/current` 文件清单、总大小和关键 manifest hash；
4. 确认项目所在磁盘同时容纳源目录、迁移副本和训练输出。

### 8.2 数据迁移

1. 创建 `<repo>/workspace/data`；
2. 将 `tensile-data/current` 复制到该目录；
3. 比较文件数量、总字节数和全部受管文件 hash；
4. 校验当前 development release、training candidates、source-aware sampling 和媒体路径；
5. 在校验通过前保留原目录不变。

迁移期间禁止通过软链接让新旧目录互相指向。程序只能读取明确选择的新根或旧根，避免
路径解析结果取决于软链接状态。

### 8.3 代码切换

1. 将 V4.1 路径解析改为 `<repo>/workspace/data`；
2. 将训练、评测、审查和发布工具中的活动路径统一到新根；
3. 删除 main 活动链路对 data root profile、marker 和环境变量的依赖；
4. 将本地模型、日志和结果路径改为 `workspace/runs/<experiment-id>/...`；
5. 添加 `/workspace/` Git ignore 规则；
6. 更新 README、runbook 和测试 fixture。

### 8.4 实验重建

1. 在 `finetune/experiments/` 创建语义实验目录；
2. 从冻结 release 和 Prompt revision 重新生成 `input/`；
3. 验证 seed3411 视频多重集、顺序和 assistant 标签与原基线完全一致；
4. 生成 `train.yaml`、`merge.yaml` 和轻量 manifest；
5. 完成 Git、依赖、LLaMA-Factory 来源、GPU、磁盘和目标目录预检；
6. 停在训练命令执行前，等待用户明确授权。

### 8.5 旧根退役

新路径完成一次真实训练和严格评测前，不删除原外部 V4.1 数据。

验证完成后：

1. 将原 `tensile-data/current` 改名为带日期的只读备份；
2. 再运行一次路径扫描，确认活动代码不引用旧根；
3. 经用户明确授权后才删除备份。

## 9. 失败处理与回滚

- 复制中断：删除不完整的新副本后重新复制，原目录保持权威；
- 文件数、字节数或 hash 不一致：停止切换，不修改旧根；
- release 或 sampling 验证失败：停止实验重建，不能放宽校验；
- 代码仍引用旧路径：不得启动训练；
- 新实验目标目录已存在：拒绝覆盖，先核实身份；
- 训练前发现配置或 Prompt 漂移：废弃本次 prepared manifest 并重新生成；
- 切换后发现问题：恢复代码到迁移前提交并继续读取原外部目录。

## 10. 测试与验收

### 10.1 路径测试

- 默认 V4.1 根解析为 `<repo>/workspace/data`；
- main 活动链路不读取 `TENSILE_DATA_HOME`；
- main 不再初始化或写入 V2 archive；
- 所有生成输出均位于 `workspace/` 或 Git 管理的实验目录。

### 10.2 数据一致性

- 源目录和新目录的受管文件 hash 完全一致；
- development release manifest hash 不变；
- `training_candidates.json` hash 不变；
- seed3411 candidate sequence、video sequence 和标签 hash 不变；
- Prompt content hash 不变。

### 10.3 实验语义

- 实验 ID 在 Git 配置目录和本地运行目录中完全一致；
- `experiment.yaml` 能直接说明目的、基线、唯一变化、release、Prompt 和 seed；
- manifest 能从实验 ID解析到所有真实输入和输出路径；
- 不存在新的独立 bundle ID 或 run ID。

### 10.4 Git 与运行安全

- `workspace/` 不会出现在 `git status`；
- Git 中只包含代码、配置和轻量 manifest；
- 训练入口只加载当前仓库的 LLaMA-Factory；
- adapter、merged、evaluation 和 logs 目标目录在首次运行前不存在；
- 训练机 GPU、磁盘和依赖预检通过；
- 未经明确授权不启动训练。

## 11. 完成标准

以下条件同时满足时迁移完成：

1. 活跃 V4.1 数据物理位于训练机项目的 `workspace/data`；
2. main 活动代码不再依赖外部活动数据根；
3. 历史 V2 保持原地只读且不受 main 管理；
4. 当前实验只使用 `v4.1-prompt-minimal-v1-seed3411` 一个语义 ID；
5. 配置目录和本地运行目录能从名称直接理解实验意义；
6. 所有机器身份 hash 仍可从 manifest 验证；
7. 新实验通过完整启动前检查；
8. 训练尚未启动，并等待用户单独授权。
