# v3 标签与历史人工审查参考

本模块为新的视觉模型标签链路提供两个独立能力：

1. `pipeline/v3_labels.py`：五字段 v3 标签契约和候选片段状态推导；
2. `pipeline/review_evidence.py`：将现有 v2 人工审查结果保存为不可覆盖的历史参考证据。

现有 v2 生产契约、训练数据和审查结果不会被原地修改。

## v3 标签

模式版本为 `tensile-label/v3`，标签恰好包含：

```json
{
  "clip_state": "发生断裂",
  "fracture_mechanism": "界面脱粘",
  "root_break": true,
  "location": "inside_gauge",
  "special_case": null
}
```

`clip_state` 取值：

- `未断裂`
- `发生断裂`
- `已断裂`
- `无法判断`

稳定的断裂前、断裂后状态使用事件时刻前后各 `0.5s` 的安全边界。候选“发生断裂”至少需要一个实际采样时间位于事件前、一个位于事件时刻或之后。该推导只产生系统建议，人工审查仍是最终标签来源。

## 审查记录

`pipeline/v3_review_decisions.py` 使用 `tensile-review-decision/v3`：

- 同时保留系统建议、历史建议、人工修正和最终标签；
- 历史建议不能自动成为最终标签；
- `corrected` 状态下人工修正优先；
- `dropped`、`needs_regenerate`、`needs_review` 没有有效训练标签；
- 审查批次采用原子写入，同一路径只允许完全相同的幂等重试。

## 构建历史参考

只读检查：

```bash
uv run python pipeline/scripts/build_v3_review_reference.py --dry-run
```

写入新的内容寻址批次：

```bash
uv run python pipeline/scripts/build_v3_review_reference.py
```

默认输出：

```text
data/07_metadata/v3/review_reference/review-ref-<内容哈希>/
```

输出文件：

- `manifest.json`：输入文件哈希、划分保护信息和产物哈希；
- `development_reference.json`：只允许开发源视频进入；
- `test_reference_audit.json`：冻结测试集的独立审计信息；
- `quarantined_cross_split.json`：历史训练文件中、按当前清单已属于测试集的记录；
- `conflicts.json`：原视频级历史标签冲突；
- `build_report.json`：覆盖率和状态统计。

开发训练、采样比例估计和 Agent oracle replay 只能读取 `development_reference.json`，不能读取测试审计或跨划分隔离文件。

## 当前参考批次

当前 110 条原视频生成的批次为：

```text
review-ref-7cd2e73a1cd1
```

统计：

- 开发源清单 89 条，历史记录实际覆盖 83 条；
- 冻结测试源 21 条，测试审计覆盖 21 条；
- 历史训练文件中有 5 个源现在属于测试集，共 119 条记录，已单独隔离；
- 开发历史共识冲突源：`video_0098`；
- 测试审计历史共识冲突源：`video_0082`。

跨划分隔离源：

```text
video_0067
video_0082
video_0087
video_0093
video_0094
```

这些记录被保存用于审计，但不会进入开发参考索引。

## 测试

```bash
uv run pytest \
  tests/test_v3_labels.py \
  tests/test_v3_review_decisions.py \
  tests/test_review_evidence.py \
  tests/test_build_v3_review_reference.py \
  -q
```

运行全量回归：

```bash
uv run pytest -q
```
