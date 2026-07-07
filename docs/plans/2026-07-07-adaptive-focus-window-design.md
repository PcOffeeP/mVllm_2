# Adaptive Focus 子视频窗口自适应方案设计

> 版本：v1.1  
> 日期：2026-07-07  
> 状态：已按审查意见修订，待实现  

---

## Goal and scope

### 目标

解决当前 focus 子视频生成中，当检测事件靠近视频边界时固定窗口需要平移或无法完整容纳，导致事件实际位置偏离目标 ratio 的问题。在不破坏现有普通 focus 输出契约的前提下，为每个 ratio 额外生成一个尽可能大的 adaptive focus 窗口。

### 范围

- **覆盖阶段**：focus 子视频的窗口选择逻辑（当前为 `pipeline/scripts/subvideo_builder.py::build_focus_subvideos`）
- **覆盖的视频类型**：所有需要 focus 子视频生成的视频，包括短事件（靠近边界）和长事件（居中）
- **输出产物**：命名包含 `_adaptive` 后缀的新子视频，保留可追溯窗口长度和 adaptive 标记
- **不影响**：非 focus 类型的子视频生成、主视频剪辑逻辑、事件检测流水线

### 成功指标

| 指标 | 说明 |
|------|------|
| 覆盖提升 | 此前因边界问题无法获得 ratio-preserving 固定窗口的 ratio 中，至少 80% 能生成 adaptive focus |
| ratio 可控 | adaptive focus 的事件位置 ratio 在帧量化容差内接近目标 ratio |
| 命名可追溯 | 每个 adaptive focus 可通过文件名、crop_type 和元数据字段与普通 focus 区分 |

---

## Non-goals

- 不修改事件检测或定位逻辑（event_time / event_frame 仍是输入）
- 不引入新的固定窗口大小或新的 ratio 值
- 不改变普通 focus 子视频的生成逻辑、命名和 `crop_type` 契约
- 不解决视频内容质量问题（模糊、遮挡等属于下游检测环节）
- 不涉及多模态大模型或视频理解模型的训练/微调

---

## Constraints and assumptions

### 已知约束

| 约束 | 值 | 来源 |
|------|-----|------|
| 固定窗口集合 | [3, 5, 10, 20] 秒 | 现有系统 |
| 固定 ratio 集合 | [0.2, 0.35, 0.5, 0.65, 0.8] | 现有系统 |
| 最小 adaptive 窗口 | 默认 **1.5 秒**（3 个采样帧 / 2fps）；实现时应从采样帧率和最小采样帧数推导 | 视频采样约束 |
| 普通 focus crop_type | `focus_{window}s`，例如 `focus_3s` | 现有元数据契约 |
| adaptive focus crop_type | `focus_adaptive`，窗口长度写入 `actual_focus_window_seconds` | 新规范 |
| 文件命名模式 | 普通 focus 保持 `{video_id}_focus_{window}s_{ratio}pct`；adaptive 使用 `{video_id}_focus_{actual_window}s_{ratio}pct_adaptive` | 现有规范扩展 |

### 假设

1. `event_time` 是事件发生的绝对时间戳（秒），来自事件检测模块
2. `event_frame`、`fps`、`total_frames` 是当前实现中更可靠的窗口计算输入；实现时应优先按帧计算，再回写秒
3. 当前普通 focus 以 `(window, ratio)` 唯一决定一个子视频；adaptive focus 以 `(actual_window, ratio, adaptive)` 区分
4. 窗口选择逻辑是无状态的，每次输入 `(ratio, event_time/event_frame, video_duration/total_frames, fps)` 独立输出窗口参数
5. ratio 验收必须考虑帧量化，不能要求所有场景严格等于浮点目标值

---

## Recommended architecture

### 总体策略：保留普通 focus + 额外 adaptive 候选

普通 focus 生成保持现有行为不变。adaptive focus 作为新增候选，只在某个 ratio 没有任何固定窗口能在不平移的情况下满足目标 ratio 时生成。

```
Track A ──► 现有固定窗口逻辑 ──► 生成普通 focus（保持命名/crop_type 不变）
   │
   └──► 同步记录每个 ratio 是否存在 strict-fit 固定窗口

Track B ──► 若某 ratio 无 strict-fit 固定窗口 ──► 计算 max_window
                                               │
                                               ├── max_window 足够大 → 生成 adaptive focus
                                               └── max_window 过小 → 不生成 adaptive
```

