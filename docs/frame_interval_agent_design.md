# 帧区间迭代定位技术设计文档

> 项目：mVllm-frame-interval-agent  
> 模型：MiniCPM-V 4.6  
> 日期：2026-06-11  
> 状态：Current Repository Design

---

## 0. 文档地位与适用范围

本文是 `mVllm-frame-interval-agent` 当前仓库的设计文档，后续实现、评审和验收均以本文为主。若本文与实际训练 YAML、`dataset_info.json`、CSV 标注文件或 `AGENTS.md` 的稳定约束不一致，以对应权威配置/数据文件为准，并优先修订本文。

本文只定义新 worktree 的帧区间迭代定位方案。旧 worktree 中“直接预测断裂时间与断裂模式”的方案仅作为对比基线，不在本文范围内继续扩展。

---

## 1. 项目概述

### 1.1 目标

训练一个基于多模态大模型的**帧区间判别模型**，并配合外部**迭代控制器**，逐步缩小视频断裂时间范围，最终定位材料拉伸试验视频的断裂时刻。

### 1.2 与旧方案的根本区别

| 维度 | 旧方案 | 新方案 |
|---|---|---|
| 预测方式 | 直接输出断裂秒数（回归/分类） | 输出"断裂发生在哪两帧之间"（区间判别） |
| 推理流程 | 单轮预测 | 多轮迭代，逐步收缩时间区间 |
| 信息利用 | 一次性观看全视频 | 每轮聚焦子区间，逐层定位 |
| 失败模式 | 偏差大时无修正机制 | 每轮有置信度，可提前终止或加权融合 |

核心思想：**不直接预测精确秒数，而是通过多轮问答让模型判断"断裂在哪两帧之间"，外部 Agent 据此迭代缩小范围。**

### 1.3 成功标准

| 指标 | 目标 | 说明 |
|---|---|---|
| 区间命中率 | ≥ 80% | 预测区间包含真实断裂时间的比例 |
| within_1s | ≥ 60% | 点估计（区间中点）与真实时间误差 ≤ 1s |
| within_3s | ≥ 85% | 点估计与真实时间误差 ≤ 3s |
| within_5s | ≥ 95% | 点估计与真实时间误差 ≤ 5s |
| type macro-F1 | ≥ 0.75 | 断裂类型（韧性/脆性等）分类性能 |
| location 准确率 | ≥ 0.70 | 标距内/外判断准确率（补标后） |

---

## 2. 技术决策记录（ADR）

以下决策已与项目团队确认，记录如下：

| 决策项 | 选定方案 | 理由 |
|---|---|---|
| 子视频存储 | **A. 独立 `.mp4` 文件** | LLaMA-Factory 对独立视频文件兼容性最好，训练逻辑简单清晰，避免自定义数据加载器 |
| `location` 标注 | 先占位（`"to_be_annotated"`），后续人工补标复核 | 当前标注数据缺失，不阻塞开发进度；补标后重新生成相关样本即可 |
| 断裂帧号 | 自动计算 `event_frame_original = round(event_time × FPS)`，后续人工复核 | 基于现有 `event_time` 标注可快速启动训练；复核后更新 `video_meta.json` |
| 训练框架 | **LLaMA-Factory** | 团队已熟悉该框架，现有基础设施（环境、配置模板、训练脚本）可直接复用 |
| 划分策略 | **按原始视频划分 + 3-fold 交叉验证** | 保证同一原始视频的所有子视频不跨训练/验证/测试集合，避免数据泄漏 |
| 旧代码处理 | 全部删除，全新工作流 | 旧方案架构差异大，保留反而增加维护成本 |

---

## 3. 模块架构

### M1: 元数据管理

**输入**
- `data/02_annotations/all_videos_tag.csv`：原始标注 CSV（含 `event_time`, `type` 等）
- `data/01_videos/*.mp4`：原始视频文件

**处理流程**
1. 读取视频元信息：使用 `ffprobe` 或 OpenCV (`cv2`) 提取 `fps`, `total_frames`, `duration`
2. 计算断裂帧号：`event_frame_original = round(event_time * fps)`
3. `location` 字段占位：若 CSV 中无该字段，统一填充为 `"to_be_annotated"`
4. 异常标记：根据 `type` 字段识别早期断裂、未断裂、未夹紧、视频异常等样本，标记 `is_abnormal`

**输出**
- `data/metadata/video_meta.json`：结构化元数据文件

**Schema（单条记录）**

