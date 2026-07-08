# Adaptive Focus 子视频窗口自适应方案设计

> 版本：v1.4  
> 日期：2026-07-08  
> 状态：新增 sample/smoke 生成入口设计  

---

## Goal and scope

### 目标

解决当前 focus 子视频生成中，当检测事件靠近视频边界时固定窗口需要平移才能放入视频，导致事件实际位置偏离目标 ratio 的问题。核心方案：

- 对能 strict-fit（不平移即满足目标 ratio）的固定窗口，**保留**普通 focus 输出（同一 ratio 下可存在多个不同时长的 strict-fit 普通 focus）
- 对 **所有** 无法 strict-fit 的固定窗口（3/5/10/20 秒中任一失败规格），**不原封不动保存**（平移输出丢弃），而是由同一 ratio 下 **唯一** 的 adaptive focus 窗口替代，避免重复生成
- 同一 ratio 下可能 **同时存在** strict-fit 普通 focus 与 adaptive 替代输出——前者保留可实现的固定规格，后者覆盖无法 strict-fit 的失败规格

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
- 不改变 strict-fit 普通 focus 子视频的生成逻辑、命名和 `crop_type` 契约（非 strict-fit 固定窗口不再保留，改为 adaptive 替代）
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

### 总体策略：strict-fit 普通 focus 保留 + 失败固定规格由 unique adaptive 替代

核心变化：

1. 对能 strict-fit 的 `(window, ratio)` 保留普通 focus（同一 ratio 可输出多个不同时长的普通 focus）
2. 对无法 strict-fit 的 `(window, ratio)` **丢弃**平移输出（不原封不动保存）
3. 每个 ratio 最多生成 **一个** adaptive focus，集中替代该 ratio 下 **所有** 失败的固定规格
4. 同一 ratio 下 strict-fit 普通 focus 与 adaptive 替代输出 **可以同时存在**——前者代表可实现的固定规格，后者覆盖无法 strict-fit 的失败规格

```
Track A ──► 遍历 [3, 5, 10, 20] × [0.2, 0.35, 0.5, 0.65, 0.8]
   │
   ├── strict-fit → 生成普通 focus（保留命名/crop_type）
   │
   └── 非 strict-fit → 不生成普通 focus（丢弃平移后的失败规格）
                        记录该 ratio 有失败规格，需要 adaptive

Track B ──► 对存在至少一个失败固定规格的 ratio ──► 计算 max_window
                                               │
                                               ├── max_window ≥ min_adaptive_window
                                               │   → 生成唯一 adaptive focus 替代
                                               │     该 ratio 下所有失败固定规格
                                               │
                                               └── max_window < min_adaptive_window
                                                   → 该 ratio 的失败规格无替代输出
                                                      （strict-fit 普通 focus 仍保留）
```

### Track A：strict-fit 保留普通 focus，非 strict-fit 丢弃

Track A 不再无条件为所有 `(window, ratio)` 生成普通 focus（含平移输出）。改为：

- 遍历 `[3, 5, 10, 20] × [0.2, 0.35, 0.5, 0.65, 0.8]`
- **只对 strict-fit 的固定窗口**生成普通 focus（无需平移，事件位置精确满足目标 ratio）
- 保持普通 focus 的文件名 `{video_id}_focus_{window}s_{ratio}pct`
- 保持普通 focus 的 `crop_type=f"focus_{window}s"`
- 非 strict-fit 的固定窗口不再输出普通 focus——它们将被 Track B 的 adaptive 替代
- 同步记录 `has_failed_by_ratio[ratio]`：若该 `(window, ratio)` 非 strict-fit，标记该 ratio 需要 adaptive

实现 adaptive 时不得把普通 focus 的 `crop_type` 改成 `focus`，也不得删除 strict-fit 的普通 focus 候选。

### Strict-fit 判定（Track A 筛选条件）

为决定一个 `(window, ratio)` 是否生成普通 focus，计算是否需要平移：

```
strict_fit = (window * ratio <= event_time + tolerance)
             AND (window * (1 - ratio) <= video_duration - event_time + tolerance)
```

如果 `strict_fit = true`：

- 该 `(window, ratio)` 生成普通 focus（帧内 ratio 精确）

