# V4.1 固定全字段 Prompt 与统一加载链路设计

> 编写日期：2026-07-28\
> 文档状态：已审批\
> 适用仓库：`mVllm_2`

## 1. 目标与范围

本设计在保持当前 V4.1 development 视频、子视频、四字段标签和冻结 training release
不变的前提下，重新确定 Prompt 内容、人工编辑入口、版本发布方式，以及训练、严格评测和
TensileAgent 的统一加载链路。

本设计解决以下问题：

- 当前 V4.1 System Prompt 和 User Prompt 约束过密，可能诱导模型偏向断裂标签并削弱
  基于视频证据的独立判断；
- `pipeline/prompt_library.yaml` 与 V4.1 contract 存在两个 Prompt 正文来源，人工难以
  判断实际训练和推理加载了哪一份；
- 训练 JSON 使用旧 V4.1 Prompt，而当前严格评测加载澄清后的 runtime Prompt，身份描述
  没有充分区分训练 Prompt 与评测 Prompt revision；
- Prompt 变更缺少单一人工入口、不可变历史版本、自包含 contract 快照和统一 hash。

## 2. 非目标

本设计不包含：

- 修改、重新审查或重新标注当前 development 视频及四字段标签；
- 修改当前不可变 training release；
- 修改 LoRA rank、alpha、dropout、学习率、epoch 或其他训练超参数；
- 设计面向任意用户自然语言的微调模型 Prompt 路由；
- 让微调模型直接接收 TensileAgent 用户的原始问题；
- sealed-test 标签读取、生产切换或质量 final 结论；
- 实现代码、启动训练或执行长评测。

LoRA 超参数继续以实际训练启动 YAML 为唯一人工编辑入口。Prompt 控制入口不得复制或
覆盖训练 YAML 中的超参数。

## 3. 已冻结的数据边界

当前 development release 保持不变：

```text
/home/liuyang/文档/tensile-data/current/training_releases/
v4.1.0-ecb5aeb9657c
```

其权威身份包括：

```text
release_id:
v4.1.0-ecb5aeb9657c

release_manifest_sha256:
ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b

training_candidates_sha256:
390447dee4bdec6ead93df7ed2ebf8eac0dd5b41f6f1aecf21320c0201a0eacf
```

`metadata/training_candidates.json` 是通过审查路由、标签规范化、媒体身份验证和发布门禁
后形成的最终训练候选清单。其标签来源包括直接人工批准或修正、合格的历史人工共识，以及
自动门禁通过的稳定未断裂样本。它必须与整个 release manifest 一起使用，禁止被单独复制
为无身份的数据源。

本轮只使用该 release 中已经冻结的：

- 子视频路径和媒体 hash；
- source video 与有效帧 signature；
- `clip_state`；
- `fracture_mechanism`；
- `fracture_site`；
- `special_case`。

## 4. 设计选择

### 4.1 固定全字段任务

微调模型只承担固定的视觉结构化识别任务。每次调用均返回完整四字段：

```text
clip_state
fracture_mechanism
fracture_site
special_case
```

本轮不生成单字段、双字段任务，不维护 task profile 或 User Prompt 变体池。

选择固定全字段任务的原因：

- 避免组合四个字段产生大量单字段、双字段和多字段 Prompt；
- 避免把“未询问字段”与真实 `null` 标签混淆；
- 保持训练、评测和运行时调用接口一致；
- 将用户意图理解和最终字段筛选留给 TensileAgent；
- 首轮只验证一套固定 Prompt，更容易隔离性能变化来源。

### 4.2 TensileAgent 职责边界

调用链固定为：

```text
用户问题
  → TensileAgent 理解用户意图
  → 使用固定 Prompt 调用微调模型
  → 微调模型返回完整四字段 JSON
  → TensileAgent 按用户意图筛选和组织结果
  → 返回最终回答
```

TensileAgent 不得把用户原始问题直接拼接或转发给微调模型。用户问法变化不能改变模型调用
Prompt 的正文或 hash。

### 4.3 Prompt 约束强度

Prompt 只负责：