```json
{
  "video_id": "video_0001",
  "video_path": "data/01_videos/video_0001.mp4",
  "fps": 30.0,
  "total_frames": 15000,
  "duration": 500.0,
  "event_time": 145.4,
  "event_frame_original": 4362,
  "type": "韧性断裂",
  "location": "to_be_annotated",
  "has_fracture": true,
  "is_abnormal": false
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `video_id` | string | 视频唯一标识 |
| `video_path` | string | 原始视频文件路径 |
| `fps` | float | 视频帧率 |
| `total_frames` | int | 总帧数 |
| `duration` | float | 视频时长（秒） |
| `event_time` | float | 标注断裂时刻（秒） |
| `event_frame_original` | int | 计算断裂帧号（`round(event_time * fps)`） |
| `type` | string | 断裂类型（韧性断裂/脆性断裂/...） |
| `location` | string | 标距内/外位置（当前占位） |
| `has_fracture` | bool | 是否发生断裂 |
| `is_abnormal` | bool | 是否为异常样本 |

---

### M2: 子视频生成 + 训练样本构建

> **本模块为最复杂模块**，负责原始视频划分、子视频裁剪、帧采样标签计算、训练格式转换。

**输入**
- M1 输出：`data/metadata/video_meta.json`
- 原始视频：`data/01_videos/*.mp4`

#### Step 1 — 原始视频划分

1. **测试集划分**：按原始视频级别，随机抽取 20% 作为 Test 集（`test_ratio = 0.2`）
2. **训练集内 3-fold**：剩余 80% 视频进行 stratified 3-fold，分层变量为 `type + location`（若 location 为占位值，则仅按 type 分层）
3. **标签生成**：每个原始视频标记以下标签之一：
   - `test`
   - `fold_0_train` / `fold_0_val`
   - `fold_1_train` / `fold_1_val`
   - `fold_2_train` / `fold_2_val`

> **划分原则**：同一原始视频的所有子视频必须归属同一集合，禁止跨集合泄漏。

#### Step 2 — 子视频类型（7 种）

所有子视频均从原始视频中截取，共 7 种类型：

| 类型 | 说明 | `has_fracture` | 配置参数 |
|---|---|---|---|
| 1. **全时长** | 原始视频本身，作为基准样本 | true / false | — |
| 2. **局部聚焦 — 短窗口** | 围绕断裂帧，窗口 3s，断裂点位于子视频内不同位置 | true | `focus_windows[0] = 3` |
| 3. **局部聚焦 — 中窗口** | 同上，窗口 10s | true | `focus_windows[1] = 10` |
| 4. **局部聚焦 — 长窗口** | 同上，窗口 30s | true | `focus_windows[2] = 30` |
| 5. **负样本 — 断裂前** | 断裂时刻之前片段（如断裂前 5s ~ 断裂前 1s） | false | `neg_before_duration = 5` |
| 6. **负样本 — 断裂后** | 断裂时刻之后片段（如断裂后 1s ~ 断裂后 5s） | false | `neg_after_duration = 5` |
| 7. **负样本 — 未断裂视频** | 未断裂视频的任意片段 | false | — |

**局部聚焦窗口的位置比例**：

断裂点在子视频中的位置比例可取以下 5 个值：
- `focus_positions = [0.2, 0.35, 0.5, 0.65, 0.8]`

即：对于窗口大小 `W`，子视频时间范围为 `[event_time - W * ratio, event_time + W * (1 - ratio)]`。

> 窗口大小和位置比例均可通过 YAML 配置调整。

#### Step 3 — 子视频生成

- 使用 `ffmpeg` 或 OpenCV 截取时间区间
- 输出路径：`data/02_subvideos/{video_id}_{crop_type}_{idx}.mp4`
- 命名示例：`video_0001_focus_3s_50pct.mp4`
- 记录子视频元数据（见第 5 节 Schema）

#### Step 4 — 帧采样与标签计算

对每个子视频执行以下操作：

1. **均匀采样固定帧数**：`sample_frame_count = 36`（可配置）
2. **计算每个采样帧的对应信息**：
   - `sampled_frame[i].original_frame`：该采样帧在原始视频中的帧号
   - `sampled_frame[i].timestamp`：该采样帧在原始视频中的时间戳
3. **计算 `fracture_between`**：找到唯一的 `[i, i+1]` 使得：
   ```
   sampled_frame[i].original_frame <= event_frame_original < sampled_frame[i+1].original_frame
   ```
4. **负样本**：`has_fracture = false`，`fracture_between = null`

#### Step 5 — 训练格式转换（LLaMA-Factory 对话格式）

将每个子视频转换为一个 LLaMA-Factory 多模态对话样本：

```json
{
  "id": "video_0001_focus_3s_50pct",
  "video": "data/02_subvideos/video_0001_focus_3s_50pct.mp4",
  "conversations": [
    {
      "from": "system",
      "value": "你是一个材料拉伸试验视频分析助手。请根据视频内容回答用户问题，输出必须为合法 JSON 格式。"
    },
    {
      "from": "human",
      "value": "请分析这段拉伸试验视频，判断是否存在断裂。如果存在，请指出断裂发生在哪两帧之间，并判断断裂模式和标距内位置。"
    },
    {
      "from": "gpt",
      "value": "{\"has_fracture\": true, \"fracture_between\": [17, 18], \"type\": \"韧性断裂\", \"location\": \"inside_gauge\", \"confidence\": 0.92}"
    }
  ]
}
```

**输出文件清单**

| 文件 | 路径 | 说明 |
|---|---|---|
| 子视频文件 | `data/02_subvideos/*.mp4` | 所有裁剪后的子视频 |
| 训练 JSON | `data/04_new_merged/fold_{0,1,2}_{train,val}.json` | 3-fold 训练/验证集 |
| 测试 JSON | `data/04_new_merged/test.json` | 测试集 |
| 样本元数据 | `data/04_new_merged/samples_meta.json` | 所有样本的元信息索引 |

---

### M3: 训练配置与 Prompt 设计

#### Prompt 设计规范

Prompt 不再使用固定模板，而是由 Meta-Agent 每轮动态构建。Agent 在生成 `parameters.prompt` 时必须包含以下要素：

1. **角色设定**：明确模型的身份（如"你是一个材料拉伸试验视频分析助手"）。
2. **任务描述**：当前需要分析什么（如"请判断这段视频是否包含断裂"）。
3. **输入说明**：这是一段拉伸试验视频的哪个区间（时间范围、帧数等）。
4. **输出格式要求**：严格合法的 JSON schema，包含 `has_fracture`、`fracture_between`、`type`、`location`、`confidence` 字段。
5. **可选上下文提示**：基于历史结果的提示（如"前几轮分析显示断裂可能发生在 150~160 秒区间，请重点关注"）。

> 注：Agent 可根据当前迭代阶段调整 prompt 的措辞和重点，例如初期侧重"有无断裂"，后期侧重"精确边界"。

#### 微调模型的 System Prompt 模板

以下是给微调模型（MiniCPM-V）的固定 System Prompt，Agent 在此基础上追加动态构建的用户问题：

```
你是一个材料拉伸试验视频分析助手。你的任务是分析给定的视频片段，判断试样是否发生断裂。

如果存在断裂，请回答：
1. 断裂发生在哪两帧之间（用帧索引表示，如 [17, 18]）
2. 断裂类型（如：韧性断裂、脆性断裂）
3. 断裂位置是否在标距内（inside_gauge / outside_gauge）
4. 你对判断的置信度（confidence，0.0 ~ 1.0 的浮点数）

如果判断不存在断裂，has_fracture 为 false，fracture_between 为 null，type 和 location 可填 "none"，confidence 仍需给出（表示你对"无断裂"判断的置信度）。

输出必须为严格合法的 JSON 格式，不要包含任何其他解释文字。confidence 字段为必填项。
输出 Schema：{"has_fracture": bool, "fracture_between": [int, int]或null, "type": str, "location": str, "confidence": float}
```

#### LLaMA-Factory YAML 配置要点

```yaml
# 关键配置项
model_name_or_path: openbmb/MiniCPM-V-2_6  # 或对应 4.6 版本路径
template: minicpm_v
dataset: fracture_interval_sft  # 在 dataset_info.json 中注册
video_maxlen: 36  # 每轮采样帧数
cutoff_len: 2048

# LoRA 参数
lora_target: all
lora_rank: 8
lora_alpha: 16
lora_dropout: 0.05

# 训练参数
per_device_train_batch_size: 1
gradient_accumulation_steps: 8
learning_rate: 1.0e-4
num_train_epochs: 3
warmup_ratio: 0.03
```

#### dataset_info.json 注册

在 LLaMA-Factory 的 `dataset_info.json` 中新增条目：

```json
{
  "fracture_interval_sft": {
    "file_name": "fold_0_train.json",
    "formatting": "sharegpt",
    "columns": {
      "messages": "conversations",
      "videos": "video"
    },
    "tags": {
      "role_tag": "from",
      "content_tag": "value",
      "user_tag": "human",
      "assistant_tag": "gpt",
      "system_tag": "system"
    }
  }
}
```

> **注意**：3-fold 训练时，每折需分别替换 `file_name` 为对应 fold 的训练集路径。

#### 训练数据 confidence 标注规范

- **Ground truth 样本**：所有训练样本的 `confidence` 均标注为 `1.0`，即假设人工标注和自动计算标签是确定的。
- **负样本**：`has_fracture: false` 的样本同样标注 `confidence: 1.0`，表示"该片段确实不包含断裂"是确定事实。
- 模型在推理时自报的 `confidence` 反映其对当前输入的主观不确定性，与训练标签的 `1.0` 含义不同。

#### 模型输出 JSON 示例

```json
{
  "has_fracture": true,
  "fracture_between": [17, 18],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.92
}
```

负样本输出示例：

```json
{
  "has_fracture": false,
  "fracture_between": null,
  "type": "none",
  "location": "none",
  "confidence": 0.95
}
```

---

### M4: 模型微调训练

**训练流程**

1. **3-fold 独立训练**：对每一折分别执行完整训练流程
   - Fold 0：`fold_0_train.json` 训练，`fold_0_val.json` 验证
   - Fold 1：`fold_1_train.json` 训练，`fold_1_val.json` 验证
   - Fold 2：`fold_2_train.json` 训练，`fold_2_val.json` 验证

2. **Checkpoint 保存路径**：
   ```
   finetune/saves/minicpmv4_6/lora/new_sft_fold_0/
   finetune/saves/minicpmv4_6/lora/new_sft_fold_1/
   finetune/saves/minicpmv4_6/lora/new_sft_fold_2/
   ```

3. **验证策略**：每轮 epoch 后在验证集上评估 JSON 输出准确率，保存最佳 checkpoint。

---

### M5: Meta-Agent 驱动的迭代推理框架

#### Agent LLM 后端架构

Agent 与 LLM 的交互采用 **Native Function Calling** 协议：模型输出标准 `tool_calls` 字段，Agent Loop 解析 `tool_calls` 后执行对应 Tool，并将结果回传给模型。**不引入 MCP**。

开发阶段可根据需要选择远程 API 或本地部署，模型由配置决定。

**统一接口设计（抽象基类）**：

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class BaseAgentLLM(ABC):
    """Agent 大脑的统一接口，屏蔽本地/远程差异"""
    
    @abstractmethod
    def chat_with_tools(
        self, 
        messages: List[Dict[str, Any]], 
        tools: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> Any:
        """
        调用模型，支持 function calling
        
        Args:
            messages: OpenAI-compatible messages 列表
            tools: OpenAI-compatible tools schema 列表
            temperature: 采样温度
            max_tokens: 最大生成 token 数
            
        Returns:
            OpenAI-compatible ChatCompletion 对象
            包含 .choices[0].message.content 和 .choices[0].message.tool_calls
        """
        pass
    
    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称"""
        pass
```

**远程 API Client（通用 OpenAI-compatible）**：

```python
import os
from openai import OpenAI

class RemoteAPIClient(BaseAgentLLM):
    """
    远程 API 客户端（通用 OpenAI-compatible）
    
    支持任意 OpenAI-compatible API 提供商，包括但不限于：
    - 阿里云百炼 (dashscope): https://dashscope.aliyuncs.com/compatible-mode/v1
    - SiliconFlow: https://api.siliconflow.cn/v1
    - OpenAI: https://api.openai.com/v1
    - Together AI: https://api.together.xyz/v1
    - 任何其他兼容 OpenAI API 格式的服务
    """
    
    def __init__(
        self, 
        model: str, 
        api_key: str,
        base_url: str,
        provider: str = "custom"  # 仅用于日志标识，如 "dashscope", "siliconflow", "openai"
    ):
        self._model = model
        self._provider = provider
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    
    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=None):
        kwargs = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        return self.client.chat.completions.create(**kwargs)
    
    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"
```

**本地部署 Client（通用 OpenAI-compatible 本地端点）**：

```python
class LocalClient(BaseAgentLLM):
    """
    本地部署客户端（通用 OpenAI-compatible 本地端点）
    
    支持任意提供 OpenAI-compatible API 的本地推理工具，包括但不限于：
    - Ollama: http://localhost:11434/v1
    - vLLM: http://localhost:8000/v1
    - llama.cpp (server mode): http://localhost:8080/v1
    - 任何其他兼容 OpenAI API 格式的本地端点
    """
    
    def __init__(
        self, 
        model: str,
        base_url: str = "http://localhost:11434/v1",
        provider: str = "ollama"  # 仅用于日志标识，如 "ollama", "vllm", "llamacpp"
    ):
        self._model = model
        self._provider = provider
        self.client = OpenAI(api_key="EMPTY", base_url=base_url)
    
    def chat_with_tools(self, messages, tools, temperature=0.7, max_tokens=None):
        kwargs = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        
        return self.client.chat.completions.create(**kwargs)
    
    @property
    def model_name(self) -> str:
        return f"{self._provider}/{self._model}"
```

**工厂方法**：

```python
class AgentLLMFactory:
    """根据配置创建对应的 LLM Client"""
    
    @staticmethod
    def create(config: dict) -> BaseAgentLLM:
        backend = config.get("backend", "remote")
        
        if backend == "remote":
            api_key = config.get("api_key") or os.getenv("LLM_API_KEY")
            if not api_key:
                raise ValueError("远程模式需要提供 api_key 或设置 LLM_API_KEY 环境变量")
            
            return RemoteAPIClient(
                model=config["model"],  # 任意模型名，直接透传
                api_key=api_key,
                base_url=config["base_url"],
                provider=config.get("provider", "custom")
            )
        
        elif backend == "local":
            return LocalClient(
                model=config["model"],  # 任意模型名，直接透传
                base_url=config.get("base_url", "http://localhost:11434/v1"),
                provider=config.get("provider", "ollama")
            )
        
        else:
            raise ValueError(f"不支持的后端: {backend}，请使用 'remote' 或 'local'")
```

**配置示例**：

```yaml
# config/agent.yaml
agent:
  # 后端类型: remote (远程API) | local (本地部署)
  backend: "remote"
  
  # ==========================================
  # 远程 API 配置
  # ==========================================
  remote:
    # provider: 仅用于日志标识，可选值如 dashscope, siliconflow, openai, together 等
    # 不影响实际调用，只帮助区分不同提供商的日志
    provider: "dashscope"
    
    # model: 模型名称，完全由提供商决定，代码直接透传
    # 百炼示例: qwen2.5-7b-instruct, qwen2.5-14b-instruct, qwen2.5-32b-instruct, qwen-max, qwen-plus...
    # SiliconFlow 示例: Qwen/Qwen2.5-14B-Instruct, deepseek-ai/DeepSeek-V3...
    # OpenAI 示例: gpt-4o, gpt-4o-mini...
    model: "qwen2.5-14b-instruct"
    
    # base_url: API 基础地址
    # 百炼: https://dashscope.aliyuncs.com/compatible-mode/v1
    # SiliconFlow: https://api.siliconflow.cn/v1
    # OpenAI: https://api.openai.com/v1
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    
    # api_key: API 密钥
    # 可在此硬编码（不推荐），或从环境变量 LLM_API_KEY 读取
    api_key: null
  
  # ==========================================
  # 本地部署配置
  # ==========================================
  local:
    # provider: 仅用于日志标识，可选值如 ollama, vllm, llamacpp 等
    provider: "ollama"
    
    # model: 模型名称，由本地服务决定，代码直接透传
    # Ollama 示例: qwen2.5:7b, qwen2.5:14b, llama3.1:8b...
    # vLLM 示例: Qwen/Qwen2.5-7B-Instruct, meta-llama/Llama-3.1-8B-Instruct...
    model: "qwen2.5:7b"
    
    # base_url: 本地服务端点
    # Ollama: http://localhost:11434/v1
    # vLLM: http://localhost:8000/v1
    # llama.cpp: http://localhost:8080/v1
    base_url: "http://localhost:11434/v1"
```

> **关于模型选择的灵活性设计**
>
> Agent LLM 层采用"完全透传"策略，代码不维护任何硬编码的模型支持列表。原因如下：
> 1. **模型迭代快**：各大模型厂商不断更新模型版本，硬编码列表需要频繁维护
> 2. **多提供商支持**：用户可能在不同项目中使用百炼、SiliconFlow、OpenAI 等不同服务，统一接口降低切换成本
> 3. **用户自主权**：用户最了解自己需要什么模型，代码不应做不必要的限制
> 4. **责任边界**：模型可用性、function calling 能力、价格等由用户和提供商决定，代码只负责正确调用
>
> 用户在选择模型时需要自行确认：
> - 该模型是否支持 function calling（tool use）
> - 该模型在当前任务上的推理质量是否满足需求
> - API 配额和成本是否在预算内
>
> 推荐的模型组合（基于当前测试经验）：
> - **开发阶段**：百炼 qwen2.5-14b-instruct（function calling 稳定，性价比高）
> - **本地测试**：Ollama qwen2.5:7b（轻量，MacBook Air M4 可流畅运行）
> - **生产增强**：百炼 qwen2.5-32b-instruct 或 qwen-max（推理能力更强，成本更高）

#### 架构概述

```
┌─────────────────────────────────────────────────────────────┐
│              Agent Loop（迭代控制器）                         │
│                                                             │
│  1. 构建 messages（system + user context + history）         │
│  2. 调用 LLM.chat_with_tools(messages, tools)                │
│  3. 解析 response.choices[0].message.tool_calls              │
│  4. 执行 Tool → 结果回传为 tool 消息                         │
│  5. 循环直至 terminate 或达到 max_rounds                     │
│                                                             │
│  LLM 后端：DashScope（百炼）/ Ollama（本地），可配置切换      │
│                                                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                   Tool 执行层（通用代码）                      │
│                                                             │
│  1. VideoSampler：根据 tool_args 抽帧 → 输出帧序列             │
│  2. InferenceClient：使用 tool_args.prompt 调用微调模型        │
│     （MiniCPM-V via LLaMA-Factory）                          │
│  3. ResultParser：按 tool_args.expected_schema 解析模型输出   │
│  4. 返回结构化结果给 Agent Loop                               │
│                                                             │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
              本轮结果 → 追加到 history → 回到 Agent Loop
```

#### Tool Schema 定义

Agent 注册给模型的可用工具如下。模型通过 Native Function Calling 输出 `tool_calls`，Agent Loop 解析后执行：

```python
# Agent 注册给模型的可用工具
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "sample_and_infer",
            "description": "在指定时间区间内采样视频帧，调用微调模型进行推理",
            "parameters": {
                "type": "object",
                "properties": {
                    "sample_range": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "采样时间区间 [start_seconds, end_seconds]"
                    },
                    "num_frames": {
                        "type": "integer",
                        "description": "采样帧数",
                        "default": 36
                    },
                    "sampling_strategy": {
                        "type": "string",
                        "enum": ["uniform", "adaptive"],
                        "description": "采样策略：uniform=均匀采样，adaptive=自适应采样（断裂点附近更密）",
                        "default": "uniform"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "发送给微调模型的完整 prompt"
                    },
                    "expected_schema": {
                        "type": "object",
                        "description": "期望模型输出的 JSON schema"
                    }
                },
                "required": ["sample_range", "prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "terminate",
            "description": "终止迭代，返回最终分析结果",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_range": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "最终断裂时间区间 [start_seconds, end_seconds]"
                    },
                    "time_estimate": {
                        "type": "number",
                        "description": "断裂时间估计值（区间中点或模型最可能值）"
                    },
                    "frame_range": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "最终断裂帧区间 [start_frame, end_frame]"
                    },
                    "type": {
                        "type": "string",
                        "description": "断裂模式"
                    },
                    "location": {
                        "type": "string",
                        "description": "标距内位置判断"
                    },
                    "confidence": {
                        "type": "number",
                        "description": "最终置信度 0-1"
                    },
                    "confidence_level": {
                        "type": "string",
                        "enum": ["高", "中", "低", "不可信"],
                        "description": "置信度等级"
                    }
                },
                "required": ["time_range", "time_estimate", "type", "location", "confidence", "confidence_level"]
            }
        }
    }
]
```

#### Agent Loop 伪代码

```python
class IterativeAgent:
    def __init__(self, llm_client: BaseAgentLLM, video_meta: dict, config: dict):
        self.llm = llm_client
        self.video_meta = video_meta
        self.config = config
        self.history = []
        self.max_rounds = config.get("max_rounds", 10)
        self.tolerance = config.get("tolerance_seconds", 1.0)
    
    def run(self) -> dict:
        """主循环"""
        messages = self._build_system_messages()
        
        for round in range(self.max_rounds):
            # 1. 调用 Agent LLM
            response = self.llm.chat_with_tools(
                messages=messages,
                tools=TOOLS_SCHEMA,
                temperature=0.7
            )
            
            message = response.choices[0].message
            
            # 2. 记录中间过程
            self._log_round(round, message)
            
            # 3. 检查是否有 tool_calls
            if not message.tool_calls:
                # 模型直接回答了（异常情况，应要求重新输出）
                messages.append({"role": "assistant", "content": message.content})
                messages.append({"role": "user", "content": "请使用 tool_calls 输出你的决策。"})
                continue
            
            # 4. 处理 tool_calls
            tool_call = message.tool_calls[0]  # 每次只取第一个
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)
            
            # 5. 执行 Tool
            if tool_name == "terminate":
                return self._finalize(tool_args)
            elif tool_name == "sample_and_infer":
                result = self._execute_sample_and_infer(tool_args)
            else:
                raise ValueError(f"未知工具: {tool_name}")
            
            # 6. 构建下一轮 messages
            messages.append({
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [{
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_call.function.arguments
                    }
                }]
            })
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False)
            })
        
        # 超过最大轮数，强制终止
        return self._force_terminate()
    
    def _execute_sample_and_infer(self, args: dict) -> dict:
        """执行 sample_and_infer 工具"""
        # 视频抽帧
        frames = VideoSampler.sample(
            video_path=self.video_meta["video_path"],
            sample_range=args["sample_range"],
            num_frames=args.get("num_frames", 36),
            strategy=args.get("sampling_strategy", "uniform")
        )
        
        # 调用微调模型
        raw_output = InferenceClient.infer(frames, args["prompt"])
        
        # 解析结果
        parsed = ResultParser.parse(raw_output, args.get("expected_schema"))
        
        # 换算 fracture_between 到原视频时间
        if parsed.get("has_fracture") and parsed.get("fracture_between"):
            time_range = self._convert_to_time_range(frames, parsed["fracture_between"])
            parsed["inferred_time_range"] = time_range
        
        return parsed
    
    def _log_round(self, round: int, message):
        """记录中间过程"""
        log_entry = {
            "round": round,
            "model": self.llm.model_name,
            "reasoning": message.content,
            "tool_calls": [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments)
                } for tc in (message.tool_calls or [])
            ]
        }
        self.history.append(log_entry)
        logger.info(f"Round {round}: {json.dumps(log_entry, ensure_ascii=False)}")
    
    def _finalize(self, args: dict) -> dict:
        """正常终止"""
        return {
            **args,
            "video_id": self.video_meta["video_id"],
            "rounds": len(self.history),
            "history": self.history
        }
```

#### Agent System Prompt 设计

Agent 的 System Prompt 需明确角色、可用工具、决策逻辑和输出约束。以下是 System Prompt 模板：

```
# 角色定义
你是材料拉伸试验视频分析协调者。你的核心目标是通过多轮迭代，利用视频分析模型定位材料拉伸试验视频中的断裂时刻。

# 可用工具
你拥有两个工具，必须通过 function calling 调用：
1. sample_and_infer：在指定视频区间采样固定帧数，调用微调后的多模态模型（MiniCPM-V）进行推理，返回结构化结果。
2. terminate：当你认为已经定位到足够精确的断裂时刻时，调用此工具终止迭代并输出最终结果。

# 核心目标
通过多轮迭代缩小断裂时间范围，最终给出包含断裂时刻区间、断裂类型、位置及综合置信度的结果。

# 决策规则
1. 初始区间为 [0, duration]（全视频）。
2. 每轮根据历史迭代记录决定下一步操作。
3. 可以动态调整 prompt 的措辞和重点。
4. 可以要求不同的采样策略（uniform / adaptive）。
5. 当区间宽度 ≤ tolerance 或达到最大轮数时，必须调用 terminate。

# 最终 confidence 判断指南（参考框架，非硬编码公式）
调用 terminate 时，请综合以下因素给出 0~1 的综合 confidence：
- 多轮模型自报 confidence 的平均值和趋势
- type 和 location 在多轮中的一致性
- 采样区间是否有效收敛
- 分级标准：高(0.9~1.0) / 中(0.7~0.89) / 低(0.5~0.69) / 不可信(0.0~0.49)

# 注意事项
- sample_range 必须在视频总时长范围内。
- prompt 应包含角色设定、任务描述、输入说明和输出格式要求。
- 必须通过 tool_calls 输出你的决策，不要直接文本回答。
```

#### Agent 输入上下文格式

每轮提交给 Meta-Agent 的完整 prompt 结构如下：

```
[视频元信息]
视频ID: {video_id}
总时长: {duration}s
FPS: {fps}
总帧数: {total_frames}

[配置参数]
容忍误差: {tolerance}s
最大迭代轮数: {max_rounds}
当前轮次: {current_round}/{max_rounds}

[历史迭代记录]
轮次1:
- 采样区间: [0, 500]s
- 模型输出: {"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.85}
- 换算后区间: [145, 155]s
...

[当前状态]
当前候选区间: [150, 160]s
区间宽度: 10s

请通过 tool_calls 输出你的下一步决策。
```

#### Tool 执行层接口定义

Tool 执行层为通用代码，不硬编码任何业务逻辑，仅按 Action Plan 执行：

- **`VideoSampler.sample(video_path, sample_range, num_frames, strategy)`**
  - 输入：视频路径、采样时间区间（秒）、采样帧数、策略（`uniform` / `adaptive`）
  - 输出：帧序列列表，每项含 `input_index`, `original_frame`, `timestamp`

- **`InferenceClient.infer(frames, prompt)`**
  - 输入：帧序列（由 VideoSampler 输出）、动态 prompt（来自 Action Plan）
  - 输出：微调模型（MiniCPM-V via LLaMA-Factory）的原始文本响应

- **`ResultParser.parse(raw_text, expected_schema)`**
  - 输入：模型原始文本、expected_schema（来自 Action Plan）
  - 输出：结构化 JSON，若解析失败返回 `null`

#### 停止条件（双层保险）

| 层级 | 条件 | 处理逻辑 |
|---|---|---|
| **Agent 层** | Agent 在 reasoning 中自主判断终止 | Agent 调用 `terminate` tool，给出最终输出参数 |
| **代码层保底 1** | Agent 调用 terminate 但区间宽度 > tolerance | 代码层拒绝终止，在 tool result 中提示 Agent 继续迭代 |
| **代码层保底 2** | 超过 `max_rounds` | 强制终止，代码层构造 final_output，无论区间是否收敛 |
| **代码层保底 3** | 连续 `max_low_conf_rounds` 轮模型自报 confidence < threshold | 代码层在 tool result 中提示 Agent 考虑终止；Agent 可采纳或继续 |

#### 最终输出 Schema

```json
{
  "video_id": "video_0001",
  "time_range": [158.42, 159.08],
  "time_estimate": 158.75,
  "frame_range": [4752, 4772],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.79,
  "confidence_level": "高",
  "rounds": 5,
  "status": "converged",
  "history": [
    {
      "round": 0,
      "range": [0.0, 500.0],
      "has_fracture": true,
      "fracture_between": [17, 18],
      "type": "韧性断裂",
      "location": "inside_gauge",
      "confidence": 0.92
    }
  ]
}
```

---

### M6: 评估体系

#### 评估指标定义与计算

| 指标 | 定义 | 计算公式 |
|---|---|---|
| **区间命中率** | 预测区间包含真实断裂时间的比例 | `hit = (time_range[0] <= event_time <= time_range[1])` |
| **within_1s** | 点估计与真实时间绝对误差 ≤ 1s 的比例 | `\|time_estimate - event_time\| <= 1.0` |
| **within_3s** | 点估计与真实时间绝对误差 ≤ 3s 的比例 | `\|time_estimate - event_time\| <= 3.0` |
| **within_5s** | 点估计与真实时间绝对误差 ≤ 5s 的比例 | `\|time_estimate - event_time\| <= 5.0` |
| **time MAE** | 时间估计的平均绝对误差 | `MAE = mean(\|time_estimate - event_time\|)` |
| **type accuracy** | 断裂类型分类准确率 | 正确预测 type 的样本比例 |
| **type macro-F1** | 断裂类型分类宏平均 F1 | 各类 F1 的算术平均 |
| **location accuracy** | 标距位置判断准确率 | 正确预测 location 的样本比例（补标后） |
| **异常样本失败率** | 异常样本中预测失败的占比 | 早期断裂、未断裂、未夹紧、视频异常等子集的错误率 |
| **置信度-误差相关性** | 模型自报 confidence 与预测误差的相关性 | Pearson / Spearman 相关系数 |
| **不同 confidence 阈值下的区间命中率** | 在 `final_confidence ≥ threshold` 子集上计算的区间命中率 | 阈值可取 0.5 / 0.7 / 0.9 |
| **reliability diagram** | confidence vs accuracy 的校准曲线 | 横轴为 confidence 分桶，纵轴为对应桶的实际准确率 |
| **低 confidence 样本错误率** | `final_confidence < 0.5` 的样本中，预测失败（区间未命中或 type/location 错误）的比例 | 用于验证低置信度预警的有效性 |

#### 置信度专项评估

1. **可靠性图（Reliability Diagram）**：将 `final_confidence` 分成若干桶（如 0.0~0.1, 0.1~0.2, ...），计算每个桶内的实际准确率。理想情况下，confidence 为 0.8 的桶准确率应接近 0.8。若模型系统性地高估自身信心（overconfidence），则实际准确率显著低于 confidence 值。
2. **阈值分析**：报告 `final_confidence ≥ 0.5 / 0.7 / 0.9` 时的区间命中率和 within_1s/3s/5s 指标，验证高置信度预测是否确实更可靠。
3. **低置信度失败率**：统计 `final_confidence < 0.5` 的样本中，真实区间未命中或 type/location 预测错误的占比。该值应显著高于高置信度样本的错误率，否则说明 confidence 信号无效。

#### 对比基准

所有指标需与**旧方案在同一批测试集**上的表现进行对比，评估相对提升：

| 对比维度 | 说明 |
|---|---|
| 旧方案 vs 新方案（单轮） | 新方案仅使用第一轮（全时长视频）的预测结果 |
| 旧方案 vs 新方案（完整迭代） | 新方案完整迭代后的最终结果 |
| 3-fold 平均 | 报告 3-fold 交叉验证的平均指标 ± 标准差 |

---

## 4. 数据流图

```
原始视频 (data/01_videos/*.mp4)
    + 标注 CSV (data/02_annotations/all_videos_tag.csv)
    |
    v
┌─────────────────────────────────────┐
│  M1: 元数据提取                       │
│  - ffprobe / cv2 提取 fps/帧数/时长   │
│  - 计算 event_frame_original          │
│  - location 占位 + 异常标记            │
└─────────────────────────────────────┘
    |
    v  data/metadata/video_meta.json
┌─────────────────────────────────────┐
│  M2: 划分 + 子视频生成 + 样本构建       │
│  - Step 1: 原始视频 3-fold 划分        │
│  - Step 2: 生成 7 种类型子视频         │
│  - Step 3: ffmpeg 裁剪                │
│  - Step 4: 帧采样 + 标签计算            │
│  - Step 5: LLaMA-Factory 格式转换      │
└─────────────────────────────────────┘
    |
    +--> data/02_subvideos/*.mp4
    +--> data/04_new_merged/fold_*_{train,val}.json
    +--> data/04_new_merged/test.json
    |
    v
┌─────────────────────────────────────┐
│  M3: Prompt 规范 + 训练配置            │
│  - Prompt 设计规范（Agent 动态构建）    │
│  - 微调模型 System Prompt 模板          │
│  - LLaMA-Factory YAML 配置            │
│  - dataset_info.json 注册             │
└─────────────────────────────────────┘
    |
    v
┌─────────────────────────────────────┐
│  M4: 模型微调训练 (LLaMA-Factory)     │
│  - 3-fold 独立训练                    │
│  - 输出 checkpoints                   │
└─────────────────────────────────────┘
    |
    v  finetune/saves/minicpmv4_6/lora/new_sft_fold*/
