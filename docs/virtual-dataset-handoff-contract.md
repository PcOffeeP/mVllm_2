# 虚拟数据集传输契约（`BlenderTensileVideo` → `TensileAgent-Finetune`）

本文档固化上游仿真视频仓库 `BlenderTensileVideo` 向本仓库 `TensileAgent-Finetune` 交付虚拟拉伸视频数据集时的交付包边界、导入准入门槛、标签映射约定与只读校验规范。

## 1. 交付包边界

上游每个已确认版本位于 `BlenderTensileVideo/datasets/<version>/`，导入本仓库后落地至 `TensileAgent-Finetune/data/virtual/<version>/`（例如 `data/virtual/video-V1/`）。

| 资产 | 上游路径 | 下游路径 | 传输与 Git 规则 |
| --- | --- | --- | --- |
| 虚拟源视频 | `datasets/<version>/videos/*.mp4` | `data/virtual/<version>/videos/*.mp4` | **只复制实体文件，禁止软链接**；不入 Git（由 `.gitignore` 忽略） |
| 28 列标注表 | `datasets/<version>/labels.csv` | `data/virtual/<version>/labels.csv` | **只复制实体文件，禁止软链接**；入 Git |
| 交付清单 | `datasets/<version>/manifest.json`（上游源清单） | `data/virtual/<version>/manifest.json`（下游合并清单） | 导入时合并生成，采用 schema `tensile-virtual-dataset/1`；入 Git |
| 仿真内部档案 | `datasets/<version>/metadata/` | **不搬运** | 不复制到下游；需要查看渲染参数或复核档案时回上游仓库查阅，清单中通过 `upstream.omitted_upstream_assets` 显式记录 |

下游基于该版本生成的派生处理产物（`roi/`、`splits/`、`sub_video/`、`subvideo-review/`）按需写入对应版本目录 `data/virtual/<version>/` 下，不得写入真实数据目录或混入 `data/splits/three-fold/`（详见 `data/README.md`）。

## 2. 导入准入门槛

任意虚拟数据集版本导入 `data/virtual/<version>/` 时，必须同时满足以下全部条件：

1. **上游必须已提交且工作区干净**：
   - `upstream.working_tree_dirty` 必须严格为 `false`，严禁从存在未提交改动或未跟踪文件的脏工作树导出交付包。
2. **完整上游溯源记录**：
   - `manifest.json` 必须声明 `schema == "tensile-virtual-dataset/1"` 与 `source_domain == "virtual"`。
   - `upstream` 对象必须完整记录 `repo`、`dataset_path`、`git_branch`、`git_head`（40 位十六进制提交哈希）以及 `manifest_sha256`（上游源 `manifest.json` 的 64 位十六进制 SHA-256）。
3. **逐文件完整性与结构核验**：
   - `labels.csv` 必须为非软链接实体文件，其 SHA-256 与 `labels.sha256` 一致，数据行数（不含表头）与 `labels.row_count` 一致，且表头包含与 `data/annotation-table-full.csv` 对齐的全部 28 列。
   - `videos/` 目录必须存在且非软链接，`video_count == len(videos)`；每条记录的 `video_path` 必须位于 `videos/` 下，对应实体文件存在且非软链接，文件字节数与 SHA-256 与清单一致。
   - 所有清单视频的实际字节数之和必须等于 `total_video_bytes`。
   - `videos/` 目录内不得存在清单未登记的多余 `.mp4` 文件。
4. **导入后只读不就地改写**：
   - `data/virtual/<version>/{videos/,labels.csv,manifest.json}` 一经导入即视为该版本的只读输入，不得在下游就地修改源视频或源标注表。
   - 如需修正视频、标签或增删样本，须在上游 `BlenderTensileVideo` 完成复核并发布新版本后，作为新版本目录重新导入。
5. **与真实数据目录物理隔离**：
   - 所有虚拟数据集及其派生目录均隔离在 `data/virtual/<version>/` 下，不得与真实源视频目录 `data/videos/`、真实标注表 `data/annotation-table-full.csv` 或真实三折划分 `data/splits/three-fold/` 混放。
   - 跨机同步（Mac ↔ 训练机）后，必须在目标机重新运行校验脚本核对 `manifest.json` 中的全部 SHA-256。