- 限定模型仅依据当前视频可见信息；
- 要求返回 JSON；
- 声明四个输出字段；
- 罗列各字段使用的标签池；
- 禁止解释、Markdown 和其他附加文本。

Prompt 不负责：

- 给出详细的视觉分类步骤；
- 强制优先判断某个字段；
- 描述各断裂类别的视觉特征；
- 用正向或负向示例强化某一类别；
- 罗列枚举外错误同义词；
- 承载复杂字段联动规则。

字段类型、标签合法性和字段联动由 contract schema、parser 和 validator 执行，不能为了
修复结构错误而继续扩张 Prompt。

## 5. 初版固定 Prompt

### 5.1 System Prompt

```text
你是一位材料力学视频分析助手。请仅依据当前输入视频中可见的信息完成判断，不要推测视频片段之外发生的事件。

请以一个合法 JSON 对象给出结果，不要输出解释、Markdown 或其他文字。结果包含 clip_state、fracture_mechanism、fracture_site、special_case 四个字段。

本任务使用以下标签池：

clip_state：
未断裂、临界未断裂、发生断裂、已断裂、无法判断。

fracture_mechanism：
韧性断裂、脆性断裂、界面脱粘、爆炸性断裂、半脆半韧断裂，以及 null。

fracture_site：
inside_gauge、outside_gauge_non_root、grip_root，以及 null。

special_case：
未夹紧、视频异常，以及 null。

输出结构：

{"clip_state": ..., "fracture_mechanism": ..., "fracture_site": ..., "special_case": ...}
```

### 5.2 User Prompt

```text
请根据这段拉伸试验视频，判断试样是否发生断裂，并给出相应的断裂模式和断裂位置。
```

### 5.3 初版身份

初版人工可读 revision ID 为：

```text
v4.1-fixed-full-fields-initial-v1
```

最终 Prompt identity 必须由发布工具对规范化后的完整 System Prompt、User Prompt、
标签池、输出字段顺序和 Prompt schema version 计算 SHA-256。人工 revision ID 不能代替
内容 hash。

## 6. 单一人工编辑入口

建议新增：

```text
pipeline/prompt_control/
├── active_prompt.yaml
├── prompt_control.schema.json
└── README.md
```

`active_prompt.yaml` 是 Prompt 正文的唯一人工编辑入口，只包含：

```yaml
schema_version: tensile-prompt-control/v1
protocol_id: tensile-vlm/v4.1
revision_id: v4.1-fixed-full-fields-initial-v1

system_prompt: |-
  ...

user_prompt: |-
  ...

output_fields:
  - clip_state
  - fracture_mechanism
  - fracture_site
  - special_case

label_pools:
  clip_state: [...]
  fracture_mechanism: [...]
  fracture_site: [...]
  special_case: [...]
```

该入口不得包含：

- training release 的标签正文；
- 视频或逐样本记录；
- LoRA 超参数；
- seed；
- 模型路径；
- 评测阈值；
- 部署配置。

数据 release 和训练 YAML 保持各自独立的唯一来源。Prompt 控制文件只在发布时引用和验证
这些外部身份，不复制其可编辑内容。

## 7. Prompt 发布与历史版本

### 7.1 发布命令

设计目标命令：

```bash
python -m pipeline.prompt_control validate \
  --source pipeline/prompt_control/active_prompt.yaml

python -m pipeline.prompt_control publish \
  --source pipeline/prompt_control/active_prompt.yaml
```

`validate` 只读校验，不生成版本。`publish` 在校验通过后生成不可变 Prompt revision。

### 7.2 不可变 registry

发布产物位于：

```text
pipeline/prompt_registry/
└── v4.1-fixed-full-fields-initial-v1/
    ├── prompt.yaml
    └── manifest.json
```

`manifest.json` 至少记录：

- schema version；
- protocol ID；
- revision ID；
- Prompt 内容 SHA-256；
- 源文件路径和源文件 SHA-256；
- 完整 System/User Prompt 的独立 SHA-256；
- 标签池和输出字段的规范化 SHA-256；
- 发布代码 commit；
- 生成时间。

