# 变更窗口声明：新增 `data/splits/dev-exclusions.json`（选项 A 排除清单）

- **日期**：2026-11-25
- **工作线**：`work/b2-sync-dedup`（统一同步 B2 审核结果、源标注待改清单、项目状态与 PR #23 选项 A 落地）
- **状态**：已完成（2026-11-25，Draft PR #25 占坑后追加实际改动并完成验收）
- **变更意图**：按 [虚拟视频测试集泄漏审查与 110 条真实源视频去重审计](../research/source-video-dedup-audit.md)（PR #23）选项 A（最小扰动），在不修改 `data/splits/three-fold/*.json` 原字节的前提下（守住 `split_identity_sha256`、全部 527 条已确认人工审核记录身份、`ReviewApp` 及 `test_batches.py`），在 `data/splits/` 下新增机器可读排除清单 `data/splits/dev-exclusions.json`，明确在所有训练与开发调参中强制排除近重复开发源 `video_0006`（19 条子视频）与 `video_0079`（1 条子视频）并隔离 15 条测试关联虚拟视频（12 条直接关联 + 3 条经 `video_0006` 间接关联）。
- **涉及全局共享只读路径**：
  - 新增：`data/splits/dev-exclusions.json`
  - **严格不改**：`data/splits/three-fold/*.json`（7 份成员清单与 `manifest.json` 逐字节不动）、`data/annotation-table-full.csv`、`data/roi/*.json`、`data/sub_video/`、`docs/label.md`
- **开工前探针**：`gh pr list --state open --json number,headRefName,title,isDraft,labels,files` 返回 `[]`（0 个在途 PR 占坑）。
- **预计时间窗口**：2026-11-25 当日单 PR 完成并转正。
- **备份位置**：`data/splits/dev-exclusions.json` 为全新文件，无既有文件被覆写；`data/splits/three-fold/` 全部 8 个文件原字节保持不变（SHA-256 见 `docs/split/data-split-result.md`）。
- **回滚方式**：直接 `git revert` 对应提交或删除 `data/splits/dev-exclusions.json` 即可恢复原状，不影响 `data/splits/three-fold/*.json` 或既有审核记录。

---

## 完成记录

- **完成时间**：2026-11-25
- **实际改动**：
  - 新增 `data/splits/dev-exclusions.json`（6,523 B，SHA-256 `52d9b04af7924cab58c95451dd48eb1e597a61582e5bd47fc7f603c7844b0758`，`schema: tensile-dev-exclusions/1`）：登记排除 `video_0006`（19 条子视频）与 `video_0079`（1 条子视频），以及 15 条隔离虚拟视频（12 条 `direct_test` + 3 条 `transitive_via_near_dup`）。
  - 核对 `data/splits/three-fold/` 全部 8 个文件原字节未改动（`git status` / `git diff data/splits/three-fold/` 为空），`split_identity_sha256` 与 `data/subvideo-review/reviews.json` 全部 527 条已确认人工审核记录身份保持有效。
  - 同步新增 [DEC-007](../decisions/0007-dev-test-dedup-exclusion.md) 与 `docs/facts.yaml` `DF-054`，更新 `docs/decisions/README.md`、`docs/design-test.md`、`docs/research/virtual-video-provenance.md`、`docs/split/data-split-result.md`、`docs/guide.md` 与 `docs/TODO.md`。
- **校验结果**：
  - `data/splits/dev-exclusions.json` 与 `data/sub_video/manifest.json`（20 条排除子视频）、`data/virtual/video-V1/manifest.json`（15 条隔离虚拟视频）交叉核对通过。
  - `script.checks.facts --json`：evidence 313、passed 233、`gone` 0、`ambiguous` 0、unverifiable 80、structure 0。

**保留期说明**：按 `AGENTS.md` §2，本变更单自「已完成」记录之日起保留 7 天，期满可直接删除、不归档。