如果 `strict_fit = false`：

- 该 `(window, ratio)` **不**生成普通 focus（平移输出会被丢弃，不作为最终产物）
- 标记 `has_failed_by_ratio[ratio] = True`，表示该 ratio 有至少一个失败固定规格需要 adaptive 替代

注意：某个 ratio 下可能有部分窗口 strict-fit（如 3s）、部分非 strict-fit（如 10s/20s）。strict-fit 的窗口正常输出普通 focus；非 strict-fit 的窗口被丢弃，由 Track B 为该 ratio 统一生成一个 adaptive 替代。两者互不排斥。

### Track B：对存在失败规格的 ratio 生成唯一 adaptive 替代

当某个 ratio 存在 **至少一个** 失败固定窗口（即 `has_failed_by_ratio[ratio] = True`）时进入 Track B。自适应窗口 **替代**（而非补充）所有失败固定规格。

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
    → 此 adaptive 替代该 ratio 下所有失败的 3/5/10/20 秒固定规格
else:
    → 该 ratio 的失败规格无替代输出
    → 若该 ratio 尚有 strict-fit 普通 focus，它们仍正常保留
```

**唯一性保证（去重 + 退化）**：

同一个 ratio 下最多生成一个 adaptive focus，原因：

- `max_window` 只取决于 `event_time`、`video_duration` 和 `ratio`，与原始请求的固定时长（3/5/10/20 秒）无关
- 同一 ratio 下，5 秒、10 秒、20 秒失败窗口计算出的 `max_window` 完全一致
- 较长窗口（10/20 秒）如果因为边界不足，也自然退化到与 5 秒等同 ratio 的同一个 `max_window` adaptive 输出
- 因此不会为每个失败窗口重复生成 adaptive

**伪代码**：

```
function process_video(event_time, video_duration, fps):
    has_failed_by_ratio = {ratio: False for ratio in FOCUS_POSITIONS}

    # Track A：strict-fit 保留普通 focus；非 strict-fit 丢弃并标记需 adaptive
    for window in [3, 5, 10, 20]:
        for ratio in [0.2, 0.35, 0.5, 0.65, 0.8]:
            if fixed_window_is_strict_fit(window, ratio, event_time, video_duration):
                generate_focus(window, ratio, crop_type=f"focus_{window}s")
            else:
                # 不生成普通 focus（丢弃平移输出）
                has_failed_by_ratio[ratio] = True

    # Track B：对存在至少一个失败规格的 ratio，生成唯一 adaptive 替代
    for ratio in [0.2, 0.35, 0.5, 0.65, 0.8]:
        if not has_failed_by_ratio[ratio]:
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
            # 一个 ratio 只有一个 adaptive，替代该 ratio 下所有失败固定规格
            # strict-fit 普通 focus（如有）仍正常保留，互不排斥
        # else: 失败规格无替代输出，但 strict-fit 普通 focus 仍保留
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
    │        ├── strict-fit? → generate ordinary focus (preserved)
    │        └── not strict-fit? → skip ordinary focus (discard shifted output)
    │                              + mark has_failed_by_ratio[ratio] = True
    │
    ├──► Track B: for each ratio where has_failed_by_ratio is True:
    │        │
    │        ├── compute max_window
    │        │     ├── max_window >= min_adaptive_window
    │        │     │   → generate ONE adaptive focus (replaces all failed
    │        │     │     fixed durations at this ratio)
    │        │     └── max_window < min_adaptive_window
    │        │       → failed specs at this ratio have no replacement;
    │        │         strict-fit ordinary focus (if any) still preserved
    │        │
    │        ▼
    │   (下一个 ratio)
    │
    ▼
输出：focus 子视频列表
  - 每个 strict-fit (window, ratio) → 一条普通 focus（同一 ratio 可有多条）
  - 每个有失败规格的 ratio 至多一条 adaptive focus（替代所有失败规格）
  - 同一 ratio 下 strict-fit 普通 focus 与 adaptive 可同时存在
