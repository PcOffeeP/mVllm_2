# mVllm_2：`tensile-vlm/v2` 契约与服务端同步实施计划

> 适用仓库：`mVllm_2`，以及作为前置依赖的相邻 `TensileAgent`
>
> 当前阶段：可替换视觉模型 MVP
>
> 本计划只迁移生产推理契约、服务预检和部署身份；不训练、不调参、不重建数据。

## 一、结论与实施顺序

当前实施将生产服务迁移到 `tensile-vlm/v2`，并保留当前模型
已经训练和使用的“视频异常”语义：

```json
{
  "has_fracture": null,
  "fracture_between": null,
  "type": "视频异常",
  "location": null
}
```

旧 TensileAgent hash `141887...9002` 的 v2 artifact 要求
`has_fracture=null` 时其余字段全部为 `null`，与本项目现状冲突。

按以下顺序施工：

1. 先在 TensileAgent 更新 v2 artifact、四字段解析规则和 HTTP 客户端重试行为。
2. 两仓共同确认新 artifact 的 canonical hash。
3. 再在 mVllm_2 实施生产契约、服务端点和部署身份迁移。
4. 最后执行跨仓一致性测试和训练机传输 smoke。

前一步未完成时不得开始下一步，也不得让两个仓库使用同名但内容不同的 v2 契约。

## 二、固定设计决策

### 2.1 四字段输出语义

模型输出始终且只能包含以下四个字段，顺序固定：

```text
has_fracture
fracture_between
type
location
```

字段联动规则：

- `has_fracture=true`
  - `fracture_between`、`type`、`location` 可以分别为 `null`；
  - 非空区间必须是相邻帧 `[i, i+1]`；
  - 非空 `type` 必须是 8 种断裂类型；
  - 非空 `location` 必须是 `inside_gauge` 或 `outside_gauge`。
- `has_fracture=false`
  - `fracture_between` 和 `location` 必须为 `null`；
  - `type` 必须为 `未断裂` 或 `未夹紧`。
- `has_fracture=null`
  - `fracture_between` 和 `location` 必须为 `null`；
  - `type` 必须为 `视频异常`。

不再接受 `has_fracture=null, type=null`。

### 2.2 Prompt 来源

- `pipeline/prompt_library.yaml` 保持不变，继续作为当前训练和核心评测的 Prompt 来源。
- v2 artifact 的 `analysis.system_prompt` 和 `analysis.user_prompt` 必须逐字保存该 YAML
  当前加载后的 Prompt，以保持 merged 模型训练分布不变。
- 生产服务只读取 v2 artifact，不在运行时读取或合并 YAML。
- `evidence` Prompt 只存在于 v2 artifact，不进入训练样本。

这是一份“训练 Prompt 的版本化生产快照”，不是让训练流程反向依赖生产 artifact。
本任务不得修改 YAML、训练样本或历史数据。

### 2.3 重试归属

客户端不得向视觉 Prompt 注入动态文本。模型输出格式纠错统一由 mVllm_2 服务端负责：

1. 客户端只发送 artifact 中固定的 analysis 或 evidence Prompt。
2. 服务端校验请求中的固定 Prompt，随后用 artifact 内容重新构造实际模型输入。
3. analysis 首次输出不符合四字段契约时，服务端最多内部重试 2 次。
4. 重试只使用 artifact 中固定的 `analysis.retry_prompt`，并引用服务端自己刚生成的上一轮
   assistant 输出。
5. TensileAgent 收到最终响应后只解析一次，不再追加动态 correction user message。
6. evidence 只要求非空文本，不执行四字段 JSON 重试。

这样既保留格式恢复能力，也保证客户端文本不能改变视觉任务。

### 2.4 部署配置与公共身份分离

启动配置文件必须恰好包含 10 个字段：

```text
max_frames
model_version
adapter_version
base_model_version
processor_version
llamafactory_version
transformers_version
config_fingerprint
runtime_device
runtime_dtype
```

其中 `max_frames` 必须是整数 `8`，其余 9 项必须是非空字符串，且不能是 `unknown` 或
`REPLACE_*`。

