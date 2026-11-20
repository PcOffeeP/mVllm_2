# 本轮源视频划分结果

**2026-11-07 已生成并核验三折划分。** 测试集 21 个视频保持原样；89 个开发视频全部各进入一次验证集。2026-11-08 已按用户授权将当前结果精简到 [data/splits/three-fold](../../data/splits/three-fold/)，本次只整理文件，不重新运行划分搜索；迁移和 ROI 扫描的历史验证结果见下文。三折于 2026-11-19 重跑，当前人数 59／30、59／30、60／29，见「2026-11-19 三折重跑」。

按照已确认的规则，实际搜索完成 **100 个起点**（seed 42–141），选中本次候选中评分最好的 seed 53；manifest 的 `search_summary.best_score.coverage_gap` 为 0，`config.objective_order` 第一项为 `coverage_gap`。这个结果不代表数学上的全局最优，也不证明模型效果提升。

## 输入和来源

- 当次生成使用的标注表：[data/annotation-table-full.csv](../../data/annotation-table-full.csv)，110 条源视频。2026-11-07 搜索实际使用的 CSV 字节 SHA-256 为 `9970d259e14e6321eea76282b6a206b5b907527101736fe28d3c437387fa8d81`；其后术语统一（三列单选的不确定值由“无法确定”改为“无法判断”）改变了文件字节，但未改变任何 ID、成员或标签含义，当时划分成员文件未重新生成、未改变。2026-11-19 源表 6 处字段变更后，当前该文件的 SHA-256 为 `c928bea3d769eb16ad55ed7d872a877a3b4fd327d0af5422bc2bb682c1ec354c`；重跑输入即此字节，与 manifest `inputs.labels.csv.sha256` 一致。
- 用户确认 110 个视频分别来自独立试验；本轮据此将每个视频作为一个来源组。本次整理已将来源组恢复到稳定输入位置 [data/split-inputs/source-groups-20261107.json](../../data/split-inputs/source-groups-20261107.json)，并在 2026-11-08 核验与原 `input_groups.json` 字节一致，避免删除结果目录中的输入快照后丢失必需输入。
- 对 110 个视频进行了路径和文件 SHA-256 检查，未发现字节完全相同的文件。**不同哈希不能排除近似素材，也不能独立证明试验来源。** 模拟视频不在此次 110 个真实视频的输入内，其来源关系未在本次发布中核验。
- 旧七份划分清单的指纹均与[划分设计](data-split-design.md)记录一致；新 `test.json` 与旧文件字节完全一致。测试集已有历史使用记录，本次没有运行模型测评或用模型结果选划分。

## 三折结果

| 折 | 训练源视频 | 验证源视频 | 对应文件 |
| --- | ---: | ---: | --- |
| 0 | 59 | 30 | [训练成员](../../data/splits/three-fold/fold_0_train.json) · [验证成员](../../data/splits/three-fold/fold_0_val.json) |
| 1 | 59 | 30 | [训练成员](../../data/splits/three-fold/fold_1_train.json) · [验证成员](../../data/splits/three-fold/fold_1_val.json) |
| 2 | 60 | 29 | [训练成员](../../data/splits/three-fold/fold_2_train.json) · [验证成员](../../data/splits/three-fold/fold_2_val.json) |

[测试成员](../../data/splits/three-fold/test.json)共 21 条。当前输出仅保留 7 份成员 JSON 和 `manifest.json`；完整标注由上游标注表维护，不再默认复制成 7 份划分 CSV。整理不复制或重新编码视频。

2026-11-07 独立核查当时确认（重跑后现状见下文新章节）：每折 train／val 不交叉、并集均为同一批 89 个开发 ID，与 test 不交叉；每个开发 ID 恰好进入一折 val。当时也核对了划分 CSV 与 JSON、输入标注表的一致性。CSV 和旧折移动记录按本次精简方案删除，该项是历史验证记录，不表示对应明细文件仍在当前目录。

## 稀有标签仍有哪些限制

