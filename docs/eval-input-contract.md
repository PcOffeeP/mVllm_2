# 评测输入契约（索引页）

**失效条件：** 合并顺序 W4 → W3 → W2 → W5 变动；`docs/eval/` 内任一专题文件改名、拆分或合并；`script/five_label_eval/score.py` 的字段、取值或校验行为改变；术语统一已合入本分支（提交 `045536c`）且本页已按合并后状态复核，其后再出现上述变动时须重新核对。以上任一发生，本页与下表路径映射即失效，须重新核对。

本路径原为单文件长契约，现已拆分为 `docs/eval/` 专题文档集；本页只作索引入口，不再承载任何字段表与取值表。

| 专题文件 | 承担内容 | 何时读它 |
| --- | --- | --- |
| [`docs/eval/README.md`](eval/README.md) | 范围界定、阅读顺序、改契约时要同步的对象清单、各文件失效条件汇总 | 第一次进契约，或动手改动前确认要同步哪些对象 |
| [`docs/eval/output-contract.md`](eval/output-contract.md) | 11 个叶字段与 5 个顶层键、四类边界样例、`predictions.jsonl` 必填项、关键词义、代码同步状态 | 改字段或取值、判读模型输出格式、排查 `invalid`／`missing` |
| [`docs/eval/prompt.md`](eval/prompt.md) | v1 prompt 正文位置、约束项与评分器行为对应、版本策略、冻结机制、术语同步待办 | 改 prompt 文本、升版本号、核对 `prompt_id` |
| [`docs/eval/inference-entry.md`](eval/inference-entry.md) | 推理入口 CLI 与拟定签名、身份字段口径、三态与重试、backend 边界、旧实现借鉴 | 接模型、跑批次、填身份字段、追查失败行 |
| [`docs/eval/input-record.md`](eval/input-record.md) | 四层画面谱系、四个帧索引、`source_start_frame` 命名陷阱、同序证据、四层一致性校验、逐层导出 | 抽帧、写输入记录、追溯帧号、核对实际输入 |
| [`docs/eval/eval-subset.md`](eval/eval-subset.md) | 画幅三档、报告必报项、`max_pixels` 与分档绑定、分层抽样与冻结、旧批次退流 | 划定评测子集、写评测报告、比较不同画幅结果 |

**合并顺序依赖（未同步完毕）：** 本路径被 W3 的 `docs/base-model-eval-plan.md` §6（画幅三档必报）与 W5 的 `docs/eval-migration-plan.md` 判据④（四类边界用例）引用。W3 的画幅三档引用已改指 `docs/eval/eval-subset.md` §1（即原 §4.6 内容）；**W5 判据④ 仍写着「用例定义见 `docs/eval-input-contract.md` §1」（`docs/eval-migration-plan.md:126`），该引用已失效**：本页拆分为纯索引页后文件内无任何编号章节（全文件只有一个一级标题），且该处括注「该文件位于分支 `feat/eval-input-contract`，合并入主线后引用生效」已不成立。四类边界用例的实际内容在 `docs/eval/output-contract.md` §2，该引用应改指该处。**本页只指出该失效与应改指的目标，不表示引用已同步**（W5 文件尚未订正）；移动、改名或删除本路径前，必须先同步上述引用。另需注意：W3 该节正文原先写的是单值三类按旧字面量统计，与取值口径不一致，该处已订正为现行取值 `无法判断`。

**失效条件（补充）：** 若本页被改成非索引页（重新内联字段表或取值表），或 `docs/eval/` 不再是六个文件的集合，则本页与其被引用的合并顺序依赖同时失效。