启动配置不得提供 `contract_version` 或 `contract_hash`。服务从已校验 artifact 注入这
两个字段，构造恰好 11 个字段的公共 `deployment_manifest`：

```text
model_version
adapter_version
base_model_version
processor_version
llamafactory_version
transformers_version
config_fingerprint
runtime_device
runtime_dtype
contract_version
contract_hash
```

服务启动时冻结该对象。GET 和每轮 POST 返回其副本，请求处理中不得重新读取配置、
环境变量或 artifact。

## 三、权威 v2 artifact

两仓最终的 `tensile_vlm_v2.json` 必须逐字段一致。按本计划附录内容计算出的 canonical
hash 固定为：

```text
d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102
```

hash 计算规则：

```python
def canonical_contract_bytes(contract: dict[str, Any]) -> bytes:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
```

必须同时满足：

1. artifact 自带 hash 等于 canonical SHA256；
2. 代码或测试中独立固定的预期 hash 等于上述值；
3. 本地交付时两仓 artifact 规范化内容完全一致。

不能只依赖 artifact 自签名，也不能因 CI 缺少相邻仓库而放弃固定 hash 校验。

## 四、TensileAgent 前置修改

这一阶段需要在相邻 TensileAgent 仓库单独实施和验收：

1. 更新 `agent/contracts/tensile_vlm_v2.json` 为附录内容。
2. 更新 `agent/contract.py`：
   - 必需字段加入 `anomaly_types`；
   - 校验固定版本、固定 hash、字段顺序和 canonical hash。
3. 更新 `agent/schema.py` 和 parser 相关测试：
   - 允许且要求 `has_fracture=null, type=视频异常`；
   - 继续拒绝 null 状态下的区间和位置；
   - 拒绝 `has_fracture=null, type=null`；
   - 拒绝其他 null 状态类型。
4. 更新 `agent/inference.py`：
   - analysis/evidence 仍发送 artifact 中的固定 Prompt；
   - 移除客户端动态 correction 消息重试；
   - 对服务最终响应只做一次严格解析；
   - 继续 fail closed，不在客户端修补非法组合。
5. 更新 stub、contract、parser、inference 和 v2 MVP 测试。

不得借此修改 TensileAgent 的规划、证据汇总或终止决策逻辑。

## 五、mVllm_2 修改范围

### 允许修改

- `pipeline/contracts/tensile_vlm_v2.json`
- `pipeline/production_contract.py`
- `pipeline/output_normalizer.py`
- `pipeline/server_adapter.py`
- `pipeline/server_proxy.py`
- `pipeline/server_deployment_manifest.example.json`
- `tests/test_production_contract.py`
- 与生产服务直接相关的少量测试
- `README.md`
- `docs/FINAL_PROMPT_POLICY.md`
- `finetune/README.md`

`pipeline/prompt_library.yaml` 只读取和比对，不修改。

### 禁止修改

- `data/` 中的训练、标注和划分内容
- checkpoint、adapter、merged model 或 base model
- 训练 YAML、超参数和视觉算法
- 训练样本构造器及其“视频异常”标签规则
- 为通过测试而放宽契约、帧表、鉴权或部署身份校验
- v1 运行时 fallback

若实现需要超出以上范围，记录证据并停止，不自行扩大施工。

## 六、`production_contract.py`

改为只加载：

```python
CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v2.json"
CONTRACT_VERSION = "tensile-vlm/v2"
EXPECTED_CONTRACT_HASH = "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102"
```

`load_production_contract()` 必须：

1. 要求附录中的所有顶层字段存在；
2. 校验四字段顺序；
3. 校验 8 种断裂类型、2 种非断裂类型和唯一异常类型 `视频异常`；
4. 拒绝非 v2；
5. 校验 canonical SHA256；
6. 校验固定 `EXPECTED_CONTRACT_HASH`；
7. 校验 analysis、retry、evidence Prompt 及 generation 字段非空且结构正确；
8. 返回 artifact 自身，不读取 YAML。

`production_contract_hash()` 直接返回已校验 artifact 的 `contract_hash`。