| 开发集标签 | 独立来源数 | 三折 val 正例数（0／1／2） | 三折 train 正例数（0／1／2） |
| --- | ---: | --- | --- |
| 未夹紧 | 1 | 0／1／0 | 1／0／1 |
| 爆炸性断裂 | 1 | 0／0／1 | 1／1／0 |
| 开裂 | 3 | 1／1／1 | 2／2／2 |
| 断后脱夹 | 3 | 1／1／1 | 2／2／2 |

manifest 的 `search_summary.best_score.coverage_gap` 为 0，`config.objective_order` 首项是 `coverage_gap`；按已确认规则：只有 1 个来源的标签**不要求三折都出现**，没有来源的标签也不能靠划分制造出来。因此它不意味着每个标签在每一折都有正例，更不能表示类别表现稳定。固定 test 中未夹紧、爆炸性断裂、开裂均无正例；这些缺口不能靠重排开发集解决。

## 历史搜索与本次整理

- 2026-11-07 搜索完成 100 个起点，检查 676,465 个邻居，接受 4,713 次改进；当次选定的三折验证人数为 29／30／30，已由 2026-11-19 重跑的 30／30／29 替代。原生成代码提交为 `bf253b2b440e434e259b9c40143de36b7ddceacf`。
- 原完整结果曾独立核查 12 项输入快照、30 项输出的哈希与结构；原 manifest SHA-256 为 `462c1fac05eebb65628e274f0582d0e2d9af9a3b0b4f2920703be7361d9ab104`。这些数字记录当次核查范围，不是当前精简目录的文件数量或 manifest 身份。
- 用户确认本次删除输入快照、划分 CSV、独立分析报告和完整搜索轨迹，不保留历史归档。删除后无法仅凭哈希恢复这些原文件，也不能把本页历史概述当作仍可逐项重查的完整搜索证据。
- 2026-11-08 的 manifest 记录了精简目录成员摘要及原生成身份；当前 [manifest.json](../../data/splits/three-fold/manifest.json) 已因 2026-11-19 重跑更新。
- 原生成器的 28 项合成测试及独立代码审查是历史检查记录；本次修改后的测试结果另行记录。合成检查和成员一致性检查不能代替近似素材去重、片段标签复核、训练或模型评价。
- 当前标注表、来源分组、八份划分结果文件及 ROI 非视频记录按用户要求纳入 Git 管理，视频继续忽略；本地版本记录不代表已推送或已建立独立备份。本次不运行模型测评，也不以模型结果选划分。

## 2026-11-08 整理与 ROI 衔接验证

2026-11-08 迁移当时先核对原 manifest 中 30 项输出的摘要，再将结果目录改为 `data/splits/three-fold/`。七份成员 JSON 与迁移前基准逐字节、逐 ID 一致；110 条标注和来源分组覆盖核对通过，21 个 test 与 89 个开发成员不交叉，各折 train／val 互斥且每个开发成员恰好验证一次。当时未重新运行划分搜索，没有重新生成视频。此结论现已由 2026-11-19 重跑替代，七份中只有 test.json 仍相同。

2026-11-08 来源组恢复后 SHA-256 为 `ce96febf1a41a15a4ecc9eba0e1256ebc5c7105f15c01c22afbca80130dde28b`，当时与原输入快照一致。当前 SHA-256 为 `a640cd71746f508f9e904208a699b68391b54c2c5c0acb9a9ced19b0c46adaa7`（10983 字节）；2026-11-19 重标注时 `provenance.label_csv_sha256` 随之更新，分组内容未变。原目录多余的 23 个文件已删除，当前目录共 8 个文件，不保留单独归档。

下表六个折指纹现为 manifest `inputs.old_fold_*` 的重跑前快照；七份中仅 test.json 与当前相同。

| 成员文件 | 2026-11-08 迁移时的 SHA-256（已被重跑替代） |
| --- | --- |
| `fold_0_train.json` | `73abf0f28a3d06b09aa0aabcefd31451bce1b32bba51f7d8356d8c7440ca0421` |
| `fold_0_val.json` | `026410713000db8b3ada0e93c6af63e3e7bc9767aebdf73e490672002c005d34` |
| `fold_1_train.json` | `991229766e2a2ad74ec4298e195937c4fb9ee130d232875ab276ca65f7e2d2a3` |
| `fold_1_val.json` | `61f4e41345bdd5f18c685411aef37800cf8b42b6590ca11b6772252c9da53ab3` |
| `fold_2_train.json` | `a1467c8ed7332473425a73a832a6bf26cf37c76185e52e1b29a118546af0cfc7` |
| `fold_2_val.json` | `cecc8d653ec44bef5e81821d2fee87a3221fd287c7f5c17d644cafaa51ef436c` |
| `test.json` | `26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc` |

