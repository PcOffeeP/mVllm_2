# 人工审查决策审计报告

- 决策：1721 条；通过：1587；需重生成：0；丢弃：134。
- 关键标签变更：has_fracture 80，type 130，location 92。
- 断裂帧区间变更：181 条；人工区间与当前源事件帧冲突：45；可验证且一致：79；源事件本身不可验证：46。
- full/focus 子视频中与原始视频标签冲突、需回查原标注的视频：11 个。
- 原始事件时间与帧号换算相差超过一帧的视频：7 个。

## 必须人工处理

1. 逐项处理 `review_key_label_change_queue.csv` 中 `needs_source_confirmation=true` 的记录；确认后更新原始 CSV 或撤销子视频修正。
2. 处理 `review_fracture_interval_source_queue.csv`：它将人工区间还原为原始帧范围；先在原视频中确定精确首断帧，再更新源标注并重新生成受影响 focus 子视频。
3. `review_regeneration_queue.csv` 中 `must_recheck_original_event=true` 的源视频，须先复核原视频断裂时刻/帧号，再重生成。
4. 已发现 0 个非法修正值；不得进入 canonical 标签。

## 自动化边界

本报告只做可追溯的一致性核验，不从像素自动推断断裂时刻或类型。对于可变帧率风格 MP4，诊断必须使用 average FPS，不能用 r_frame_rate 直接换算。