命令行输出：

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102"
}
```

`pipeline/contracts/tensile_vlm_v1.json` 可以保留为历史文件，但生产代码、测试和部署说明
不得继续加载或推荐它。

## 七、`output_normalizer.py`

同步当前项目已有的“视频异常”标签规则：

- `has_fracture=null` 时，输出固定为
  `fracture_between=null, type=视频异常, location=null`；
- 原始 `type=视频异常` 保持不变；
- 原始 `type` 为其他值或 `null` 时，归一化为 `视频异常` 并记录 repair flag；
- `validate_structured_output()` 只接受 null 状态下的 `type=视频异常`；
- `has_fracture=true` 时仍不得把 `视频异常` 当作断裂类型；
- `has_fracture=false` 时仍只接受 `未断裂` 或 `未夹紧`。

同步更新 `tests/test_output_normalizer.py`。这只统一既有标签语义，不修改训练数据。

## 八、`server_adapter.py`

将 `wrap_response()` 的输入明确为：

```python
wrap_response(raw_response, video_frames, deployment_snapshot)
```

其中 `deployment_snapshot` 已由服务启动阶段构造，必须恰好包含公共 11 字段。

函数必须：

- 校验 11 字段集合恰好相等，缺失或新增字段都拒绝；
- 校验每项为允许的非空字符串；
- 校验 v2 version/hash；
- 校验 1 至 8 帧；
- 校验 index 从 0 连续递增；
- 校验 timestamp 是有限数且严格递增；
- 每轮生成非空 request ID；
- 返回 `processor_version`、`max_frames=8`、真实帧表和冻结 manifest 副本。

保留现有 `tensor_digest` 和 `tensor_shape` 诊断，但它们不属于公共 deployment identity。

## 九、`server_proxy.py`

### 9.1 启动阶段

`create_integrated_app(chat_model, startup_config)` 必须：

1. 严格校验启动配置的 10 字段 schema；
2. 校验实际 processor 类名等于 `processor_version`；
3. 校验实际 processor 使用 `max_frames=8`；
4. 加载并验证 v2 artifact；
5. 注入 contract version/hash；
6. 构造一次内部只读的 11 字段 deployment snapshot；
7. GET 和 POST 只返回 snapshot 的普通 dict 副本。

### 9.2 鉴权

提取一个 GET/POST 共用的鉴权函数。`API_KEY` 启用时，两端都要求完全相同的 Bearer
语义；未启用时两端都允许访问。

鉴权错误、请求错误和日志不得包含 API Key、Base64 内容、本地模型绝对路径或用户视频。

### 9.3 预检端点

新增：

```text
GET /v1/tensile/contract
```

返回：

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102",
  "deployment_manifest": {
    "model_version": "...",
    "adapter_version": "...",
    "base_model_version": "...",
    "processor_version": "...",
    "llamafactory_version": "...",
    "transformers_version": "...",
    "config_fingerprint": "...",
    "runtime_device": "...",
    "runtime_dtype": "...",
    "contract_version": "tensile-vlm/v2",
    "contract_hash": "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102"
  },
  "capabilities": {
    "analysis": true,
    "evidence": true
  }
}
```

### 9.4 POST 请求语法

继续使用：

```text
POST /v1/chat/completions
```

只接受一组 system message 和一组包含一个 Base64 MP4、一个固定文本 Prompt 的 user
message。按 system/user Prompt 的精确组合识别 analysis 或 evidence；其他文本、额外
assistant/user message、多个视频、错误媒体类型和 streaming 请求全部拒绝。

校验通过后，服务必须从 artifact 重新构造模型消息和 generation 参数，不能直接把客户端
文本传入模型。

### 9.5 analysis 内部重试

analysis 每次生成后执行严格四字段验证：

- 合法输出立即返回；
- 非法输出使用 artifact 的固定 `retry_prompt` 内部重试；
- 最多重试 2 次；
- 不因次要字段为 `null` 而重试，只对非法 JSON、字段集合、字段类型、枚举或联动组合重试；
- 全部失败时返回最后一次模型响应，由 TensileAgent 严格解析并 fail closed；
- 每次 HTTP 请求只返回一份 request ID、帧表和 deployment manifest。

