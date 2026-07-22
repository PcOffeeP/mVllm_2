# v3 子视频候选计划 dry-run 设计

## 目标与范围

阶段 B 第一版只读取版本化 `video_meta.roi.json`、ROI media manifest、v3 历史审查参考和
`tensile-vlm/v3` 契约，生成内容寻址的候选计划、统计和复审队列。规划器不读取视频像素、
不加载模型、不调用 ffmpeg，也不创建 MP4 或帧图。

## 非目标

- 不修改或复用旧 `subvideo_builder.py` 的 v2 生成路径。
- 不决定最终训练样本配比，不生成 `06_merged` 或 `08_training_ready`。
- 不把历史审查部分重叠记录自动升级为已审核标签。
- 不将 test 候选或 test 历史审查混入 development 输出和统计。

## 输入与身份

规划器必须验证 ROI manifest 中的 `video_meta.roi.json` SHA-256、110 条记录的唯一性和
`roi_media_id`，再验证历史参考 manifest 中 development/test artifact 的 SHA-256、89/21
清单互斥且完整覆盖 ROI metadata。计划身份包含输入哈希、v3 契约 hash、策略版本和全部策略
参数；计划 ID 为 `candidate-plan-<内容哈希前 12 位>`。

## 候选策略

候选时长以 20/10/5/3/2 秒为目标，所有边界按源视频帧率对齐。断裂事件前后 `0.5s` 作为
稳定“未断裂”和“已断裂”的安全边界；“发生断裂”只要求区间严格跨越事件时刻。

- `发生断裂`：使用多尺度、不同事件位置模板；短视频或边界事件允许生成去重后的自适应区间。
- `未断裂`：脆性断裂源每源最多 3 条；韧性和半脆半韧源最多 6 条；其他断裂源最多 4 条。
- `已断裂`：每个断裂源最多 2 条，避免用同一源的断后背景堆积样本。
- 正常未断裂源：最多 6 条，覆盖不同尺度与时间位置。
- `未夹紧`、`视频异常`或缺少可靠事件时间：最多 3 条 `无法判断` 候选。
- 源视频不超过 20 秒时，完整区间可作为上述上限内的一个候选；不得因此突破上限。

候选标签只由源 metadata、区间与 v3 规则推导。规划阶段没有真实采样帧，因此标签为
`candidate_v3_labels`，后续媒体生成和人工审查仍可推翻。

## 历史审查匹配

同一源视频且起止帧完全一致、历史状态可用并且 v3 候选标签一致时，标记
`reference_exact` 并保存引用 ID。存在精确区间但标签冲突、只有部分重叠或没有匹配时都进入
`needs_review`；部分重叠只记录交并比最高的有限条参考，不自动复制标签。

## 输出与隔离

非 dry-run 写入不可覆盖目录 `data/07_metadata/v3/candidate_plans/<plan_id>/`：

- `development_candidates.json`：仅 89 个 development 源；
- `test_candidate_audit.json`：仅 21 个 test 源，不能作为训练输入；
- `needs_review.json`：development 中需人工复审的候选；
- `statistics.json`：按 scope 分离的状态、时长、模式、匹配和每源贡献统计；
- `manifest.json`：输入、策略、artifact hash 和数量。

`--dry-run` 只向标准输出打印计划 ID 与统计，不创建输出目录。相同输入重复写入只允许验证并
复用完全一致的目录；身份或 artifact 不一致时失败，不覆盖。

## 失败处理与验证

输入哈希不一致、split 交叉或不完整、非法时间/帧率、候选越界、状态规则冲突和既有目录漂移
均 fail closed。测试覆盖输入身份、split 隔离、脆性负样本上限、事件安全边界、历史精确/部分
匹配、dry-run 零写入、内容寻址幂等和真实 110 条轻量产物的完整规划。
