# DEC-007：跨 dev↔test 近重复源视频选项 A 排除与 15 条虚拟视频隔离口径

- **决策状态：已确认。** 用户已于 2026-11-25 确认按 [虚拟视频测试集泄漏审查与 110 条真实源视频去重审计](../research/source-video-dedup-audit.md)（PR #23）选项 A（最小扰动）处置 2 对跨 `dev ↔ test` 近重复真实源视频，并将虚拟视频隔离口径由 12 条更新为 15 条。
- **记录日期：2026-11-25。**
- **适用范围：** 全部模型训练、开发调参、三折交叉验证、评测子集冻结与虚拟视频使用边界。
- **实施状态：** 机器可读排除清单 [`data/splits/dev-exclusions.json`](../../data/splits/dev-exclusions.json) 及相关文档口径已落地；后续训练与评测数据构建脚本消费 `data/splits/three-fold/` 时必须联合读取该排除清单。登记本决定不构成启动真实训练、重生成子视频或改写源标注表的授权。

## 背景

2026-11-25 对 110 条真实源视频（5,995 对）与 65 条 `data/virtual/video-V1` 虚拟视频的去重审计（PR #23，见 [source-video-dedup-audit.md](../research/source-video-dedup-audit.md)）确认了 2 对同一物理实验的跨 `dev ↔ test` 近重复源视频：

1. `video_0006`（`fold_0_val` / `fold_1_train` / `fold_2_train`）↔ `video_0010`（`test`）：金属韧断同一实验，且 `video-V1` 中有 3 条虚拟视频参考 `video_0006`；
2. `video_0079`（`fold_1_val` / `fold_0_train` / `fold_2_train`）↔ `video_0032`（`test`）：高分子半脆半韧同一实验（`video_0032` 原已有 11 条虚拟视频隔离）。

## 决定

1. **采用选项 A（保固定 `test.json` 不动，开发侧强制排除 `video_0006` 与 `video_0079`）**
   - 保持固定测试集 `data/splits/three-fold/test.json`（21 条）逐字节不动。
   - 在全部模型训练、开发调参、三折验证与评测子集构建中，强制排除开发源 `video_0006`（19 条子视频）与 `video_0079`（1 条子视频）。
   - 有效开发源由 **89 降至 87**，三折有效规模均恰好为 **`58 train / 29 val`**；有效开发子视频由 **1,319 降至 1,299**（扣除 20 条）。
2. **保持 `data/splits/three-fold/*.json` 原字节不变，以独立排除清单 `data/splits/dev-exclusions.json` 落地**
   - `script/subvideo_review/server.py` 将 `data/splits/three-fold/` 7 份成员文件哈希计入 `split_identity_sha256` 与 `review_subject_sha256`。若直接修改 `fold_*_{train,val}.json`，会导致 `reviews.json` 中全部 527 条已确认人工审核记录的身份失效，并触发 `ReviewApp` 与 `test_batches.py` 报错。
   - 因此不改写 `data/splits/three-fold/*.json` 历史快照，改由独立的机器可读清单 [`data/splits/dev-exclusions.json`](../../data/splits/dev-exclusions.json)（`schema: tensile-dev-exclusions/1`）统一承载排除源、20 条排除子视频及 15 条隔离虚拟视频名单；所有下游训练/评测构建入口必须显式读取并过滤该清单。
3. **虚拟视频隔离口径由 12 条更新为 15 条**
   - 在原 12 条直接参考固定 `test` 源（`video_0025` 1 条 + `video_0032` 11 条，`direct_test`）基础上，新增隔离 3 条参考 `video_0006` 的虚拟视频（`metal_round_ductile_baseline_v1`、`metal_round_ductile_stage1_a2_v1`、`metal_round_ductile_coupled_a2_time12_v1`，`transitive_via_near_dup`），合计 **15 条**严禁用于训练与开发调参。
   - 其余 **50 条**（`clean_dev_only`，涉及 8 个开发源）仅可在按折隔离前提下用于开发试制或非冻结诊断，严禁跨折泄漏。

## 影响与不改的部分

- **不改的部分**：不改写 `data/splits/three-fold/*.json`（8 份文件逐字节不变）、不改写 `data/annotation-table-full.csv`、不重生成 `data/sub_video/`、不改写 `data/roi/manifest.json`、不修改 `docs/label.md`，也不删除或改写 `data/subvideo-review/reviews.json` 中已确认的历史审核记录（含 B2 中已审的 `video_0006_pre_06`、`video_0006_pre_13`、`video_0079_fracture_01`）。
- **同步文档**：已同步更新 [整体模型测评方案](../design-test.md)、[65 条虚拟视频溯源](../research/virtual-video-provenance.md)、[本轮划分结果](../split/data-split-result.md)、[项目导航](../guide.md)、[TODO](../TODO.md) 与 [`docs/facts.yaml`](../facts.yaml)（`DF-054`）。

## 取代关系

本决定在 [DF-020](../facts.yaml)（2026-11-19 三折划分）与 [DF-031](../facts.yaml)（原 12 条虚拟视频隔离）基础上补充选项 A 排除规则与 15 条虚拟视频隔离口径，不改写历史划分文件与历史结论。

**失效条件：** 若未来经用户确认采用方案 B 重新划分测试集与开发集、增补/替换 110 条源视频、导入新版本虚拟数据集（如 `video-V2`），或对 32 条 `1280×720` 复材固定机位簇完成全量未决配对核验并发现新的跨划分近重复时，须同步更新 `data/splits/dev-exclusions.json` 并登记新决策。