本次生成器合成测试实际执行 `.venv/bin/python -m pytest -q script/data_split/tests --basetemp=/tmp/tensile-split-output-tests-implementation`，结果为 **40 passed in 2.72s**，包含输出精简前后七成员文件的字节回归；该检查未重划当前真实数据。

2026-11-08 当时实际执行 `.venv/bin/python script/roi/roi.py --splits-dir data/splits/three-fold --scan`，退出码为 0。ROI 清单当时记录的新划分路径及七个文件摘要正确，110 个视频均为 `success`，逐视频划分归属与当时成员清单一致。当时扫描更新 `data/roi/manifest.json`，未执行 ROI 视频生成；`success` 只表示媒体可用，不表示人工画面审核完成。已于 2026-11-20 按当前划分与重标注后的标注重扫，结果见「2026-11-19 三折重跑」节。

## 2026-11-19 三折重跑

源表在提交 `51d647d` 有六处字段人工修改：`video_0021` 断裂模式无法判断→韧性断裂；`video_0026` 异常_爆炸性断裂是→否；`video_0040` 断裂模式脆性断裂→半脆半韧断裂、标注备注空→“出现一个跳转，跳转能看到明显的视角伸长。”、现象_伸长否→是；`video_0050` 断裂模式韧性断裂→无法判断。四个 ID 均属开发集，不在 test。据此重跑开发三折，test 未动。

manifest SHA-256 为 `1ad84afb9a9eb122d6d7cdc13b78a975567a51667eaeacfabd5748c1055f6ae2`（8394 字节）；`code_commit` 为 `51d647d02a6c208ea0d8715a1351ba42c36a7adb`，`rule_version` 为 `explicit-source-five-task-v1`，`status` 为 `generated_split_not_model_evaluation`，`manual_exceptions` 为 `[]`。`warnings` 三条为：

- `explicit_source_table_is_user_evidence_not_media_deduplication`
- `historically_exposed_test_is_not_never_used_independent_test`
- `bounded_local_search_does_not_prove_global_optimality`

搜索 100 个起点（seed 42–141），`best_seed` 为 53，`search_summary.best_score.coverage_gap` 为 0；`global_optimality_proven` 为 false，`test_labels_used_for_objective` 为 false，不证明全局最优。三折 train／val 为 59／30、59／30、60／29，test 为 21；每折 train∩val 为空，train∪val 均为同一批 89 个开发 ID，与 test 不交叉，每个开发 ID 恰进入一次 val。

换折开发视频 40 条。旧折→新折人数矩阵（行旧 0／1／2，列新 0／1／2）为 `[18,7,4]／[10,13,7]／[2,10,18]`；各折 val 对称差 23／34／23，val 新增 12／17／11。test 625 字节，与 `git show 51d647d:data/splits/three-fold/test.json` 逐字节相同。

| 当前输入或成员 | SHA-256 | 字节 |
| --- | --- | ---: |
| `data/annotation-table-full.csv` | `c928bea3d769eb16ad55ed7d872a877a3b4fd327d0af5422bc2bb682c1ec354c` | 22458 |
| `data/split-inputs/source-groups-20261107.json` | `a640cd71746f508f9e904208a699b68391b54c2c5c0acb9a9ced19b0c46adaa7` | 10983 |
| `fold_0_train.json` | `9145833a4bc4722598ee133623f5dc96b8a0c9e83d1e53107d88afcd3495d529` | 1199 |
| `fold_0_val.json` | `15341b97c0d26302644f7b17b39e1a9c8616f9e0b391c87a17c9165e6dd18206` | 675 |
| `fold_1_train.json` | `daf6116c2beb6a1e7aa9e41144197b6f7736c13956f3557780db0386526ed338` | 1199 |
| `fold_1_val.json` | `77e278e6c419bf24d6dea3d4432b1d2c8ee926776dce64736f2ab15bd04f5a27` | 675 |
| `fold_2_train.json` | `47bbe6680e5e2ed4fe5f2b9c96cbb745f76e54fbcf3231e32740f12c47cb6491` | 1217 |
| `fold_2_val.json` | `77cf740c93cc9848b6c48e9dfa93f2f430ff636a9502f05780c859464836f9fb` | 657 |
| `test.json` | `26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc` | 625 |