```

### 状态变化

| 步骤 | 输入 | 输出 / 状态变化 |
|------|------|----------------|
| Track A | `(window, ratio)`, event_time, video_duration | strict-fit → 生成普通 focus，crop_type=`focus_{window}s`；非 strict-fit → 不生成普通 focus，标记 `has_failed_by_ratio[ratio]=True` |
| failure 记录 | ratio | 记录该 ratio 是否存在至少一个失败的固定规格；一个 ratio 被标记一次即可（不计具体失败窗口数） |
| Track B | ratio, event_time, video_duration | 若 `has_failed_by_ratio[ratio]==True` → 计算 max_window；成功则生成唯一 adaptive focus 替代该 ratio 下所有失败规格 |
| 去重/退化 | ratio | 同一 ratio 下所有失败窗口（3/5/10/20 秒中任意失败者）退化到同一个 max_window adaptive，不重复生成 |

---

## Failure handling and edge cases

### 边界情况矩阵

| 场景 | 条件 | 预期行为 |
|------|------|----------|
| 事件严格居中 | 所有窗口两侧都足够 | 所有窗口 strict-fit → 各生成普通 focus；`has_failed_by_ratio` 均为 False → 不生成 adaptive |
| 事件靠近左边界（混合） | `event_time=1.6, ratio=0.5`，3s strict-fit，5/10/20s 需平移 | 3s 保留普通 focus；5/10/20s 丢弃平移输出；该 ratio 存在失败规格 → 唯一 adaptive 替代 5/10/20s 的失败规格（与 3s 普通 focus 并存） |
| 事件靠近右边界（混合） | `event_time=58.4, ratio=0.5, duration=60`，3s strict-fit，5/10/20s 需平移 | 同上：3s 普通 focus 保留 + adaptive 替代 5/10/20s 失败规格 |
| 事件非常靠近边界（全失败） | `event_time=0.2, ratio=0.5`，所有窗口非 strict-fit | 无普通 focus；max_window=0.4 < min_adaptive_window → 失败规格无替代输出；该 ratio 无任何输出 |
| 事件在正中间但窗口极大 | 20s 窗口超过视频长度 | 较小 strict-fit 窗口正常保留；其余非 strict-fit 的较大窗口由唯一 adaptive 替代；若全部越界（连 3s 也无法 strict-fit）→ 无普通 focus，唯一 adaptive 替代 |
| 较长窗口退化 | 10/20s 非 strict-fit，5s 也非 strict-fit | 10/20/5s 全部由同一个 max_window adaptive 替代，不重复生成；较长窗口的 max_window 与 5s 相同（仅取决于 ratio 和边界距离） |
| ratio=0.5（居中对称） | 两边需求相等 | `max_window = 2 * min(event_time, duration - event_time)` |
| ratio=0.2（偏左） | 左侧需求小 | 左侧瓶颈时 `max_window = event_time / 0.2` |
| ratio=0.8（偏右） | 右侧需求小 | 右侧瓶颈时 `max_window = (duration - event_time) / 0.2` |
| adaptive 过小但仍有 strict-fit | `max_window < min_adaptive_window`，但有 strict-fit 窗口 | 失败规格无替代输出；strict-fit 普通 focus 仍正常保留 |

### 异常处理

| 异常 | 处理方式 |
|------|----------|
| `event_time` 为 0 或负值 | adaptive 视为无效输入，跳过所有 ratio，记录告警日志；普通 focus 仍必须遵守 Track A strict-fit-only，非 strict-fit 固定窗口不得回退为平移输出 |
| `video_duration <= min_adaptive_window` | 不生成 adaptive；普通 focus 仍必须遵守 Track A strict-fit-only，非 strict-fit 固定窗口不得回退为平移输出 |
| `event_time > video_duration` | 视为无效输入，跳过 adaptive，记录告警日志 |
| 浮点精度问题 | max_window 保留 3 位小数或量化到帧边界，比较时使用容差 `1e-6` |
| 并发处理多个视频 | 每个视频独立调用，无共享状态 |

### 日志要求

每条调用至少记录：

- 视频 ID、event_time、video_duration
- 每个 ratio 的处理结果（strict-fit 普通 focus 列表 / 失败固定规格列表 / 生成 adaptive / adaptive 过小跳过）
- Track B 被触发时记录计算的 max_window 值
- 不生成 adaptive 时记录原因（无失败固定规格，或 `max_window < min_adaptive_window`）

---

## Testing strategy

### 单元测试

**测试目标**：`build_focus_subvideos` 中普通 focus 兼容性、strict-fit 判定和 adaptive 生成逻辑

| 测试用例 | 输入 | 预期输出 |
|----------|------|----------|
| 正常居中事件（全 strict-fit） | ratio=0.5, event_time=15, duration=60 | 所有 4 个窗口均 strict-fit → 各生成普通 focus；`has_failed_by_ratio[0.5]==False` → 不生成 adaptive |
| 左边界事件（部分 strict-fit） | ratio=0.5, event_time=1.6, duration=60 | 3s strict-fit（3*0.5=1.5 ≤ 1.6, 3*0.5=1.5 ≤ 58.4）→ 保留 3s 普通 focus；5/10/20s 非 strict-fit → 丢弃平移输出；该 ratio 存在失败规格 → 唯一 adaptive（max_window=3.2）替代 5/10/20s 失败规格；3s 普通 focus 与 adaptive 并存 |
| 左边界事件（全非 strict-fit，adaptive 足够） | ratio=0.5, event_time=1, duration=60 | 所有窗口非 strict-fit → 不保留普通 focus（平移输出丢弃）；max_window=2.0 ≥ min_adaptive_window → 唯一 adaptive 替代 |
| 极左边界事件（全非 strict-fit，adaptive 过小） | ratio=0.5, event_time=0.2, duration=60 | 所有窗口非 strict-fit → 不保留普通 focus；max_window=0.4 < min_adaptive_window → 该 ratio 无任何输出 |
| 右边界事件（全非 strict-fit） | ratio=0.5, event_time=59, duration=60 | 所有窗口非 strict-fit → 不保留普通 focus；max_window=2.0 ≥ min_adaptive_window → 唯一 adaptive 替代 |
| 较长窗口退化验证 | ratio=0.2, event_time=0.5, duration=60 | 所有窗口非 strict-fit → max_window=2.5；生成唯一 adaptive (2.5s)，替代 3/5/10/20s 全部失败规格，不重复生成 4 个 adaptive |
| 去重验证 | 同一 ratio 触发 Track B | 同一 ratio 最多一个 adaptive focus（而非 4 个） |
| strict-fit 普通 focus 契约 | 任意有 strict-fit 的场景 | `subvideo_id` 不变，`crop_type` 保持 `focus_{window}s` |
| ratio 量化误差 | 3s@2fps, ratio=0.35 | 验收使用帧量化容差，不要求严格等于 0.35 |
| 混洗验证（多个 strict-fit + 部分非 strict-fit） | ratio=0.5, event_time=4, duration=60 | 3s/5s strict-fit → 保留 3s 和 5s 普通 focus；10/20s 非 strict-fit → 丢弃平移输出，由唯一 adaptive（max_window=8.0）替代；普通 focus 与 adaptive 并存 |

### 集成测试

| 场景 | 方法 |
|------|------|
| 完整视频管道（混合场景） | 输入一个已知边界事件的视频，验证：(a) strict-fit 的 (window, ratio) 生成普通 focus；(b) 存在失败规格的 ratio 生成唯一 adaptive focus（替代所有失败规格）；(c) 同一 ratio 下 strict-fit 普通 focus 与 adaptive 可同时并存 |
| 命名验证 | 检查普通 focus 命名/crop_type 不变；非 strict-fit 焦点无普通 focus 输出；adaptive 子视频文件名包含 `_adaptive` 后缀 |
| 去重验证 | 同一 ratio 下最多生成一个 adaptive focus，不因 3/5/10/20 秒分别触发而产生 4 个 |
| 多 ratio 覆盖 | 验证同一视频下 5 个 ratio 各自独立处理，互不影响 |
| 元数据兼容 | 验证 adaptive 元数据包含 `is_adaptive_focus` 和 `actual_focus_window_seconds`，下游 review/training 流程可识别 |
| 无重复退化 | 较长窗口（10/20s）与较短窗口（3/5s）在同 ratio 下生成同一个 max_window adaptive，不留重复 |

### 回归测试

| 检查项 | 说明 |
|--------|------|
| strict-fit 普通 focus 输出不变 | 对于能 strict-fit 的 `(window, ratio)`，普通 focus 的 `subvideo_id`、`crop_type` 与旧版一致 |
| 非 strict-fit 窗口不再保留 | 旧版会输出平移后的普通 focus，新版丢弃这些失败规格（由 adaptive 替代或 ratio 整体无输出） |
| 居中事件输出不变 | 对于居中的事件，各 ratio 均有 strict-fit 窗口，输出与旧版一致，不生成 adaptive |
| 边界事件不崩溃 | 旧版可能报错的边界输入，新版至少不会崩溃 |
| 无重复 adaptive | 同一 ratio 下仅生成一个 adaptive focus（替代全部失败固定规格），非 4 个 |
| ratio 容差 | adaptive focus 的事件位置 ratio 在帧量化容差内 |
| 较长窗口退化无重复 | 10/20s 若因边界不足退化到同一 max_window，与 5s 共享同一个 adaptive，不留独立副本 |

### 验收标准清单

- [ ] 所有 unit test 通过
- [ ] 边界 case 覆盖左/右/极左/极右四种场景
- [ ] 去重逻辑验证通过（同一 ratio 下仅生成一个 adaptive focus，非 4 个）
- [ ] 较长窗口退化验证通过（10/20s 与 5s 在同 ratio 下共享同一个 adaptive，无重复）
- [ ] strict-fit 普通 focus 的 `subvideo_id` 和 `crop_type=focus_{window}s` 回归不变
- [ ] 非 strict-fit 固定窗口不再保留为普通 focus（平移输出已丢弃）
- [ ] adaptive focus 的命名、crop_type 和新增元数据字段检查通过
- [ ] 回归测试确认居中事件输出与旧版一致，且不会多生成 adaptive
- [ ] ratio 验收使用帧量化容差，避免不可实现的严格浮点相等
- [ ] 日志输出完整、可读（至少包含每个 ratio 的处理结果——已有 strict-fit / 生成 adaptive / ratio 无输出）

---

## Sample / smoke generation before full generation

### Motivation

Full generation of focus subvideos processes the entire video metadata file (potentially hundreds of videos, each generating 20-80 subvideo candidates + media). Before committing to a full run — especially when testing new logic like adaptive focus Track B — the operator needs a fast feedback loop:

- Does the adaptive logic produce valid output for boundary cases?
- Are file paths, metadata fields, and crop_type values correct?
- Are there any crashes, assertion errors, or frame-out-of-bounds issues?
- Is the output quality acceptable before occupying the training machine for hours?

A sample/smoke mode addresses this by generating only a small, controllable subset of subvideos into an isolated output directory, allowing inspection before full generation.

### Requirements

| # | Requirement | Rationale |
|---|-------------|----------|
| 1 | **Limit generation to a subset of source videos** | Operator specifies how many videos (e.g. 5, 10, 20) or specific video IDs to process; quick iteration without waiting for the full dataset |
| 2 | **Deterministic sampling** | Same seed + same input → same sample set; reproducible for debugging and comparison across runs |
| 3 | **Cover boundary / adaptive-prone cases** | Random sampling of easy (centered) events misses the very cases adaptive focus is designed for. Sample mode should intentionally include videos with events near boundaries, short durations, extreme ratios, and those known to trigger Track B |
| 4 | **Isolated output directory** | Sample output must not pollute the full output directories (`data/subvideos/`, `data/frames/`, `data/subvideos_meta.json`). A separate sample output tree allows safe inspection, comparison, and cleanup without affecting production data |
| 5 | **Print manifest and counts** | After generation, print a clear summary: how many videos processed, how many subvideos generated (ordinary vs adaptive), per-ratio counts, and output paths. The manifest should be machine-readable (JSON lines) for downstream inspection scripts |
| 6 | **Gate full generation on sample pass** | The operator inspects sample output (manifest, file naming, metadata, frame samples), then explicitly decides whether to run a separate full-generation command. Sample mode must never continue into full generation automatically |
| 7 | **Zero side effects on non-sample outputs** | When running in sample mode, no files outside the sample output directory are created, modified, or deleted. The input video metadata file is read but never mutated |

### Proposed CLI extension

The existing entrypoint is `pipeline/scripts/subvideo_builder.py` using argparse with kebab-case flags. New parameters follow the same style:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--sample-size` | `int` | omitted | Number of videos to sample. Must be ≥ 1 when provided; omitting it keeps full-generation mode unless `--video-ids` is provided |
| `--sample-seed` | `int` | `42` | RNG seed for deterministic video selection and ordering within sample mode. Independent from `--seed` (which controls candidate generation internals) |
| `--sample-output-dir` | `Path` | `data/sample_subvideos/` | Root output directory for sample generation. Creates `sample_subvideos/03_subvideos/`, `sample_subvideos/04_frames/`, and `sample_subvideos/sample_manifest.json` inside this path |
| `--video-ids` | `str nargs="*"` | `None` | Explicit list of video IDs to process (alternative to `--sample-size`). When specified, overrides random sampling and processes only the given IDs |
| `--sample-boundary-weighted` | `store_true` | `False` | When enabled, sample selection weights videos with events near boundaries (event_time ≤ 15s or ≥ duration-15s), short duration (≤ 20s), or those with extreme ratios. Ensures sample covers adaptive-relevant cases, not only easy centered events |

