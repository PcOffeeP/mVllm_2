# 可读版本控制迁移交接与验收盘点

## 2026-09-13 当前交接

当前处于 M8 整体审查和问题闭环，**尚未形成可合并候选，整体迁移未完成**。状态以
[项目 TODO](../../project-todo.md) 为准；完整审查及R2/R3修复见[验证记录第39节](verification.md#m8-audit-20260913)，R1见[第40节](verification.md#m8-r1-evidence-20260913)，R4见[第41节](verification.md#m8-r4-restore-20260913)，历史汇总与batch修正见[第42节](verification.md#m8-history-20260913)，本轮物理Prompt落位及最终复审见[第43节](verification.md#m8-final-20260913)。

Codeup 发布基线在第39节审查时经 `git ls-remote codeup refs/heads/main` 核实为 `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。
第39节当次独立审查冻结目标为任务分支 `0963642bdb47c87af0df78b809a2262ee7e1ea30`：117个提交、148个变更文件，
包含本地 main 原有的6个独有提交。审查结论为驳回修改：1项P1、3项P2；后续局部修复不等于整体通过。

| Spec 要求 | 已有证据 | 当前验收结论及余项 |
| --- | --- | --- |
| 两个数据版本保持身份、内容与生命周期 | verification 第20–24节真实复制、20个payload验签、外部媒体引用核对；第39节复算源manifest | 复制迁移完成；本轮未重扫完整payload，媒体仍依赖原根 |
| 当前Prompt迁移，旧引用保留 | 第27节原文逐字段一致；第39节新旧文件SHA复查 | **迁移完成**：第43节已通过公开create将相同1200字节定义登记到`/data/mVllm_2/records/prompts/prompt-v4.1-r1.yaml`；标准show和重复拒绝通过，原源/指针/两data凭证保持。外部媒体及模型输入仍需显式提供 |
| 历史模型、参数和已有指标可查询 | [history-summary.yaml](history-summary.yaml)；第42节原工作区stat、47份轻量源验签与独立核查 | **本轮交付完成**：21条、234已知/152未知；源root、原ID、参数、指标口径和缺失原因可查。权重内容未重验、报告声明未重算；简明历史不等于正式可执行身份 |
| 七阶段数据及人工审查语义 | 第12–24节真实2个source、34候选、23条旧审批精确复用及11条普通自动通过 | M3完成；不代表全量新数据重建或新人工审批 |
| 三折实际训练、测评事实 | 第25–31节执行器、1678视频准备dry-run和CPU故障路径 | 接线及限定验证完成；**M8-R1**代码3b63aa52与独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；**full/holdout实际输入未接线（实现缺口）**；GPU训练/真实评分未执行（独立验证缺口） |
| 严格alias及实际服务入口 | 第32节实际服务调用和拒绝路径 | 入口切换完成；M8-R1实际证据门已修复，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；**M8-R5新发现P2**：当前concise Prompt即使合法candidate也被固定服务契约拒绝；同ID当前定义漂移为固定契约反而放行。须绑定训练/eval冻结内容并裁决兼容策略；真实模型加载/推理成功也未验证 |
| 不覆盖及同操作失败恢复 | M1/M3/M6故障测试；第39节Prompt并发和训练完成半提交回归 | M8-R2/R3本轮修复与复审结果见第39节；不将该局部修复扩大为所有故障窗口已验证 |
| 隔离备份恢复 | 第33节SSH小对象往返；第41节Mac/Linux异根恢复 | **M8-R4本轮范围已解决**（2fce3ab1）：原模拟store不可访问时读取/写入新根、显式current与服务准入、再次备份均通过。只重定位活动地址，冻结事实/外部引用保留；真实移动硬盘、大型产物及外部依赖整机恢复未验收 |
| 全部活动入口接管、完整差异审查 | 第34–38节M7a–e；entrypoint-map；第39节整体审查 | M7切片已有双机证据，M8整体尚未通过；旧低层库保留不等于允许旧公共写入 |

本轮M8-R1已覆盖公开手工写入及已有无证据记录，冻结训练基座并校验被评路径与服务deploy_target一致；本机2623 passed/11 skipped、独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决。
本轮M8-R4代码2fce3ab1：Mac受影响回归175 passed/1 skipped、最后URI专项6 passed；Linux最终181 passed/1 skipped，exit0，独立代码/操作文档局部审查通过。实际历史汇总现已完成，第42节另记录公共历史生成器batch口径修复d2ae4cee、Mac/Linux各247项与独立15项。物理/data下Prompt已落位并验证（第43节）；当前最终复审范围更新为f1b7d8a3→ab5c71ae，125提交/149文件。新增M8-R5服务Prompt冻结输入绑定P2；完整性门可先修复，兼容策略待裁决；full/holdout实际输入接线另行推进。独立完整代码复审已完成，结论为整包驳回修改；Mac最终整仓2647 passed/11 skipped，452.07秒，正常exit0；skip为本机历史数据缺失。四份交付文档同步当前结论（第43节）。
所有修复继续沿已确认Spec，不得以放宽门禁或把未知历史事实补成passed来关闭条目。

第39节只读核对：训练机原项目 `main@f1b7d8a3` 干净；隔离checkout在当时审查时为 `0963642b`，
原有环境和验证目录均保留。前轮R2/R3代码`2b8cbc89`通过bundle同步，Mac/Linux各466项及独立251项通过。
本轮R1代码`3b63aa52`已同步到隔离分支，原正式项目仍为干净main@f1b7d8a3；Linux分三进程956 passed/1 skipped、各exit0，验收结果见第40节。
本轮R4代码`2fce3ab1`也已同步隔离分支；原正式项目保持只读。Linux回归与恢复边界见第41节。
当前轻量证据提交由相关文件`git log`追溯，不能把审查冻结目标或修复提交冒充最终整包通过版本。
拟合并目标仍为 Codeup `main`。尚未请求或执行merge/push；需问题闭环、更新完整差异和两端Git状态后再提出具体请求。
下文保留M3授权执行单及当时事实，**其状态、路径存在性及“待推进”表述均为历史快照**，不得覆盖本节当前盘点。

---

# M3 训练机验收执行单（2026-09-12历史记录）

本记录区分已完成的只读准备和待授权的写入动作。代码/测试实施状态以
[项目 TODO](../../project-todo.md) 和 [验证记录](verification.md) 为准。
2026-09-12 用户对本单明确回复“确认”，已批准下列隔离同步、新 CPU 环境、小样本验证、Mac 审查回传与两份 release 复制迁移。该授权持续有效；不包含 push/merge、模型训练/GPU/完整评测或改写旧正式产物。

## 2026-09-12 执行前只读核对（下列为历史快照）

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

## 已授权动作的精确范围（执行结果另记 verification）

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

## 执行状态（2026-09-12，来源见 verification 第20节）

隔离同步、新CPU环境、两段development真实媒体与旧算法逐字节对照、两份正式release复制已完成并经独立核查。r1/r2为声明的superseded/active状态；旧源与活动指针不变。外部媒体仍从原workspace/data根解析，新store镜像不包含全部视频/帧。

用户已明确确认历史审批均由本人完成，并批准默认记录“项目维护者”。23条媒体/帧/标签/时间戳精确匹配的旧审批保留原审查时间复用，原匿名记录与来源保存独立确认文件；11条普通未断裂保持自动准入。Mac真实UI已冻结23完成/0待审的回收包，训练机已完成review_import、隔离开发发布及release_validate（34样本、257文件），并通过独立核查。不是新的视觉人工复审，不改写原历史发布。Mac完整1772项正常退出，Linux专项5项及最终公共发布校验通过，独立核查通过；M3已完成，详见verification第23–24节。M4–M8尚未实施，整体迁移未完成。本执行单授权持续有效，不再重复确认。