### Track A：普通 focus 生成（保持不变）

普通 focus 继续使用当前 `build_focus_subvideos` 的固定窗口逻辑：

- 遍历 `[3, 5, 10, 20] × [0.2, 0.35, 0.5, 0.65, 0.8]`
- 当理论窗口越界但固定窗口长度仍能放入视频时，按现有对侧平移策略生成普通 focus
- 保持普通 focus 的文件名 `{video_id}_focus_{window}s_{ratio}pct`
- 保持普通 focus 的 `crop_type=f"focus_{window}s"`

实现 adaptive 时不得把普通 focus 的 `crop_type` 改成 `focus`，也不得删除现有固定窗口候选，除非另行明确批准破坏性数据契约变更。

### Strict-fit 判定（新增辅助状态）

为决定是否需要 adaptive，同步计算每个 ratio 是否存在至少一个不需要平移的固定窗口：

```
strict_fit = (window * ratio <= event_time + tolerance)
             AND (window * (1 - ratio) <= video_duration - event_time + tolerance)
```

如果同一 ratio 下任意固定窗口 `strict_fit = true`：

- 该 ratio 已有 ratio-preserving 的普通 focus
- 不生成 adaptive focus，避免重复候选

如果同一 ratio 下所有固定窗口都不是 strict-fit：

- 现有普通 focus 仍按 Track A 生成
- 进入 adaptive 计算，补充一个更短但更接近目标 ratio 的候选

### Track B：自适应窗口计算（新逻辑）

当某个 ratio 没有任何 strict-fit 固定窗口时进入 Track B。

**核心公式**：

```
max_window = min(event_time / ratio, (video_duration - event_time) / (1 - ratio))
```

**推导依据**：

- 事件左侧最大可用时长：`event_time / ratio`（因为 crop 窗口左侧占 `ratio * window`）
- 事件右侧最大可用时长：`(video_duration - event_time) / (1 - ratio)`（右侧占 `(1 - ratio) * window`）
- 取两者最小值确保窗口在两侧均不越界

**判定逻辑**：

```
if max_window >= min_adaptive_window:
    → 生成 adaptive focus，窗口时长 = max_window（量化到帧边界）
    → 命名：{video_id}_focus_{max_window}s_{ratio}pct_adaptive
    → crop_type：focus_adaptive
    → 元数据：is_adaptive_focus=true, actual_focus_window_seconds=max_window
else:
    → 不生成 adaptive focus（窗口过小，无法生成有意义的子视频）
```

**去重优化**：

同一个 ratio 下最多生成一个 adaptive focus。原因：

- Track B 的触发条件是该 ratio 下没有任何 strict-fit 固定窗口
- adaptive 的 `max_window` 只取决于 `event_time`、`video_duration` 和 `ratio`
- 对同一 ratio 重复生成 adaptive 只会产生重复内容

**伪代码**：

```
function process_video(event_time, video_duration, fps):
    strict_fit_by_ratio = {ratio: False for ratio in FOCUS_POSITIONS}

    # Track A：普通 focus 生成保持现有逻辑
    for window in [3, 5, 10, 20]:
        for ratio in [0.2, 0.35, 0.5, 0.65, 0.8]:
            if fixed_window_can_be_generated_by_current_logic(window, ratio):
                generate_focus(window, ratio, crop_type=f"focus_{window}s")

            if fixed_window_is_strict_fit(window, ratio, event_time, video_duration):
                strict_fit_by_ratio[ratio] = True

    # Track B：仅补充没有 strict-fit 固定窗口的 ratio
    for ratio in [0.2, 0.35, 0.5, 0.65, 0.8]:
        if strict_fit_by_ratio[ratio]:
            continue

        max_w = min(event_time / ratio,
                    (video_duration - event_time) / (1 - ratio))
        max_w = quantize_window_to_frame_boundary(max_w, fps)

        if max_w >= min_adaptive_window_seconds:
            generate_focus(
                max_w,
                ratio,
                crop_type="focus_adaptive",
                is_adaptive_focus=True,
                actual_focus_window_seconds=max_w,
            )
```

---

## Data flow and state changes