┌─────────────────────────────────────────────────────────────┐
│  M5: Meta-Agent 驱动的迭代推理框架                            │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Agent Loop（迭代控制器）                              │   │
│  │ - LLM 后端：DashScope（百炼）/ Ollama（本地），可配置 │   │
│  │ - 协议：Native Function Calling（tool_calls）        │   │
│  │ 输入：视频元信息 + 历史迭代记录（messages）            │   │
│  │ 输出：tool_calls → 执行 Tool → 结果回传               │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         ▼                                   │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ Tool 执行层（通用代码）                               │   │
│  │ - VideoSampler：按 tool_args 抽帧                    │   │
│  │ - InferenceClient：调用微调模型（MiniCPM-V）          │   │
│  │ - ResultParser：按 expected_schema 解析              │   │
│  └──────────────────────┬──────────────────────────────┘   │
│                         │                                   │
│                         └──→ 结果追加到历史记录 → 回到 Agent Loop│
│                                                             │
│  终止时：Agent 输出 final_output（含综合 confidence）        │
└─────────────────────────────────────────────────────────────┘
    |
    v  预测结果 JSON
┌─────────────────────────────────────┐
│  M6: 评估体系                         │
│  - 区间命中率 / within_1s/3s/5s       │
│  - type F1 / location 准确率          │
│  - 异常样本分析 / 置信度-误差相关性     │
│  - 与旧方案对比报告                    │
└─────────────────────────────────────┘
    |
    v  评估报告
