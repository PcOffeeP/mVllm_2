# 三折数据划分

当前使用的划分位于项目根目录下的 `data/splits/three-fold/`。ROI 读取其中的七个成员 JSON；每个源视频只关联一组划分记录，不因三折重复处理。当前结果来自已有划分的目录整理，成员文件保持原字节，没有重新搜索或分配成员。

## 输入与输出

生成脚本 `generate.py` 的路径参数必须显式提供。相对路径按执行命令时的当前目录解析。

| 输入 | 当前项目位置／要求 | 参数 |
| --- | --- | --- |
| 标注表 | `data/annotation-table-full.csv`；110 个唯一视频 ID 和完整合法标签 | `--labels` |
| 固定测试成员 | `data/splits/three-fold/test.json`；21 个成员，原字节复制 | `--test-split` |
| 来源分组 | `data/split-inputs/source-groups-20261107.json`；覆盖全部视频，不跨测试／开发集 | `--groups` |
| 输出目录 | 必须不存在，不能包含或覆盖输入；当前已有 `three-fold/` 不可再次生成 | `--output-dir` |
| 旧三折成员 | 可选，包含六份旧 train／val JSON；提供时核对完整性与互斥关系 | `--old-splits-dir` |

脚本还读取仓库中的标签说明、划分规则和自身代码，并在 manifest 中记录输入摘要；不处理视频、ROI 或模型。来源组声明是来源证据，不是素材去重证明。

常规输出只有八个文件：

```text
data/splits/three-fold/
├── test.json
├── fold_0_train.json
├── fold_0_val.json
├── fold_1_train.json
├── fold_1_val.json
├── fold_2_train.json
├── fold_2_val.json
└── manifest.json
```

成员 JSON 保持既有格式，`video_ids` 是下游读取的成员列表。manifest 记录输入摘要、七个输出摘要、数量、规则和代码身份、环境、配置及搜索摘要；不包含自身摘要。输入摘要不能恢复已删除的原始输入。脚本不再输出划分 CSV、输入快照、独立分布或差异报告、完整搜索轨迹，也不建立历史归档目录。

## 使用边界与验证

直接运行 `generate.py` 会按现有规则搜索开发集三折，它不是整理或校验当前结果的入口。需要重新划分时，应先确认数据与规则并取得对应授权；本次已有数据整理不运行该搜索。脚本拒绝覆盖现有目录，完成输入检查和临时写入后才发布新目录。

修改代码后运行合成检查：

```bash
.venv/bin/python -m pytest -q script/data_split/tests
```

合成检查包含精简前后的七份成员文件字节回归。整理真实结果时，另需比较迁移前后七个文件的原始字节与摘要，以及 ID、数量和集合关系；不能仅凭数量相同判断划分未变。该验证不执行真实数据重划，不是模型测试。

划分目录改名后，显式重新运行 ROI 扫描，更新其划分输入记录：

```bash
.venv/bin/python script/roi/roi.py --splits-dir data/splits/three-fold --scan
```

扫描会更新 `data/roi/manifest.json`，不生成 ROI 视频。扫描后须核对划分路径、七个文件摘要和逐视频归属。`data/splits/` 下仅有一个包含 `test.json` 的目录时，ROI 也可自动发现；多个目录时须显式指定。ROI 状态和输入说明见 [ROI 使用说明](../roi/README.md)。

**失效条件：**划分规则、输入约束、成员格式、输出布局或 ROI 读取接口变化时更新本说明；新数据或新划分不能直接沿用当前结果的验证结论。