### 当前流程（不变部分）

```
Event Detection
    │
    ▼ event_time/event_frame, video_duration/total_frames
build_focus_subvideos
    │
    ├──► 遍历 windows [3, 5, 10, 20]
    │        │
    │        ▼
    │   遍历 ratios [0.2, 0.35, 0.5, 0.65, 0.8]
    │        │
    │        ▼
    │   使用现有固定窗口/对侧平移逻辑生成普通 focus
    │
    ▼
生成普通 focus 子视频文件 + 更新 crop_type=focus_{window}s
```

### 变更后的流程

```
Event Detection
    │
    ▼ event_time/event_frame, video_duration/total_frames
build_focus_subvideos
    │
    ├──► Track A: for each window × ratio:
    │        │
    │        ├── generate ordinary focus with current fixed-window logic
    │        └── record strict_fit_by_ratio[ratio]
    │
    ├──► Track B: for each ratio without strict_fit:
    │        │
    │        ├── compute max_window
    │        │     ├── max_window >= min_adaptive_window → generate adaptive focus
    │        │     └── max_window < min_adaptive_window → no adaptive output
    │        │
    │        ▼
    │   (下一个 ratio)
    │
    ▼
输出：focus 子视频列表（含普通 focus 和 adaptive focus）
```

### 状态变化

| 步骤 | 输入 | 输出 / 状态变化 |
|------|------|----------------|
| Track A | ratio, event_time, video_duration, window_size | 保持现有普通 focus 输出，crop_type=`focus_{window}s` |
| strict-fit 记录 | ratio, event_time, video_duration, window_size | 记录该 ratio 是否已有不需要平移的固定窗口 |
| Track B | ratio, event_time, video_duration | 若成功：新增 adaptive focus 记录；若失败：该 ratio 无 adaptive 输出 |
| 去重 | ratio, adaptive 已生成标志 | 同 ratio 下最多生成一个 adaptive focus |

---

## Failure handling and edge cases

### 边界情况矩阵

| 场景 | 条件 | 预期行为 |
|------|------|----------|
| 事件严格居中 | 所有窗口两侧都足够 | 普通 focus 生成；存在 strict-fit，不生成 adaptive |
| 事件靠近左边界 | `event_time` 很小，固定窗口需平移 | 普通 focus 保持现有输出；若无 strict-fit，生成 adaptive |
| 事件靠近右边界 | `video_duration - event_time` 很小，固定窗口需平移 | 普通 focus 保持现有输出；若无 strict-fit，生成 adaptive |
| 事件非常靠近边界 | `max_window < min_adaptive_window` | 普通 focus 保持现有输出；不生成 adaptive，记录日志 |
| 事件在正中间但窗口极大 | 20s 窗口超过视频长度 | 较小 strict-fit 窗口若存在则不生成 adaptive；若全部无 strict-fit 才生成 adaptive |
| ratio=0.5（居中对称） | 两边需求相等 | `max_window = 2 * min(event_time, duration - event_time)` |
| ratio=0.2（偏左） | 左侧需求小 | 左侧瓶颈时 `max_window = event_time / 0.2` |
| ratio=0.8（偏右） | 右侧需求小 | 右侧瓶颈时 `max_window = (duration - event_time) / 0.2` |

### 异常处理

| 异常 | 处理方式 |
|------|----------|
| `event_time` 为 0 或负值 | adaptive 视为无效输入，跳过所有 ratio，记录告警日志；普通 focus 按现有逻辑处理 |
| `video_duration <= min_adaptive_window` | 不生成 adaptive；普通 focus 按现有逻辑处理 |
| `event_time > video_duration` | 视为无效输入，跳过 adaptive，记录告警日志 |
| 浮点精度问题 | max_window 保留 3 位小数或量化到帧边界，比较时使用容差 `1e-6` |
| 并发处理多个视频 | 每个视频独立调用，无共享状态 |

### 日志要求

每条调用至少记录：

- 视频 ID、event_time、video_duration
- 每个 ratio 的处理结果（已有 strict-fit / 生成 adaptive / adaptive 过小跳过）
- Track B 被触发时记录计算的 max_window 值
- 不生成 adaptive 时记录原因（已有 strict-fit 或 max_window < min_adaptive_window）

---

## Testing strategy

### 单元测试