## 3. 标签映射约定与下游边界

### 3.1 上游 6 组设计标签

依据 `BlenderTensileVideo/docs/DESIGN.md` 第 5 节“标签判定与人工验收”，上游整条视频维护以下 6 组设计标签（对象不存在时使用 `不适用`，证据不足时使用 `无法确认`）：

| 标签组 | 合法取值 |
| --- | --- |
| 材料类别 | 金属、高分子、复材、陶瓷、无法确认 |
| 断裂结果 | 未呈现破坏、局部破坏但仍连接、完全断裂、无法确认 |
| 单一主要破坏类别 | 韧性断裂、脆性断裂、界面脱粘、爆炸性断裂、半脆半韧断裂、不适用、无法确认 |
| 断裂位置 | 标距内、标距外非根部、夹口根部、不适用、无法确认 |
| 夹持异常 | 无、未夹紧、无法确认 |
| 拍摄异常 | 无、视频异常、无法确认 |

### 3.2 下游 28 列 `labels.csv` 表头

上游导出器负责将上述 6 组设计标签、时间/帧参数及现象字段统一映射为下游 28 列 `labels.csv`（`video_path` 采用相对路径 `videos/<id>.mp4`），其表头与真实参考表 `data/annotation-table-full.csv` 保持精确一致：

```text
id,video_path,断裂时间点,断裂模式,材料类型,清晰度,断裂位置,断裂帧数,视频时长,视频帧率,视频总帧数,has_fracture,is_abnormal,标注状态,断裂帧_前,断裂帧_后,标注备注,断裂状态,异常_未夹紧,异常_视频异常,异常_爆炸性断裂,现象_伸长,现象_颈缩,现象_开裂,现象_界面分离,断裂时间范围_下界,断裂时间范围_上界,现象_断后脱夹
```

### 3.3 下游独立决策边界

- 上游 `labels.csv` 记录的是整条仿真视频的源级标签与模拟时间点参考，不直接等同于下游训练切片或最终评测标签。
- 下游的 ROI 裁剪、子视频切片、切片级人工重标与数据集用途均由下游独立决定。
- 按 `docs/decisions/0003-five-label-eval-scope.md` 约定，当前虚拟数据集仅用于**试制与链路检查**，不纳入真实五类主评价与固定测试集。

## 4. 只读校验脚本与退出码约定

本仓库提供纯标准库只读校验脚本 `script/checks/virtual_dataset.py` 用于核验导入后的虚拟数据集是否满足本契约。

### 4.1 CLI 用法

```bash
# 校验单个虚拟数据集版本
python3 script/checks/virtual_dataset.py --dataset-dir data/virtual/video-V1

# 自动扫描并校验 data/virtual/ 下所有虚拟数据集版本
python3 script/checks/virtual_dataset.py --all
```

脚本仅执行只读文件检查，不修改任何数据或清单文件，向标准输出打印结构化 JSON 摘要（包含 `ok`、`checked_count`、`passed_count`、`failed_count` 以及每个数据集的逐项检查状态 `checks`、统计 `stats` 与失败详情 `errors`）。

### 4.2 退出码约定

| 退出码 | 含义 |
| --- | --- |
| `0` | 目标虚拟数据集的全部校验项均通过 |
| `1` | 任一校验项失败（包括清单缺失/非法、脏工作树、哈希或字节数不匹配、软链接、多余 `.mp4`、表头缺失、或 `--all` 未扫描到任何数据集目录） |

---

**失效条件：** 当 `manifest.json` 的 schema 版本不再为 `tensile-virtual-dataset/1`、上游 6 组设计标签或下游 28 列 `labels.csv` 表头发生结构性变更、虚拟数据集目录结构不再沿用 `data/virtual/<version>/`，或虚拟数据集用途经正式决策变更为纳入主评价体系时，本文档及 `script/checks/virtual_dataset.py` 须同步修订或废止。
