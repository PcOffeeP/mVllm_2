# 人工审查后的再生成与复标规则

运行 `pipeline/scripts/audit_review_decisions.py` 生成审计队列后，按以下规则处理；该脚本不会修改原始标签或训练元数据。

1. `needs_regenerate` 且备注为“未包含断裂/断裂时刻发生在片段外/开始时已经断裂”：先复核原视频的断裂时刻和帧号，再重生成对应源视频的子视频。不能只重跑裁剪。
2. approved 的 `has_fracture`、`type`、`location` 改动：先在 `all_videos_tag.csv` 和原视频中确认。若与原标注冲突，列为“待重新标注”；确认后只在源标签层修正，再重新派生所有 full/focus 子视频标签。
3. `fracture_between` 改动：必须用 `subvideos_meta.json` 的 `actual_frame_mapping` 和确认后的源事件帧重算。新旧区间都不能单独作为真实时间的证据。
4. location 只允许 `inside_gauge`、`outside_gauge` 或 `null`。`outside_guage` 一律视为拼写错误，不能进入训练数据。`脆性断裂、齐根断裂` 不在当前类型集合内；必须由用户确认是新增类别还是映射至既有类别，不能自动归一化。
5. 完整视频或 focus 子视频的关键标签一旦变更，应按源视频聚合处理，避免同一源视频的不同子视频保留相互矛盾的类型/位置。

## 下一轮人工审查的最小队列

- 先审 `review_regeneration_queue.csv` 中 `must_recheck_original_event=true` 的源视频；对每个源视频只确定一次真实事件帧/时间。
- 再生成子视频和 `actual_frame_mapping`，运行审计脚本并处理 `review_fracture_interval_queue.csv` 的 `conflict`。
- 只向人工展示：重生成样本、关键标签改动、区间重算冲突和源时间/帧号超过一帧误差的条目。其余 approved 且无差异的样本不重复审阅。

## 时间轴注意事项

对 MP4 的诊断使用 `avg_frame_rate` 或 `nb_frames / duration`；不得直接使用 `r_frame_rate`。本数据中部分文件的 `r_frame_rate` 为 60，而视频的平均时间轴约为 30 fps，直接使用前者会制造约 2 倍的伪时间误差。