```

---

## 5. 关键数据结构 Schema

### video_meta.json（单条记录）

```json
{
  "video_id": "video_0001",
  "video_path": "data/01_videos/video_0001.mp4",
  "fps": 30.0,
  "total_frames": 15000,
  "duration": 500.0,
  "event_time": 145.4,
  "event_frame_original": 4362,
  "type": "韧性断裂",
  "location": "to_be_annotated",
  "has_fracture": true,
  "is_abnormal": false
}
```

### 子视频元数据（单条）

```json
{
  "subvideo_id": "video_0001_focus_3s_50pct",
  "source_video": "video_0001",
  "video_path": "data/02_subvideos/video_0001_focus_3s_50pct.mp4",
  "start_time": 143.9,
  "end_time": 146.9,
  "duration": 3.0,
  "crop_type": "focus_short",
  "event_position_ratio": 0.5,
  "fold": "fold_0_train",
  "split": "train"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `subvideo_id` | string | 子视频唯一标识 |
| `source_video` | string | 来源原始视频 ID |
| `video_path` | string | 子视频文件路径 |
| `start_time` | float | 在原始视频中的起始时间（秒） |
| `end_time` | float | 在原始视频中的结束时间（秒） |
| `duration` | float | 子视频时长（秒） |
| `crop_type` | string | 裁剪类型（见 M2 Step 2） |
| `event_position_ratio` | float/null | 断裂点在子视频中的位置比例 |
| `fold` | string | 所属 fold 及集合 |
| `split` | string | `train` / `val` / `test` |

### 训练样本（LLaMA-Factory 格式）

```json
{
  "id": "video_0001_focus_3s_50pct",
  "video": "data/02_subvideos/video_0001_focus_3s_50pct.mp4",
  "conversations": [
    {
      "from": "system",
      "value": "你是一个材料拉伸试验视频分析助手..."
    },
    {
      "from": "human",
      "value": "请分析这段视频..."
    },
    {
      "from": "gpt",
      "value": "{\"has_fracture\": true, \"fracture_between\": [17, 18], \"type\": \"韧性断裂\", \"location\": \"inside_gauge\", \"confidence\": 0.92}"
    }
  ]
}
```

### 模型输出（推理时）

```json
{
  "has_fracture": true,
  "fracture_between": [17, 18],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.92
}
```

### Agent 最终输出

```json
{
  "video_id": "video_0001",
  "time_range": [158.42, 159.08],
  "time_estimate": 158.75,
  "frame_range": [4752, 4772],
  "type": "韧性断裂",
  "location": "inside_gauge",
  "confidence": 0.79,
  "rounds": 5,
  "status": "converged",
  "history": [
    {
      "round": 0,
      "range": [0.0, 500.0],
      "has_fracture": true,
      "fracture_between": [17, 18],
      "type": "韧性断裂",
      "location": "inside_gauge",
      "confidence": 0.92
    }
  ]
}
```

---

## 6. 配置参数汇总

所有可配置参数集中管理，建议通过 YAML 文件（如 `config/frame_interval.yaml`）维护：

| 参数名 | 默认值 | 说明 |
|---|---|---|
| `sample_frame_count` | 36 | 每轮迭代/每个子视频均匀采样的帧数 |
| `focus_windows` | `[3, 10, 30]` | 局部聚焦窗口大小列表（秒） |
| `focus_positions` | `[0.2, 0.35, 0.5, 0.65, 0.8]` | 断裂点在子视频中的位置比例 |
| `neg_before_duration` | 5 | 断裂前负样本片段长度（秒） |
| `neg_after_duration` | 5 | 断裂后负样本片段长度（秒） |
| `tolerance_seconds` | 1.0 | Agent 迭代停止的区间容忍误差（秒） |
| `max_rounds` | 10 | Agent 最大迭代轮数 |
| `confidence_threshold` | 0.5 | 低置信度判定阈值 |
| `max_low_conf_rounds` | 2 | 连续低置信度达到该轮数则停止 |
| `test_ratio` | 0.2 | 测试集占原始视频比例 |
| `n_folds` | 3 | 交叉验证折数 |
| `agent.backend` | "remote" | Agent LLM 后端：remote(百炼) / local(Ollama) |
| `agent.remote.provider` | "dashscope" | 远程提供商 |
| `agent.remote.model` | "qwen2.5-14b-instruct" | 百炼模型名，用户可自选 |
| `agent.remote.base_url` | "https://dashscope.aliyuncs.com/compatible-mode/v1" | 百炼 API 地址 |
| `agent.local.provider` | "ollama" | 本地提供商 |
| `agent.local.model` | "qwen2.5:7b" | Ollama 模型名，用户可自选 |
| `agent.local.base_url` | "http://localhost:11434/v1" | Ollama API 地址 |
| `agent.max_rounds` | 10 | 最大迭代轮数 |
| `agent.tolerance_seconds` | 1.0 | 区间收敛容忍误差 |
| `agent.temperature` | 0.7 | Agent LLM 采样温度 |

---

## 7. 实现顺序与里程碑

| 阶段 | 时间 | 负责模块 | 交付物 | 验收标准 |
|---|---|---|---|---|
| **Phase 1** | Week 1 | M1 + M2 | `video_meta.json`、子视频文件、训练/测试 JSON | 所有子视频生成完毕，JSON 格式通过 LLaMA-Factory 数据加载验证 |
| **Phase 2** | Week 2 | M3 + M4 | YAML 配置、dataset_info.json、3 个 fold 的 checkpoint | 每折训练 loss 收敛，验证集上 JSON 可解析率 > 95% |
| **Phase 3** | Week 3 | M5 | 迭代推理 Agent 代码、预测结果 JSON | 在测试集上单视频推理成功，输出符合最终 Schema |
| **Phase 4** | Week 4 | M6 | 评估报告（含旧方案对比） | 所有指标计算完毕，报告输出到 `docs/eval/` |

---

## 8. 风险与待办

| 风险项 | 影响 | 缓解措施 | 状态 |
|---|---|---|---|
| `location` 标注缺失 | location 准确率无法真实评估 | 先以占位值运行，人工补标后重新生成样本并复测 | 🔴 待人工补标 |
| `event_frame_original` 计算误差 | 训练标签存在系统性偏差 | 开发流程并行启动人工复核；复核后批量更新 `video_meta.json` | 🟡 待复核 |
| 子视频磁盘空间膨胀 | 110 个原视频 × 多窗口 × 多位置 × 负样本，存储可能达数十 GB | 监控 `data/02_subvideos/` 目录大小；必要时压缩或清理中间文件 | 🟡 需监控 |
| LLaMA-Factory 子视频读取性能 | 大量独立小文件可能导致 I/O 瓶颈 | Phase 1 后期做小批量训练测试，若性能不足则评估 ffmpy 内存加载方案 | 🟡 待验证 |
| 模型自报 confidence 偏置 | 模型可能产生 overconfidence（高 confidence 但实际错误），导致 Agent 综合判断失真 | 在 M6 评估阶段通过 reliability diagram 和校准曲线监控；若偏置严重，考虑让 Agent 在 system prompt 中调整判断策略 | 🟡 待评估 |
| 百炼 API function calling 稳定性 | 百炼 Qwen2.5 系列的 tool_calls 输出格式和稳定性需实测验证 | 开发阶段优先用百炼远程 API 测试；若不稳定，尝试不同模型规格或调整 tool schema | 🔴 待验证 |
| Ollama function calling 效果 | Ollama + Qwen2.5-7B 的 function calling 支持程度和输出质量不确定 | 本地先测试 Qwen2.5-7B；若效果不佳，尝试更大本地模型或切换到远程后端 | 🔴 待验证 |
| Agent 模型输出质量 | Qwen 通过 tool_calls 进行迭代决策的质量直接影响收敛性 | 在 Phase 3 前做稳定性测试；若质量不稳定，考虑提升模型规格或优化 system prompt | 🔴 待验证 |
| Agent 生成不合理参数 | Agent 可能输出越界采样区间或不符合预期的 prompt | 代码层做边界校验（如区间合法性、num_frames 范围），非法时回退或提示 Agent 修正 | 🟡 待实现 |
| 本地 7B 模型决策质量 | 本地 7B 模型的推理和决策质量可能不如 14B，影响迭代效率 | 在测试中对比 7B 和 14B 的 Agent 决策质量；根据结果选择默认模型 | 🟡 待评估 |
| 本地 Qwen 推理速度 | 上下文较长时（历史记录累积），本地模型推理可能成为瓶颈 | 监控每轮 Agent 推理耗时；若过长，评估切换到远程后端或上下文截断策略 | 🟡 待评估 |
| 局部聚焦窗口超参调优 | 窗口大小直接影响模型判断难度 | 先按默认值启动，Phase 4 通过消融实验确定最优配置 | 🟢 已知 |
| 3-fold 训练时间 | 每折需独立训练，总时间可能较长 | 评估单折训练耗时后决定是否并行化（多 GPU） | 🟡 待评估 |

### 待办清单

- [ ] 人工补标 `location` 字段
- [ ] 人工复核 `event_frame_original` 计算值
- [ ] 确认 MiniCPM-V 4.6 在 LLaMA-Factory 中的 template 名称（当前假设为 `minicpm_v`）
- [ ] Phase 1 结束后评估子视频总磁盘占用
- [ ] Phase 2 前确认 LLaMA-Factory 版本兼容性
- [ ] 申请百炼 API Key
- [ ] 在 MacBook Air M4 上安装 Ollama 并 pull qwen2.5:7b
- [ ] 测试百炼 Qwen2.5-14B 的 function calling 稳定性
- [ ] 测试 Ollama Qwen2.5-7B 的 function calling 稳定性
- [ ] 对比 7B 和 14B 的 Agent 决策质量
- [ ] 设计并实现 Agent 输出 JSON schema 的校验机制，非法时自动重试或降级
- [ ] Phase 4 中绘制 reliability diagram，评估模型 confidence 校准情况

---

## 附录：术语表

| 术语 | 说明 |
|---|---|
| **帧区间迭代定位** | 不直接预测断裂秒数，而是通过多轮"断裂在哪两帧之间"的问答逐步缩小时间范围 |
| **子视频** | 从原始视频中截取的片段，作为独立的训练/推理样本 |
| **局部聚焦** | 围绕断裂时刻裁剪的短片段，断裂点位于子视频内的特定位置 |
| **负样本** | 不包含断裂的视频片段，用于训练模型识别"无断裂"情况 |
| **event_frame_original** | 断裂帧在原始视频中的全局帧号 |
| **fracture_between** | 模型输出：断裂发生在第 i 帧和第 i+1 帧之间，格式为 `[i, i+1]` |