如果目标 revision 已存在：

- 内容完全一致时只允许验证并返回原身份；
- 任一字节或规范化内容不同则拒绝覆盖；
- 修改 Prompt 必须使用新的 revision ID。

### 7.3 Contract 自包含快照

每个训练或评测 experiment contract 必须同时记录：

- `prompt_revision_id`；
- `prompt_manifest_sha256`；
- `prompt_content_sha256`；
- 完整 System Prompt 快照；
- 完整 User Prompt 快照；
- 输出字段；
- 标签池。

registry 用于统一发布和历史浏览；contract 快照用于单个实验独立复现。两者必须 hash
一致，不能只保存引用，也不能允许两份正文独立编辑。

## 8. 训练 JSON 重新生成

现有 training release 不修改。新的训练 JSON builder 从冻结 release 读取视频和标签，从
不可变 Prompt revision 读取 Prompt，再生成新的派生训练 bundle。

数据流为：

```text
冻结 training release
  + 不可变 Prompt revision
  + 冻结视频采样多重集和顺序
  → 新训练 JSON bundle
```

每行仍使用 ShareGPT 结构：

```json
{
  "videos": ["<frozen-video-path>"],
  "messages": [
    {"role": "system", "content": "<resolved-system-prompt>"},
    {"role": "user", "content": "<video>\n<resolved-user-prompt>"},
    {"role": "assistant", "content": "<full-four-field-target-json>"}
  ]
}
```

builder 必须从 `training_candidates.json` 和 release fold 数据验证视频与标签对应关系，
不能直接复制旧训练 JSON 的 `messages`，因为旧 JSON 已内嵌旧 Prompt。

### 8.1 初版受控对照

首轮 Prompt 实验保持以下变量不变：

- release ID 和所有视频、标签；
- fold0 train/validation；
- seed3411 对应的视频候选多重集；
- seed3411 的候选排列；
- 基础模型；
- 训练 YAML 和 LoRA 超参数；
- epoch、optimizer steps 和 checkpoint 规则；
- scorer 和严格评测记录集合。

只改变：

- Prompt revision；
- 由新 Prompt 重新生成的训练 JSON；
- 与此变化绑定的新 run identity 和产物路径。

当前 3000 行多重集已经使“发生断裂 + 已断裂”与“未断裂”接近 2:1，并保留独立的
“临界未断裂”配额。初版 Prompt 对照不调整该多重集，避免同时改变 Prompt 和数据暴露。

## 9. 训练、评测与运行时加载

### 9.1 训练

训练启动 YAML 继续作为 LoRA 超参数唯一人工入口。训练前的 run manifest 必须冻结：

- train config 路径和 SHA-256；
- 解析后的关键超参数快照；
- 训练 JSON 和 registry SHA-256；
- release manifest SHA-256；
- Prompt revision 和 manifest SHA-256；
- 基础模型身份；
- seed、训练代码 commit 和预期 global step。

训练运行时不得从可编辑的 `active_prompt.yaml` 重新解析 Prompt。

### 9.2 严格评测

严格评测必须从同一个 experiment contract 加载 Prompt 快照。评测命令不得：

- 默认加载仓库当前 contract 中的另一份 Prompt；
- 通过可选 overlay 静默替换 Prompt；
- 从 `pipeline/prompt_library.yaml` 获取不同正文；
- 接受未被 run identity 记录的临时 Prompt。

evaluation run identity 必须包含 Prompt revision、Prompt content hash、模型身份、validation
身份、scorer 身份和生成参数。

### 9.3 TensileAgent

TensileAgent 通过模型 bundle 或服务 contract 加载同一 Prompt snapshot。启动时必须验证：

- 服务声明的 Prompt hash 与模型 experiment contract 一致；
- 完整四字段 response schema 一致；
- 调用路径没有拼接用户原始问题；
- 字段筛选发生在模型返回完整 JSON 之后。

Prompt 或 schema 身份不匹配时 fail closed，不能回退到仓库中的其他 Prompt。