**测试目标**：`build_focus_subvideos` 中普通 focus 兼容性、strict-fit 判定和 adaptive 生成逻辑

| 测试用例 | 输入 | 预期输出 |
|----------|------|----------|
| 正常居中事件 | ratio=0.5, event_time=15, duration=60, window=10 | 普通 focus 保持现有输出；该 ratio 有 strict-fit，不生成 adaptive |
| 左边界事件 | ratio=0.5, event_time=1, duration=60 | 普通 focus 保持现有输出；若无 strict-fit，max_window=2.0，额外生成 adaptive focus |
| 极左边界事件 | ratio=0.5, event_time=0.2, duration=60 | 普通 focus 保持现有输出；max_window=0.4 < min_adaptive_window，不生成 adaptive |
| 右边界事件 | ratio=0.5, event_time=59, duration=60 | 普通 focus 保持现有输出；若无 strict-fit，max_window=2.0，额外生成 adaptive focus |
| 极右边界事件 | ratio=0.5, event_time=59.9, duration=60 | 普通 focus 保持现有输出；max_window=0.2 < min_adaptive_window，不生成 adaptive |
| ratio=0.2 左边界 | ratio=0.2, event_time=0.5, duration=60 | 若无 strict-fit，max_window=2.5 >= min_adaptive_window，生成 adaptive focus |
| ratio=0.8 右边界 | ratio=0.8, event_time=59.5, duration=60 | 若无 strict-fit，max_window=2.5 >= min_adaptive_window，生成 adaptive focus |
| 去重验证 | 同一 ratio 触发 Track B | 同一 ratio 最多一个 adaptive focus |
| 普通 focus 契约 | 任意已有普通 focus 场景 | `subvideo_id` 不变，`crop_type` 保持 `focus_{window}s` |
| ratio 量化误差 | 3s@2fps, ratio=0.35 | 验收使用帧量化容差，不要求严格等于 0.35 |

### 集成测试

| 场景 | 方法 |
|------|------|
| 完整视频管道 | 输入一个已知边界事件的视频，验证普通 focus 和 adaptive focus 子视频均正确生成 |
| 命名验证 | 检查普通 focus 命名/crop_type 不变，adaptive 子视频文件名包含 `_adaptive` 后缀 |
| 多 ratio 覆盖 | 验证同一视频下 5 个 ratio 各自独立处理，互不影响 |
| 元数据兼容 | 验证 adaptive 元数据包含 `is_adaptive_focus` 和 `actual_focus_window_seconds`，下游 review/training 流程可识别 |

### 回归测试

| 检查项 | 说明 |
|--------|------|
| 普通 focus 输出不变 | 普通 focus 的 `subvideo_id`、`crop_type`、窗口平移行为与旧版一致 |
| 居中事件输出不变 | 对于居中的事件，普通 focus 的输出和旧版一致，不额外生成 adaptive |
| 边界事件不崩溃 | 旧版可能报错的边界输入，新版至少不会崩溃 |
| 无重复 adaptive | 去重逻辑确保同一 ratio 下不会生成多个 adaptive focus |
| ratio 容差 | adaptive focus 的事件位置 ratio 在帧量化容差内 |

### 验收标准清单

- [ ] 所有 unit test 通过
- [ ] 边界 case 覆盖左/右/极左/极右四种场景
- [ ] 去重逻辑验证通过（同一 ratio 下仅生成一个 adaptive focus）
- [ ] 普通 focus 的 `subvideo_id` 和 `crop_type=focus_{window}s` 回归不变
- [ ] adaptive focus 的命名、crop_type 和新增元数据字段检查通过
- [ ] 回归测试确认居中事件输出与旧版一致，且不会多生成 adaptive
- [ ] ratio 验收使用帧量化容差，避免不可实现的严格浮点相等
- [ ] 日志输出完整、可读（至少包含每个 ratio 的处理结果）

---

## Open questions

| 问题 | 是否阻塞 |
|------|----------|
| 日志输出级别和格式是否需要与现有 pipeline 的监控告警系统对齐？ | 否 |
| 是否需要对 adaptive focus 的子视频添加原始 max_window 计算参数，方便日后调试？ | 否 |
| video_duration/event_time 与帧索引之间的精度和单位是否需要统一校验？ | 否 |