**Parameter naming consistency check with existing codebase:**

| Existing style | This proposal |
|---------------|---------------|
| `--seed` | `--sample-seed` (separate concern, independently controllable) |
| `--subvideo-dir`, `--frame-dir` | `--sample-output-dir` (single root, internally creates `subvideos/` and `frames/` subdirs) |
| bool flags use `store_true` where needed | `--sample-boundary-weighted` (bool store_true) |
| kebab-case always | kebab-case maintained |

### Algorithm for sample selection

```
1. Read full video_meta into a list of video records
2. Determine initial candidate set:
   a. If --video-ids is provided:
      filter to only those IDs (error if any ID not found)
   b. Else if --sample-boundary-weighted:
      score each video by:
        - min(event_time, duration - event_time)  [lower = more boundary-prone]
        - penalty for easy centered events
      apply weighted random sampling without replacement
   c. Else:
      simple random sampling without replacement using --sample-seed RNG
3. Cap at --sample-size videos
4. Print candidate summary (IDs, event times, durations, expected adaptive ratios)
5. Pass to build_focus_subvideos in a loop (same as full generation path)
6. Output to --sample-output-dir with isolated paths
7. Print manifest and exit. Full generation requires a separate explicit run without sample flags after inspection passes
```

### Acceptance criteria

