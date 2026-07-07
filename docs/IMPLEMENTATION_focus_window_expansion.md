# Focus 子视频窗口边界扩展实施文档

## 1. 背景与问题

当前 `build_focus_subvideos` 在事件（event）靠近视频边界时，采用单侧截断（clamp）方式固定窗口，导致断裂时刻在子视频中的相对位置偏离预设 ratio。

现有统计数据显示：

- 共 1580 个 focus 子视频。
- 其中 917 个（58%）被 clamp。
- 平均偏差 0.21。
- 最大偏差 0.69。

预设目标位置 ratio 为 20% / 35% / 50% / 65% / 80%。单侧 clamp 使得大量子视频的实际事件位置偏离这些目标值，引入位置偏置风险。

## 2. 目标

- 保证断裂时刻在 focus 子视频中尽可能均匀分布。
- 在事件靠近边界时，优先向对侧扩展窗口，以保持事件相对位置和窗口长度不变。
- 当两侧空间均不足以容纳完整窗口时，丢弃该候选。

## 3. 修改范围

| 文件 | 修改内容 |
|------|----------|
| `pipeline/scripts/subvideo_builder.py` | 修改 `build_focus_subvideos` 的窗口 clamp 逻辑，实现向对侧扩展。 |
| `tests/test_frame_contract.py` 或 `tests/test_tail_review.py` | 补充边界扩展相关单元测试。 |
| `docs/IMPLEMENTATIONS/2026-06-30-training-data-review-pipeline.md` | 可选：同步更新窗口策略描述。 |

## 4. 算法变更

### 4.1 当前逻辑

1. 根据事件位置和预设 ratio 计算理论窗口 `[start, end]`。
2. 若窗口超出视频边界，直接对越界侧进行 clamp。
3. 保持另一侧不变。
4. 结果：窗口长度改变，或事件相对位置偏离目标 ratio。

### 4.2 新逻辑

1. 按事件位置和预设 ratio 计算理论窗口 `[start, end]`。
2. 检查窗口是否完全在视频边界内：
   - 若完全在界内，直接采用。
   - 若左侧越界（`start < 0`），保持 `end` 不变，将 `start` 向右推至 `0`，并检查右侧是否有足够空间将窗口整体右移以恢复目标长度和 ratio。等价表述：优先向右侧（对侧）扩展窗口。
   - 若右侧越界（`end > video_duration`），保持 `start` 不变，将 `end` 向左拉至视频末尾，并检查左侧是否有足够空间将窗口整体左移以恢复目标长度和 ratio。等价表述：优先向左侧（对侧）扩展窗口。
3. 若两侧空间均不足以容纳完整窗口，丢弃该候选。
4. 扩展后再次执行 clamp 检查，确保最终窗口严格位于视频边界内。

## 5. 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 事件靠近开头 | `end` 向右扩展，保持窗口长度和目标 ratio。 |
| 事件靠近末尾 | `start` 向左扩展，保持窗口长度和目标 ratio。 |
| 两侧均不足 | 丢弃该 focus 候选，不生成子视频。 |
| 扩展后二次检查 | 对最终窗口再次执行边界检查，防止浮点误差或帧对齐导致的越界。 |

## 6. 预期影响

- focus 子视频总数可能减少，但事件位置分布更均匀。
- 3 秒窗口的 focus 子视频时长统一为 3.0 秒，帧数统一为 6 帧。
- 降低因单侧 clamp 导致的位置偏置风险。
- 训练样本的位置分布更符合预设 ratio，有助于提升模型对断裂位置的敏感性。

## 7. 测试计划

新增以下测试用例：

- `test_focus_window_expands_toward_opposite_side`
  - 验证事件靠近一侧边界时，窗口向对侧扩展，事件 ratio 仍符合预设值。

- `test_focus_window_drops_when_both_sides_insufficient`
  - 验证当视频剩余时长不足以容纳完整窗口时，该候选被丢弃。

- `test_focus_event_position_matches_intended_ratio`
  - 验证生成 focus 子视频中事件相对位置与 20%/35%/50%/65%/80% 的偏差在允许误差内。

- `test_focus_3s_always_has_6_frames`
  - 验证所有 3 秒 focus 子视频的帧数恒为 6 帧。

## 8. 验证方法

1. 运行 `subvideo_builder` 生成 focus 子视频。
2. 统计 `|actual_ratio - intended_ratio|` 的分布，应接近 0。
3. 统计 3 秒 focus 子视频的帧数分布，应集中在 6 帧。
4. 运行 `review_subvideo_labels` 复检，确认无新增 mismatch。
5. 运行全量测试：

   ```bash
   python3 -m pytest tests/
   ```

## 9. 风险

- 样本数量减少：向对侧扩展失败时丢弃候选，可能导致可用于训练的 focus 子视频总量下降。
- 极端靠边事件可能语义稀释：若对侧扩展导致窗口覆盖大量与事件无关的内容，可能弱化断裂语义。
- 需要重新生成已有 metadata：实施完成后，已生成的 focus 子视频和对应 metadata 需要重新生成或更新。