成员文件位于 `data/splits/three-fold/`。CSV 共 111 行（含表头），全 CRLF，UTF-8 BOM；来源组 `provenance.label_csv_sha256` 等于当前 CSV 摘要。

| 开发集标签 | 独立来源数 | val 0／1／2 | train 0／1／2 |
| --- | ---: | --- | --- |
| 未夹紧 | 1 | 0／1／0 | 1／0／1 |
| 爆炸性断裂 | 1 | 0／0／1 | 1／1／0 |
| 开裂 | 3 | 1／1／1 | 2／2／2 |
| 断后脱夹 | 3 | 1／1／1 | 2／2／2 |

正例按取值恰为“是”计；110 个来源组各含一个视频。爆炸性断裂从 2 降到 1，因 `video_0026` 由是改否；唯一正例 `video_0040` 位于 fold 2 val，未夹紧正例 `video_0002` 位于 fold 1 val。

### 2026-11-20 ROI 清单重扫

本机执行 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python script/roi/roi.py --splits-dir data/splits/three-fold --scan`，退出码 0，输出 `{"total":110,"summary":{"success":110},"complete":true}`。新 `data/roi/manifest.json` SHA-256 为 `24b2dfa3019462dbef27fc00314901d30ad308802a458b31d95a90e4dc6948b3`，1,453,938 字节，`generated_at` 为 `2026-11-20T02:31:08.422369+00:00`；旧清单 SHA-256 为 `de202f2091d00acf34b4e6a3a774cb3fc410ff203b841e1aa1ab6a1a893a2ad8`，1,453,872 字节，`generated_at` 为 `2026-11-08T13:20:20.164007+00:00`，仓库外备份为 `~/pi-workspace/tensile-finetune/backup/roi-manifest-20261120-1029.json`。

扫后 `split_input.files` 的 7/7 摘要与当前磁盘一致；逐视频 `split.folds`／`partition` 110/110 与划分一致、0 处不符，`labels` 110/110 与当前 CSV 一致、0 处不符。值变化仅涉及 `generated_at`、`split_input.files[*].sha256` 6 条、`split.folds.{0,1,2}` 23／34／23 条，以及 `labels` 的断裂模式 17 条、断裂状态 16 条、断裂位置 13 条、异常_爆炸性断裂 1 条、标注备注 1 条、现象_伸长 1 条；顶层与逐视频键集合无增删，`output` 全部不变。重扫还同步了 15 条早于术语统一的断裂模式旧值「无法确定」；刷新后清单与 CSV 的断裂模式分布一致：脆性 20、半脆半韧 21、无法判断 15、韧性 50、无 4。

副作用核对：`data/roi/decisions.json` SHA-256 前后均为 `58cbb6ca8d086fda1c34d27b4c9ca4c7ac3bb139304115ddf2779192ea4a9e74`；`data/roi` 文件数 113→113，`data/roi/videos` mp4 110→110，磁盘占用 148488 KiB 不变，未生成或删除媒体。ROI 回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q script/roi/tests` 为 181 passed。本次未核对 ROI 视频内容正确性、逐帧解码或复算输出媒体 SHA；`success` 不表示人工画面审核完成。本轮未运行模型测评。

**ROI 重扫结论失效条件：** 本结论只对应 `data/roi/manifest.json` 的 `generated_at` `2026-11-20T02:31:08.422369+00:00`；标注表或 `data/splits/three-fold/` 任一文件变更后即失效，须重扫。

**失效条件：** 标注表、视频身份、来源关系、原测试成员、划分规则或结果文件改变后，须重新核对对应身份和受影响结果；新划分替代本版本时，本记录作为历史结果保留。
