# `data/` 目录管理说明

本目录同时存放**真实视频**与**虚拟视频**及其后续处理产物。两者按物理目录严格隔离，确保真实三折划分、固定测试集与人工审核记录不被虚拟数据污染（见 [DEC-003](../docs/decisions/0003-five-label-eval-scope.md) 第 6、8 条）。

## 1. 目录结构与职责

```text
data/
├── README.md                          # 本说明
│
├── # === 真实视频及其处理链路（保持既有路径不变）===
├── annotation-table-full.csv          # 110 条真实源视频标注表（video_path 指向 data/videos/...）
├── videos/                            # 真实源视频（不入 Git）
├── roi/                               # 真实 ROI（decisions.json / manifest.json 入 Git；videos/ 不入 Git）
├── split-inputs/                      # 真实来源组输入
├── splits/three-fold/                 # 真实三折划分与固定 test（含 ../dev-exclusions.json）
├── sub_video/                         # 真实子视频清单/摘要/核验（媒体按 DF-046 默认留训练机）
├── subvideo-review/                   # 真实子视频人工审核记录 reviews.json
├── eval-subsets/                      # 正式冻结评测子集（eval-dev-v1.json / eval-test-v1.json，入 Git）
│
└── virtual/                           # === 虚拟视频及其处理链路（按数据集版本隔离）===
    └── <dataset-version>/             # 如 video-V1、未来 video-V2
        ├── videos/                    # 从上游迁入的虚拟源视频（不入 Git）
        ├── labels.csv                 # 迁入的 28 列标注表（相对路径 videos/<id>.mp4，入 Git）
        ├── manifest.json              # 唯一清单：上游溯源信息 + labels.csv 与视频 SHA-256（入 Git）
        ├── roi/                       # （按需）ROI 裁剪产物
        ├── splits/                    # （按需）虚拟划分
        ├── sub_video/                 # （按需）虚拟子视频切片
        └── subvideo-review/           # （按需）虚拟子视频人工审核记录
```

## 2. 虚拟数据集导入与变更边界

- **只迁移视频与标签**：从上游 `BlenderTensileVideo/datasets/<version>/` 复制 `videos/` 与 `labels.csv`（禁止软链接），不迁移上游仿真内部档案 `metadata/`（需要时回上游仓库查阅）。
- **单一清单核验**：导入时须逐文件核对 `labels.csv` 与所有 `videos/*.mp4` 的 SHA-256，并将上游路径、上游 Git 状态与校验值合并写入 `data/virtual/<version>/manifest.json`。
- **源包只读**：`data/virtual/<version>/{videos,labels.csv,manifest.json}` 视为该版本的只读输入；如需调整源视频或源标签，应在上游发新版本后重新导入为新版本目录，不在本仓就地改写。
- **处理链路隔离**：对虚拟视频生成的 `roi/`、`splits/`、`sub_video/`、`subvideo-review/` 一律写入对应版本目录 `data/virtual/<version>/` 下，不得写入真实数据目录或混入 `data/splits/three-fold/`。

## 3. Git 与双机约定

- **入 Git**：`data/README.md`、真实侧非视频记录，以及虚拟侧 `labels.csv`、`manifest.json` 和后续处理的非视频清单/审核 JSON。
- **不入 Git**：所有视频文件（由 `.gitignore` 的 `/data/**/*.[mM][pP]4` 等规则自动忽略）及运行锁/临时文件（`.lock`、`.reviews-*`）。
- **双机同步**：源虚拟视频包体积较小时（如 `video-V1` 约 28.7 MB）可在 Mac 与训练机同时保留副本，跨机搬运后按 `manifest.json` 的 `sha256` 校验；派生子视频媒体延续 `DF-046` / `DF-048` 约定，在训练机生成并按需单向同步核验。

---

**失效条件：** 当 `data/` 顶层布局重构（例如将真实数据迁入 `data/real/`）或虚拟数据改为外部存储/新版本注册机制不再沿用 `data/virtual/<version>/` 时，须更新或废止本文档。
