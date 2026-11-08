# 视频 ROI 查看与裁剪

在项目根目录启动：

```bash
.venv/bin/python script/roi/roi.py
```

macOS 也可双击本目录的 `run_roi.command`。启动器优先使用项目 `.venv/bin/python`，否则使用 `python3`。需要 Python 3.10 及以上、PATH 中可用的 `ffmpeg` 和 `ffprobe`。界面依赖安装命令：

```bash
python3 -m pip install -r script/roi/requirements.txt
```

## 直接查看已有结果

工作列表覆盖全部源视频，不按训练、验证或测试划分筛选。对应的旧 ROI 视频在来源摘要、输出摘要和清单信息核对一致后直接显示为 **ROI 可用**，保持原文件内容，不会为了满足新裁剪命令而重新编码。

选择视频即可查看 ROI 结果。标签直接读取已有标注，只读显示；无需逐项选择标签，也无需为每个视频点击“通过”。“ROI 可用”和全量 `complete` 仅表示媒体结果已提供，**不表示已完成人工画面审核**。按需查看，有问题再调整范围即可。

旧记录中的请求框可能经过当时 FFmpeg 的色度对齐。处理清单分别记录旧请求范围与可还原的实际边界，不把旧像素位置改写成当前精确框。无法可靠还原时明确标记几何不确定，旧文件仍按其来源和摘要保留，供直接观看。

## 有问题时调整，新视频正常选框

1. 已有 ROI 需要修改时，展开“需要调整裁剪范围”。没有可用结果的新视频直接显示设置范围。
2. 播放原视频，按需拖动预览位置。选择固定 3:4 框或全画面补边；拖框后点“采用当前拖框”，查看最终像素范围。也可输入精确坐标。
3. 点“保存范围并生成 ROI”。工具保存当前范围，再生成新结果并核对实际帧数、时长、分辨率、方向和解码；生成后即可查看，无需逐项审核标签。

尚未处理完时，可填写备注并“保存选框进度”。草稿不替代已经可用的旧结果，只有明确保存的新范围才会生效。原标注表、原视频、旧视频及已有审核记录均保留。保存范围时，备注和此前草稿也会归档，便于继续查看。

旧输出来源摘要与当前视频不同时，不会直接采用该旧输出。界面会保留旧决定作为参考，请针对当前视频保存范围并生成。视频缺失、ID 冲突、方向不明或划分冲突会明确列出，不因为文件消失而误报全量完成。

## 默认输入与输出

所有相对路径按项目根目录解析，与执行命令时的当前目录无关。

| 输入或输出 | 默认路径／行为 | 可选参数 |
| --- | --- | --- |
| 源视频 | `data/videos/`，递归读取，文件名去扩展名作为唯一 ID | `--videos-dir` |
| 已有标注 | `data/annotation-table-full.csv`，可缺失，只读 | `--labels` |
| 旧决定 | `data/roi/imports/roi_decisions.legacy.json`，可缺失 | `--decisions` |
| 旧结果清单 | `data/roi/imports/media-manifest.legacy.json`，可缺失 | `--existing-manifest` |
| 旧视频 | `data/roi/imports/media/<视频ID>.mp4`，可缺失 | `--existing-media-dir` |
| 输出目录 | `data/roi/` | `--output-dir` |
| 划分记录 | `data/splits/` 下唯一可识别版本自动读取；多个版本须选择 | `--splits-dir` |
| 项目根目录 | 按脚本位置定位 | `--project-root` |

例如处理新视频目录：

```bash
.venv/bin/python script/roi/roi.py --videos-dir data/new-videos --output-dir data/new-roi
```

支持 `.mp4`、`.mov`、`.mkv`、`.avi`、`.m4v`、`.webm`，大小写均可。相同文件名对应多个路径时记录 ID 冲突。浏览器能否播放取决于封装与编码；无法播放原视频时，可用外部播放器对照，界面单帧预览仍可辅助选框。

旧决定文件包含 `decisions` 数组，每条以 `source_video_id`、`source_sha256`、`source_resolution`、`mode` 和 `pixel_box` 绑定原视频及范围。旧清单包含 `videos` 数组，每条须有来源与输出的完整摘要、处理方式，以及与实际媒体一致的输出分辨率；帧率与时长如有记录也会核对。仅凭文件名不会认领旧视频。

```text
data/roi/
├── imports/                        # 旧材料，只读；可直接作为现有ROI结果使用
├── drafts.json                     # 尚未保存生效的选框进度
├── decisions.json                  # 用户明确保存的新范围
├── manifest.json                   # 全量身份、原标注、划分、结果与处理状态
├── batch-errors.json               # 最近一次有错误的批处理记录
└── media/<视频ID>/<处理摘要>.mp4     # 按新范围生成的结果
```

清单保留源视频和输出摘要、媒体信息、旧请求框与实际边界、原有审核及草稿、历次输出。`origin=preserved_legacy` 表示沿用旧视频，`origin=generated` 表示按新范围生成，`origin=imported_generated` 表示接入其他机器按当前源及范围生成并通过检查的结果；`visual_review.required=false` 说明不强制逐视频确认，`status=not_recorded` 不应解释为已被人工看过。

| 状态 | 含义 |
| --- | --- |
| `success` | ROI 媒体可用，可以直接查看 |
| `ready` | 已有画面范围，等待生成 |
| `needs_decision` | 尚无适用范围，或旧范围绑定其他源视频 |
| `needs_verification` | 方向或划分存在待核实问题 |
| `failed` | 输入缺失、摘要不符或处理失败，原因保留 |

划分只读继承 `test.json`、`fold_N_train.json` 和 `fold_N_val.json` 的 `video_ids`；开发集逐折记录 train/val，新视频没有划分不阻塞。测试集产物仍遵守其访问约束。每个源视频只保留一份对应结果，不因三折重复处理。

## 无界面使用

核对输入、连接可用旧结果并写工作清单，不生成视频：

```bash
.venv/bin/python script/roi/roi.py --scan
```

生成所有已保存画面范围、状态为 `ready` 的条目：

```bash
.venv/bin/python script/roi/roi.py --batch
```

退出码 `0` 表示扫描完成，或批处理后全部 ROI 可用；`2` 表示仍有待处理项；`1` 表示配置、读取或生成错误。`complete` 不表示人工复核完成，也不表示源标签已被重新评价。

首次列表扫描计算来源和旧结果摘要并读取媒体头信息，后续未变化文件使用状态缓存；处理前针对当前视频重新核对摘要。旧结果沿用不会自动执行整批完整解码，清单如实记录 `full_decode=not_performed`。新生成时针对当前源与输出实际计帧，并缓存与源摘要绑定的计数，避免误用不可靠的文件头帧数。新输出还执行完整解码检查。

新生成采用 H.264、`fast`、CRF 23、`yuv420p`、去音频。固定框使用精确坐标，全画面补边先转 4:4:4 后居中补边，以保证实际位置与记录相同。媒体检查不能证明画面细节无损，查看时发现问题再调整。完整批量编码及长视频处理应在训练机运行。

测试命令：

```bash
.venv/bin/python -m pytest -q script/roi/tests
```

**失效条件：**入口、默认路径、记录格式、结果采用方式、裁剪或媒体验收发生变化时更新本说明；规则或处理身份变化后重新判定受影响结果，不覆盖原视频、标注或旧结果。