- [ ] `--sample-size 5` processes exactly 5 videos (or fewer if dataset is smaller) into an isolated output directory
- [ ] `--sample-seed 42` gives reproducible results across runs with the same input
- [ ] `--video-ids VID001 VID002` processes only those two videos, regardless of sample size
- [ ] `--sample-boundary-weighted` selects at least one video per boundary scenario (left, right, short) when available in the dataset
- [ ] Sample output directory contains `03_subvideos/`, `04_frames/`, and `sample_manifest.json`, isolated from the full output paths
- [ ] Running sample mode does not modify `data/subvideos/`, `data/frames/`, or `data/subvideos_meta.json`
- [ ] Manifest output includes: total videos processed, total subvideos (split by ordinary vs adaptive), per-ratio counts, per-video summary with file paths
- [ ] Any run with `--sample-size` or `--video-ids` exits after sample generation and never starts full generation automatically
- [ ] Full generation requires a separate explicit command after the operator inspects and approves sample output
- [ ] Sample generation output is deterministic given the same `--sample-seed` and input data

## Open questions

| 问题 | 是否阻塞 |
|------|----------|
| 日志输出级别和格式是否需要与现有 pipeline 的监控告警系统对齐？ | 否 |
| 是否需要对 adaptive focus 的子视频添加原始 max_window 计算参数，方便日后调试？ | 否 |
| video_duration/event_time 与帧索引之间的精度和单位是否需要统一校验？ | 否 |
| 实现 sample generation 时应该修改 `main()` 入口还是在外面包装一个新的 CLI entrypoint？ | 否 |
| sample manifest 格式：应输出单独的 JSON Lines 文件，还是复用 `subvideos_meta.json` 结构仅改变根路径？ | 否 |