## 10. 失败处理

以下情况必须拒绝发布或启动：

- Prompt revision ID 已存在但内容不同；
- Prompt manifest、contract 快照和实际加载内容 hash 不一致；
- 训练 JSON 中出现多个 System Prompt 或 User Prompt 版本；
- 训练 JSON assistant 输出不是完整四字段；
- 训练、评测或 TensileAgent 使用不同 Prompt hash；
- 数据 release 或视频多重集发生未声明变化；
- Prompt 发布工具尝试修改 training release；
- Prompt 控制文件包含训练超参数或逐样本标签；
- 旧 Prompt 被静默覆盖或历史 revision 无法复算。

结构验证失败不能通过增加更强的 Prompt 决策规则来绕过，必须修复 schema、parser、
validator 或加载身份。

## 11. 测试策略

### 11.1 Prompt 发布

- 合法 active Prompt 可以发布；
- 规范化后可复算稳定的 content hash；
- 相同 revision 和相同内容幂等；
- 相同 revision 和不同内容拒绝覆盖；
- 字段缺失、重复或顺序漂移时拒绝；
- 标签池与 V4.1 schema 不一致时拒绝。

### 11.2 训练 JSON

- 只读取冻结 release 的视频和标签；
- 每行 System/User Prompt 与发布快照完全一致；
- assistant 目标始终为完整四字段；
- 新 JSON 保持 seed3411 视频多重集和顺序 hash；
- Prompt 更新会改变训练 JSON hash，但不会改变视频多重集 hash；
- 旧 release 和旧训练 JSON 不被覆盖。

### 11.3 加载一致性

- 训练、严格评测和 TensileAgent 解析到同一个 Prompt content hash；
- 任一链路使用可编辑草稿或旧 Prompt 时失败；
- contract 自包含快照与 registry manifest 可双向复算；
- TensileAgent 只筛选模型完整结果，不改变模型请求 Prompt。

### 11.4 初版性能记录

首轮训练和评测至少记录：

- JSON/schema 合法率；
- runtime failure；
- `clip_state` 分状态指标；
- 断裂与非断裂指标；
- `fracture_mechanism` 指标；
- `fracture_site` 指标；
- joint success；
- 与同 seed、同数据、旧 Prompt 基线的配对差异。

训练 loss 或 eval loss 不能单独作为 Prompt 改善结论。

## 12. 迁移与保留

- 当前 `v4.1.0-ecb5aeb9657c` release 永久保留，不因 Prompt 修改重建；
- 现有 seed3407、seed3411、seed3413 训练、merged 模型和评测证据保留为历史基线；
- `pipeline/prompt_library.yaml` 在新 V4.1 链路完成前不得删除；迁移完成后标记其适用协议，
  防止旧 V1/V2 工具误读；
- 当前 `pipeline/contracts/tensile_vlm_v4_1.json` 的历史 hash 和 Prompt 快照继续保留，
  新实验使用新的 Prompt revision 和 contract identity；
- 首轮只执行一个受控 Prompt 对照 run；是否增加第二 seed 稳定性复核由首轮完整性和性能
  结果决定；
- 任何受控切换仍需独立的服务验证和授权，本设计不授予生产切换权限。

## 13. 验收标准

本设计实施完成需同时满足：

1. 人工只在一个 Prompt 控制文件中编辑正文；
2. 每次发布生成不可覆盖、可复算的 Prompt revision；
3. contract 保存完整 Prompt 快照并与 registry hash 一致；
4. training release、Prompt revision 和训练 YAML 各自拥有唯一编辑边界；
5. 新训练 JSON 保持冻结视频、标签、多重集和顺序，只替换 Prompt；
6. 训练、评测和 TensileAgent 使用同一 Prompt content hash；
7. 微调模型始终返回完整四字段；
8. TensileAgent 在完整结果返回后按用户意图筛选字段；
9. Prompt 加载漂移、旧 revision 覆盖和数据身份漂移全部 fail closed；
10. 初版性能报告能够与同 seed 旧 Prompt 基线做有效配对比较。