内部重试必须复用同一临时视频、同一 processor capture 上下文和同一 inference lock，不得
重新读取部署身份。

### 9.6 evidence

evidence：

- 使用 artifact 中独立的 system/user Prompt 和 generation；
- 使用同一视频处理器和相同 preprocessing 结构；
- 不接收 analysis 四字段结果；
- 只要求最终文本非空；
- 能真实完成上述流程时才声明 `capabilities.evidence=true`。

## 十、部署示例和文档

更新 `pipeline/server_deployment_manifest.example.json`：

- 使用 `adapter_version`，删除 `artifact_version`；
- 删除 `prompt_contract_hash`；
- 不包含 `contract_version` 或 `contract_hash`；
- 保留 `max_frames=8`；
- 示例占位值可以保留，但服务启动必须拒绝未替换值。

同步更新：

- `README.md`：生产服务、v2 hash、GET 预检和启动配置；
- `docs/FINAL_PROMPT_POLICY.md`：说明 YAML 是训练/评测来源，v2 artifact 是生产快照，
  evidence Prompt 只属于生产契约；
- `finetune/README.md`：删除 v1 和 `prompt_contract_hash` 部署说明，明确本任务未改变训练
  Prompt 或训练数据。

完成后，生产部署说明中不得再出现：

```text
tensile-vlm/v1
prompt_contract_hash
artifact_version
生产运行时读取 pipeline/prompt_library.yaml
```

## 十一、测试要求

重点更新 `tests/test_production_contract.py`，至少覆盖：

1. artifact 必需字段、四字段顺序、8 种断裂类型和 `视频异常`；
2. canonical hash、自带 hash、固定预期 hash 三者一致；
3. 修改 Prompt、retry Prompt、schema、generation、video、enum 或规则后启动失败；
4. v1 直接拒绝；
5. artifact analysis Prompt 与当前 YAML 加载值逐字一致，但生产 loader 不读取 YAML；
6. null 状态只接受 `type=视频异常`；
7. output normalizer 保留或补齐 `has_fracture=null, type=视频异常`，并拒绝其他 null 组合；
8. 启动配置恰好 10 字段，伪造 contract 字段或任意额外字段均拒绝；
9. 公共 manifest 恰好 11 字段；
10. GET 与所有 POST 返回的 manifest 完全相等；
11. 帧表为空、超过 8、索引不连续、timestamp 非有限或不递增均拒绝；
12. analysis 和 evidence 模式识别；
13. 任意客户端 Prompt 覆盖、额外消息和 streaming 请求均拒绝；
14. analysis 合法首轮不重试，非法首轮使用固定 retry Prompt，最多重试 2 次；
15. evidence 不执行 JSON 重试；
16. GET/POST 鉴权完全一致；
17. Base64、API Key 和本地绝对路径不进入日志或错误输出；
18. tensor digest/shape 诊断仍存在；
19. 相邻 TensileAgent 存在时，两仓 artifact 规范化内容完全一致。

跨仓测试在不包含相邻仓库的 CI 中可以 skip，但固定 hash 测试不得 skip；本地交付验收时
跨仓测试必须实际通过。

验证命令：

```bash
python3 -m pytest tests/test_production_contract.py -q
python3 -m pytest tests/test_output_normalizer.py -q
python3 -m pytest tests/test_frame_contract.py -q
python3 -m pipeline.production_contract
git diff --check
```

还应执行受 Prompt 政策文档和训练样本规则影响的现有轻量测试。不得在当前电脑启动 GPU
推理、完整评测或重训练。

## 十二、训练机 smoke

真实服务 smoke 只能在训练电脑执行。先记录模型路径、输入视频、输出日志位置和预计资源
占用，再启动服务。

先预检：

```bash
curl -s http://127.0.0.1:8000/v1/tensile/contract | python3 -m json.tool
```

再分别调用 analysis 和 evidence，只验收：

