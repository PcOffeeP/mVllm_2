# 变更窗口声明：生成规则文档补帧对应取证指针

- 状态：已完成，未改任何数据与代码。
- 时间窗口：2026-11-23，单次文档改动。
- 动因：`docs/guide.md` 已登记 `docs/frame-correspondence-evidence.md`（PR #11），用户要求生成规则文档也给出指向该证据文档的指针。

## 改了什么

在 `docs/subvideo-current-logic.md` §8 末尾追加一段指针，指向 `docs/frame-correspondence-evidence.md`（抽帧留证、不做像素比对）：

> **帧对应取证边界：** 抽帧留证（不做像素比对）的取证范围与样例另见[帧对应取证](frame-correspondence-evidence.md)；该取证不等于帧级重放通过，`basic`／`none` 批次仍不提供帧对应证明。

§1–§8 既有规则文字一字未改，`<!-- unclamped-anchors:start -->` / `<!-- unclamped-anchors:end -->` 锚点块未触碰；文件 diff 只有末尾一处新增。

## 为什么

`docs/guide.md` 已登记该证据文档，生成规则文档此前只在 §8 内说明 `basic`／`none` 不提供帧对应证明，没有指向取证文档。补上指针后，读生成规则的人能直接找到抽帧取证的适用范围与样例；同时该指针明确「取证不等于帧级重放通过，`basic`／`none` 批次仍不提供帧对应证明」，避免把取证当作帧对应证据。

## 身份影响

该文档是批次输入身份的一项：`script/subvideo_generation/generate.py:116` 把 `docs/subvideo-current-logic.md` 的 SHA-256 记入 `identity.inputs`。在盘 1,633 条候选批次 `data/sub_video/manifest.json` 的 `identity.inputs["docs/subvideo-current-logic.md"]` 仍是生成时版本 `ca50492df507a12760cb8ac512eae63549bb2a441f219602772de627e36ca304`，本次改动后当前文件 SHA-256 将与它不同。

因此该批次的 `--resume` 续跑与 `--audit-only` 一致性核对会因身份不符被拒绝（`generate.py:192-198` 的 `_check_identity`，调用点 `generate.py:701`（resume）与 `generate.py:820`（audit）），报错文案为 `input identity differs`。**本批次已定稿，不需要这两项操作**；如需按新文档重生成，须另获明确授权、换新的空输出目录重跑，不得 `--resume`。

## 未改动的东西

`data/sub_video/manifest.json`、`data/sub_video/summary.json`、`data/sub_video/audit.json`、`data/subvideo-review/reviews.json`、人工审核记录、`script/subvideo_generation/**` 全部未改。`audit.json` 的 `manifest_sha256` 仍与清单实盘 SHA-256 一致（`c70686630c8fa0277305cc25a09821bc04ab853f6ce8a6ac3ca795998c08ac0f`），审核服务只按该摘要判当前性，不受本次文档改动影响。

## 已完成与保留期

2026-11-23 已完成。本声明自「已完成」记录之日起保留 7 天，至 **2026-11-30**，期满可直接删除、不归档。

## 失效条件

批次重新生成、文档指针目标改名/删除、或下游开始依赖该段文字作为帧对应证据时，本记录不再作为当前状态依据。
