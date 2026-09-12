# M3 训练机验收执行单

本记录区分已完成的只读准备和待授权的写入动作。代码/测试实施状态以
[项目 TODO](../../project-todo.md) 和 [验证记录](verification.md) 为准。
本单不是额外授权；真实迁移、后续远程同步/环境写入仍须用户明确批准。

## 2026-09-12 只读核对

- 训练机 `liuyang@100.70.83.68`；正式项目 `/home/liuyang/文档/mVllm_2`，
  `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，工作区干净。
- 既有隔离项目 `/home/liuyang/文档/mVllm_2-migration-7eeb93a7`，
  任务分支 `refactor/2026-09-07-readable-version-control-migration@2027c4dc14753971bf499d9b65ede6bbf650222f`，
  仅 `.conda-m2/` 未跟踪。没有修改、同步或停止远程进程。
- `/data/mVllm_2` 为普通空目录，剩余空间约 3.74 TB；未创建正式 store 内容。
- `.conda-m2` 有 DVC 3.67.1、pandas 3.0.3、Pillow 12.3.0；缺 Torch、Transformers、PyAV。
  `/usr/bin/ffmpeg` 与 `/usr/bin/ffprobe` 存在。旧环境保持不变。
- 实际模型目录是 `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`，为普通目录；
  `models/minicpm_v_4_5` 是指向它的 legacy 链接，`models/minicpm-v-4.5` 不存在。
  新 inputs 必须声明普通目录，不使用该链接。处理器配置、Python 模块和 tokenizer 文件已只读列明，未读取模型权重。
- 两份 legacy release manifest 的当前 SHA 与 M0 相同：
  `760050fad303` → `c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`；
  `ecb5aeb9657c` → `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`。
  本轮仅复算 manifest，完整 payload 的前次验证不能写成本轮复跑。

## 待授权动作的精确范围

1. 本机全部 M3 提交通过完整测试后，以 Git 增量 bundle（基线 `2027c4dc`）传到训练机；
   校验 bundle SHA、`git bundle verify`、两端 branch/HEAD/status 后，仅快进上述隔离任务分支。
   不 push、不合并 main、不覆盖 tracked/untracked 修改。执行时把最终提交和 bundle SHA 补入 verification。
2. 在隔离项目新建 `.venv-m3/`，以 `.conda-m2/bin/python -m venv --system-site-packages` 创建独立环境，
   仅向新环境添加 CPU Torch 2.5.1 / torchvision 0.20.1、Transformers 4.56.1、PyAV（遵守项目约束）
   及其必要依赖。CPU wheel 源为 PyTorch 官方索引；不改 `.conda-m2`、系统环境或正式项目。
   运行时 `CUDA_VISIBLE_DEVICES` 为空；不加载模型权重、不运行模型推理/训练/完整评测。
3. 在隔离项目新建 `m3-verification-20260912/`，其中 `inputs/` 存显式小样本配置，
   `store/` 是非正式 DVC store，`comparison/` 存旧算法对照和报告，`review_return.json` 为包外回收输入。
   两个新目录在本轮只读检查时均不存在；执行前再核对，冲突时停止，不清理同名目录。
4. 仅使用下节两段 development 视频，生成 source→ROI→子视频→审查导出；不动 test 数据。
   将完整审查包复制到 Mac 的任务临时目录，运行显式 `--versioning-package` 界面并完成回传验证。
   没有真实人工决定时不能由 Agent 伪造；若复用旧决定，必须逐条证明媒体 SHA、实际采样帧、建议标签
   与原审查对象完全相同，并保留实际审查者和时间。无法复用的候选交实际审查者处理。
5. 仅按已确认映射登记两份 legacy release：
   `/data/mVllm_2/data/releases/data-v4.1-r1/` 为 superseded，replacement=`data-v4.1-r2`；
   `/data/mVllm_2/data/releases/data-v4.1-r2/` 为 active。不得重跑数据构建替代复制迁移。
   源仍为正式项目下 `workspace/data/releases/v4.1.0-{760050fad303,ecb5aeb9657c}`，
   只读取这两份对象及 `finetune/active_data_release.json`，不扫描 sibling 或改变活动指针。

## 非正式小样本输入与对照

| source | 既有范围与类别 | 字节数 | 原视频 SHA-256 |
| --- | --- | --- | --- |
| `video_0003` | fold_0_train，脆性断裂 | 5,827,018 | `efb2ba8f01e992fdf8e883d48f99e34f331e1ce2b2dec06bd30d3962439f8634` |
| `video_0011` | fold_0_train，韧性断裂 | 2,751,847 | `f5efe80167cc56d04c1a80b7e682db6a71441477e6e8b060cee2d6aabe30b6b2` |

- 视频实际路径为正式项目 `workspace/data/source/videos/<id>.mp4`。本轮已复算上述原视频字节摘要，
  与既有 ROI 决定的 source_sha256 一致；合计约 8.58 MB，时长约 45.6 秒。
- 注释来自 `workspace/data/source/annotations/{all_videos_tag.csv,video_mapping.csv}`，
  小样本只提取这两行，原 CSV 不修改。split 从现有七份 `workspace/data/source/splits/*.json`
  按这两个 ID 取交集，保留其每 fold 归属，不重新随机划分。
- ROI 从 `workspace/data/derived/metadata/roi_decisions.json` 提取两条已批准记录；
  保留几何/可见性/原始 SHA/审查时间，只在输入副本中把历史 `data/01_videos/...` 路径显式映射到
  现存普通文件路径，并在 comparison 记录该路径变换及原决定文件摘要，不能修改旧人工记录。
- 历史参考仅读 `workspace/data/derived/metadata/v3/review_reference/review-ref-7cd2e73a1cd1/`
  下 `development_reference.json`，按两 source 同步过滤 records、source_inventory、source_consensus，
  保持原 reference_id 和这两 source 的参考内容。直接用同一 reference_id 构造显式空 test 参考，
  records/source_inventory/source_consensus 均为空；此步骤不打开 `test_reference_audit.json`。
- `project_root` 可显式设为共同父目录 `/home/liuyang/文档`，从而同时引用普通模型/原视频与隔离输入副本，
  不在正式 checkout 写配置，也不使用软链接。所有 pin 路径仍须位于该根内。
- 预处理器 pin 清单只选实际模型目录的处理代码、配置和 tokenizer 所需文件；不包含权重分片。
  固定8帧、video_fps=2；fingerprint 由该普通模型路径与实际配置计算，不能复制旧报告当运行成功。
- ROI 几何/时间轴、候选数量及窗口/标签、剪辑帧数、实际采样映射/门禁逐条与原业务算法对照；
  本机已确认这些业务模块相对训练机正式 `f1b7d8a3` 无代码差异。对照执行的产物放 comparison，
  不调用 legacy 哈希发布器或改动任何旧集合索引。
- 预计媒体对照 CPU 数分钟至20分钟，新增样本/帧/报告预算1 GiB；安装依赖另需数 GiB与网络下载时间。
  达到预算或出现 source/配置漂移即停止，保留报告，不扩大到全量视频。

## 正式复制迁移的前置与证明

当前转换器的 `--root` 同时定位声明 legacy 源和目标 store。为保持正式 checkout 不变，
在写入获批后，将仅这两份 legacy release 的受验 manifest/声明 payload 及活动指针复制为
`/data/mVllm_2/workspace/data/releases/<旧ID>/` 和 `/data/mVllm_2/finetune/active_data_release.json`
的输入镜像；这是本次转换的来源副本，不是活动 legacy 集合或新版本身份。源副本必须再次完整验签，
并记录其真实来源路径；原文件保持不变。两份已声明 payload 合计23,563,409字节，另有少量manifest，
迁移本身约需再一份相同体量；这不包含旧 JSON 外部引用的全部视频。

从隔离代码目录，用已提交的 `object-mapping.yaml` 和显式 root 运行：

```sh
"$PYTHON" -m versioning migration data-precheck --root /data/mVllm_2 \
  --mapping docs/results/version-control-migration/object-mapping.yaml
"$PYTHON" -m versioning migration data-migrate --root /data/mVllm_2 \
  --mapping docs/results/version-control-migration/object-mapping.yaml
```

只有 precheck 全部 ready 才能开始复制；转换完成后按 receipt 校验两对象、逐文件 SHA、
sample_count/split/source_batches 和 r1/r2 生命周期。外部视频引用保持原语义，需另记录可达性，
不能宣称 payload 已自包含全部旧视频。r1 superseded 的新训练引用应被拒绝；r2 的元数据与
封存可验证不代表模型训练效果。保留 receipt 和输入镜像，不删除源、改旧指针或生成假质量结论。

如果实际文件/空间/清单与本记录不一致，停在该前置并更新证据；不以本机测试通过代替这些检查。