- Base64 MP4 可传输；
- 固定 Prompt 请求成功，任意 Prompt 被拒绝；
- analysis 四字段可解析或明确 fail closed；
- `has_fracture=null, type=视频异常` 可被两端接受；
- request ID 非空；
- 帧表来自实际 processor capture；
- GET、analysis POST、evidence POST 的 manifest 完全一致；
- version/hash 正确；
- generation 参数确实映射到当前 LLaMA-Factory 接口；
- v1、错误媒体、鉴权错误和 deployment drift 均 fail closed。

不评价视觉分类准确率，不把视觉效果作为本任务阻塞条件。

## 十三、交付清单

完成后必须报告：

- TensileAgent 前置修改及其测试结果；
- mVllm_2 修改文件列表；
- 最终 contract hash；
- GET 预检脱敏示例；
- 相关测试和全量轻量测试结果；
- 跨仓一致性测试是否实际执行；
- 训练机 analysis/evidence smoke 是否执行；
- LLaMA-Factory generation 参数映射是否实测；
- 明确声明未修改训练 Prompt、训练数据、权重、checkpoint 和调参配置。

## 附录：权威 `tensile_vlm_v2.json`

```json
{
  "contract_version": "tensile-vlm/v2",
  "contract_hash": "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102",
  "model_output_fields": ["has_fracture", "fracture_between", "type", "location"],
  "model_output_schema": {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": false,
    "required": ["has_fracture", "fracture_between", "type", "location"],
    "properties": {
      "has_fracture": {"type": ["boolean", "null"]},
      "fracture_between": {
        "oneOf": [
          {
            "type": "array",
            "prefixItems": [
              {"type": "integer", "minimum": 0},
              {"type": "integer", "minimum": 1}
            ],
            "items": false,
            "minItems": 2,
            "maxItems": 2
          },
          {"type": "null"}
        ]
      },
      "type": {"type": ["string", "null"]},
      "location": {"type": ["string", "null"]}
    }
  },
  "fracture_types": [
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "齐根断裂",
    "爆炸性断裂",
    "半脆半韧断裂",
    "界面脱粘、齐根断裂",
    "脆性断裂、齐根断裂"
  ],
  "other_types": ["未断裂", "未夹紧"],
  "anomaly_types": ["视频异常"],
  "locations": ["inside_gauge", "outside_gauge"],
  "analysis": {
    "system_prompt": "你是一位材料力学视频分析助手。请根据提供的拉伸试验视频，基于画面中的试样变化，判断试样的断裂信息。最后请输出JSON格式的回答。",
    "user_prompt": "请判断试样是否断裂（has_fracture），并给出断裂帧区间（fracture_between）、断裂类型（type）和断裂位置（location）。",
    "retry_prompt": "上一轮输出不符合生产契约。请重新输出一个合法 JSON 对象，且只包含 has_fracture、fracture_between、type、location 四个字段，不要添加 Markdown 代码块或额外解释。",
    "generation": {"do_sample": false, "num_beams": 1, "temperature": 0.0, "max_new_tokens": 256}
  },
  "evidence": {
    "system_prompt": "你是一位材料力学视频观察助手。请只依据当前输入的采样帧，按时间顺序描述试样的可见变化，包括伸长、变细、颈缩、连续性中断、分离、打滑、遮挡或画面异常。不要引用其他分析结果，不要输出分类标签或 JSON，只输出一段简洁的视觉观察。",
    "user_prompt": "请描述这段拉伸试验视频采样帧中实际可见的变化过程。",
    "generation": {"do_sample": false, "num_beams": 1, "temperature": 0.0, "max_new_tokens": 256},
    "reliability": "experimental"
  },
  "video": {
    "max_frames": 8,
    "allowed_media_types": ["video/mp4"],
    "timestamp_semantics": "frames[*].timestamp is a finite, strictly increasing offset in seconds relative to the submitted clip; temp_video_manifest maps each sampled clip timestamp to the original video timeline"
  },
  "validation_rules": {
    "true": "fracture_between, type and location may independently be null; non-null fracture_between must be strictly adjacent [i,i+1]; non-null type must be one of fracture_types; non-null location must be one of locations",
    "false": "fracture_between and location must be null; type must be 未断裂 or 未夹紧",
    "null": "fracture_between and location must be null; type must be 视频异常"
  }
}
```
