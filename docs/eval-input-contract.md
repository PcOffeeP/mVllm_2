# 评测输入契约（索引页）

**失效条件：** 合并顺序 W4 → W3 → W2 → W5 变动；`docs/eval/` 内任一专题文件改名、拆分或合并；`script/five_label_eval/score.py` 的字段、取值或校验行为改变；术语统一已合入本分支（提交 `045536c`）且本页已按合并后状态复核，其后再出现上述变动时须重新核对。以上任一发生，本页与下表路径映射即失效，须重新核对。

本路径原为单文件长契约，现已拆分为 `docs/eval/` 专题文档集；本页只作索引入口，不再承载任何字段表与取值表。

| 专题文件 | 承担内容 | 何时读它 |
| --- | --- | --- |
| [`docs/eval/README.md`](eval/README.md) | 范围界定、阅读顺序、改契约时要同步的对象清单、各文件失效条件汇总 | 第一次进契约，或动手改动前确认要同步哪些对象 |
| [`docs/eval/output-contract.md`](eval/output-contract.md) | 11 个叶字段与 5 个顶层键、四类边界样例、`predictions.jsonl` 必填项、关键词义、代码同步状态 | 改字段或取值、判读模型输出格式、排查 `invalid`／`missing` |
| [`docs/eval/prompt.md`](eval/prompt.md) | 现行 v2 与历史 v1 prompt 正文位置、约束项与评分器行为对应、版本策略、冻结机制、术语同步待办 | 改 prompt 文本、升版本号、核对 `prompt_id` |
| [`docs/eval/inference-entry.md`](eval/inference-entry.md) | 推理入口 CLI 与拟定签名、身份字段口径、三态与重试、backend 边界、旧实现借鉴 | 接模型、跑批次、填身份字段、追查失败行 |
| [`docs/eval/input-record.md`](eval/input-record.md) | 四层画面谱系、四个帧索引、`source_start_frame` 命名陷阱、同序证据、四层一致性校验、逐层导出 | 抽帧、写输入记录、追溯帧号、核对实际输入 |
| [`docs/eval/eval-subset.md`](eval/eval-subset.md) | 画幅三档、报告必报项、`max_pixels` 与分档绑定、分层抽样与冻结、旧批次退流 | 划定评测子集、写评测报告、比较不同画幅结果 |

**合并顺序依赖（已同步完毕）：** 本路径被 W3 的 `docs/base-model-eval-plan.md` §6（画幅三档必报）与 W5 的迁移计划判据④（四类边界用例；该迁移计划已删除，有效内容见 `docs/training-machine-review-runbook.md` 与 `docs/design-test.md`）引用，两处引用都已在各自文件内订正为指向拆分后的专题文件，不再指向本页：W3 的画幅三档改指 `docs/eval/eval-subset.md` §1（即原 §4.6 内容，见 `docs/base-model-eval-plan.md` §6 第 5 条）；W5 判据④ 改指 `docs/eval/output-contract.md` §2（四类边界样例）。订正的原因是本页拆分为纯索引页后文件内已无任何编号章节（全文件只有一个一级标题），「本页 §N」形式的引用不再成立，两处括注中「该文件位于分支 `feat/eval-input-contract`，合并入主线后引用生效」一类的前置条件也随之取消。移动、改名或删除本路径前，必须先同步上述引用。历史说明：W3 该节正文原先写的是单值三类按旧字面量统计，与取值口径不一致，该处已订正为现行取值 `无法判断`。

**失效条件（补充）：** 若本页被改成非索引页（重新内联字段表或取值表），或 `docs/eval/` 不再是六个文件的集合，则本页与其被引用的合并顺序依赖同时失效。
