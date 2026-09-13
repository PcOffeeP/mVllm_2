# 可读版本控制迁移交接与验收盘点

## 2026-09-13 当前交接

当前 M8 更新后的整包代码差异审查已通过；**真实环境验收和集成授权仍未完成，整体迁移未完成**。状态以
[项目 TODO](../../project-todo.md) 为准；完整审查及R2/R3修复见[验证记录第39节](verification.md#m8-audit-20260913)，R1见[第40节](verification.md#m8-r1-evidence-20260913)，R4见[第41节](verification.md#m8-r4-restore-20260913)，历史汇总与batch修正见[第42节](verification.md#m8-history-20260913)，物理Prompt落位及历史复审见[第43节](verification.md#m8-final-20260913)，R5修复见[第44节](verification.md#m8-r5-prompt-20260913)，full/holdout实际接线见[第45节](verification.md#m4-full-holdout-20260913)，当前R6/R7与更新后的整包代码审查结论见[第47节](verification.md#m8-r6-r7-20260913)。

第46节`f1b7d8a3→e1d70c58`的138提交/152文件审查曾因M8-R6驳回，Mac整仓也暴露M8-R7导入顺序失败。两项已由代码`d9ec1227`修复；Mac最终整仓2694 passed/11 skipped、实际exit0，Linux隔离CPU定向179项及原顺序1项各exit0。独立reviewer对更新范围`f1b7d8a3→d9ec1227`的**140提交/152文件给出整包代码差异通过**，见[第47节](verification.md#m8-r6-r7-20260913)。这是代码与CPU验收结论，不等于真实模型/硬盘验收或merge/push授权。

2026-09-13已补四份交付文档的独立核查：第47节原件、机器归属、SHA及同步边界通过；首轮两项P3（旧CLI说明和R6/R7过期下一动作）已修正，最终局部复核通过，见[第48节](verification.md#delivery-preparation-20260913)。未重做整包代码审查。

当前模型主线：HOLDOUT-BUILD等待独立新source、人工审查及正式构建入口；HOLDOUT-METRICS经用户确认，Spec55b3f4d4/Plan061d2598与代码f1be1060已提交；局部独立代码审查通过，Mac/Linux均覆盖614 passed/1 skipped；Linux原合并组因文件句柄限制exit1，拆组后正常退出，双机最终验证见[第49节](verification.md#holdout-metrics-20260913)。MODEL-DIAG已在Linux重算历史visual开发原记录1216条、各折摘要一致；concise原件仍缺、visual三fold merged均断链，实际推理对照阻塞。详情和轻量JSON见第48节，未构建/授权/消费真实holdout，未训练或读取权重。真实GPU、服务成功路径和硬盘/外部依赖恢复仍未验收。

Codeup 发布基线在第39节审查时经 `git ls-remote codeup refs/heads/main` 核实为 `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。
第39节当次独立审查冻结目标为任务分支 `0963642bdb47c87af0df78b809a2262ee7e1ea30`：117个提交、148个变更文件，
包含本地 main 原有的6个独有提交。审查结论为驳回修改：1项P1、3项P2；该次驳回为历史冻结范围结论；最新整包代码审查结论见第47节。

| Spec 要求 | 已有证据 | 当前验收结论及余项 |
| --- | --- | --- |
| 两个数据版本保持身份、内容与生命周期 | verification 第20–24节真实复制、20个payload验签、外部媒体引用核对；第39节复算源manifest | 复制迁移完成；本轮未重扫完整payload，媒体仍依赖原根 |
| 当前Prompt迁移，旧引用保留 | 第27节原文逐字段一致；第39节新旧文件SHA复查 | **迁移完成**：第43节已通过公开create将相同1200字节定义登记到`/data/mVllm_2/records/prompts/prompt-v4.1-r1.yaml`；标准show和重复拒绝通过，原源/指针/两data凭证保持。外部媒体及模型输入仍需显式提供 |
| 历史模型、参数和已有指标可查询 | [history-summary.yaml](history-summary.yaml)；第42节原工作区stat、47份轻量源验签与独立核查 | **本轮交付完成**：21条、234已知/152未知；源root、原ID、参数、指标口径和缺失原因可查。权重内容未重验、报告声明未重算；简明历史不等于正式可执行身份 |
| 七阶段数据及人工审查语义 | 第12–24节真实2个source、34候选、23条旧审批精确复用及11条普通自动通过 | M3完成；不代表全量新数据重建或新人工审批 |
| 三折实际训练、测评事实 | 第25–31节执行器、1678视频准备dry-run和CPU故障路径 | 接线及限定验证完成；**M8-R1**代码3b63aa52与独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；**full/holdout代码接线已完成（fed9bcfc）**：独立full train、媒体推理/授权score及来源核验后评分承诺均局部复审通过，Mac广回归679/1skip与最终holdout16项exit0；Linux最终819 passed/1 skipped、三组exit0及保护文件复验通过（第45节）。GPU训练/真实评分未执行，M4保持未关闭 |
| 严格alias及实际服务入口 | 第32节实际服务调用和拒绝路径 | 入口切换完成；M8-R1实际证据门已修复，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决；M8-R5前轮两反例已由de1b51dd修复：用户确认采用冻结Prompt，Mac及独立局部服务/HTTP请求/重试/smoke验证通过；Linux200 passed/1 skipped、两组exit0，M8-R5本轮范围已解决（第44节）。真实模型加载/推理成功未验证 |
| 不覆盖及同操作失败恢复 | M1/M3/M6故障测试；第39节Prompt并发和训练完成半提交回归 | M8-R2/R3本轮修复与复审结果见第39节；不将该局部修复扩大为所有故障窗口已验证 |
| 隔离备份恢复 | 第33节SSH小对象往返；第41节Mac/Linux异根恢复 | **M8-R4本轮范围已解决**（2fce3ab1）：原模拟store不可访问时读取/写入新根、显式current与服务准入、再次备份均通过。只重定位活动地址，冻结事实/外部引用保留；真实移动硬盘、大型产物及外部依赖整机恢复未验收 |
| 全部活动入口接管、完整差异审查 | 第34–38节M7a–e；entrypoint-map；第39节整体审查 | M7切片已有双机证据，第46节旧范围曾因M8-R6驳回，R7使旧整仓exit1；第47节更新的140提交/152文件整包代码差异审查通过，R6/R7本轮范围已解决。M8真实环境验收仍未完成。旧低层库保留不等于允许旧公共写入 |

本轮M8-R1已覆盖公开手工写入及已有无证据记录，冻结训练基座并校验被评路径与服务deploy_target一致；本机2623 passed/11 skipped、独立局部审查通过，Linux分三进程956 passed/1 skipped、各exit0，R1本轮范围已解决。
本轮M8-R4代码2fce3ab1：Mac受影响回归175 passed/1 skipped、最后URI专项6 passed；Linux最终181 passed/1 skipped，exit0，独立代码/操作文档局部审查通过。实际历史汇总现已完成，第42节另记录公共历史生成器batch口径修复d2ae4cee、Mac/Linux各247项与独立15项。物理/data下Prompt已落位并验证（第43节）；第43节当次最终复审范围为f1b7d8a3→ab5c71ae，125提交/149文件。M8-R5服务Prompt冻结输入绑定P2的策略已由用户确认，代码de1b51dd已修复并通过Mac/Linux及独立局部复审，Linux200 passed/1 skipped、两组exit0，本轮R5已解决；full/holdout实际输入接线已由fed9bcfc补齐，独立代码及操作说明局部通过，Linux819 passed/1 skipped、三组exit0和保护文件复验已完成（第45节）。第43节独立完整代码复审当次结论为整包驳回修改；本次R5局部通过不替代新的整包验收。前轮Mac整仓2647 passed/11 skipped，452.07秒，正常exit0；skip为本机历史数据缺失。四份交付文档同步当前结论（第43节）。
本轮用户明确确认独立full训练范围（Spec 0bf0baed），只使用合成CPU数据实施及验证。第45节双机证据已收口；第47节R6/R7修复、Mac整仓实际exit0、Linux隔离CPU及更新的独立整包代码差异审查已完成。四份轻量交付文档`c3685578`也已验签快进隔离分支，原正式项目与七保护文件保持；本次文档追加核查与修订结论见第48节，后续按TODO处理真实环境依赖。真正的全量训练和holdout独立验收仍依赖MODEL-DIAG、HOLDOUT-BUILD及另行实际执行授权；真实硬盘、大型产物和外部依赖整机恢复保留未验收。不能把新入口具备执行能力写成已经训练出full模型或已经获得真实holdout passed。
所有修复继续沿已确认Spec，不得以放宽门禁或把未知历史事实补成passed来关闭条目。

第39节只读核对：训练机原项目 `main@f1b7d8a3` 干净；隔离checkout在当时审查时为 `0963642b`，
原有环境和验证目录均保留。前轮R2/R3代码`2b8cbc89`通过bundle同步，Mac/Linux各466项及独立251项通过。
本轮R1代码`3b63aa52`已同步到隔离分支，原正式项目仍为干净main@f1b7d8a3；Linux分三进程956 passed/1 skipped、各exit0，验收结果见第40节。
本轮R4代码`2fce3ab1`也已同步隔离分支；原正式项目保持只读。Linux回归与恢复边界见第41节。
当前轻量证据提交由相关文件`git log`追溯；整包代码审查冻结目标为`d9ec1227`，文档同步提交不改变代码审查范围。
拟合并目标仍为 Codeup `main`。尚未请求或执行merge/push；实施前仍须明确授权并核对两端Git状态、具体提交及目标分支。
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


## 2026-09-13 test 数据分支续办交接

现行叙述使用train数据分支（三折训练/验证及全量训练）和test数据分支（最终独立测试），代码字段/配置值及历史身份不改。Spec042f335e、Plan66416f0f、代码abafdbf2已在Mac提交；完整test处理/全量人工审查/封存发布/最终full模型测试接线完成，427 passed/1 skipped、两组exit0及局部独立核查通过。证据与原失败保留见[第51节](verification.md#test-branch-20260913)。

下一步仍须独立新source、冻结train source清单、旧测试非语义身份清单、人工审查与适用真实操作授权；真实构建、训练和受限测试没有执行。本批Linux未同步/未复跑，不根据前轮隔离分支0d8a9f55推断其现在无漂移；操作前重新检查两端状态。M8历史整包审查不重做，也不把本批局部通过扩大为真实环境或模型质量验收。


## Linux验收与既定test source定位续办

第52节承接用户“推进第一步，第二步去训练机查看即可”：隔离checkout已同步7b0e01d5，同代码Linux427 passed/1 skipped、实际两组exit0；正式main及七保护文件未变。初始21个test视频在`workspace/data/source/splits/test.json`，源视频21/21在场，三折train/validation与test零交集。后续无需再向用户索取这一既定路径。

测试资格仍按原政策：旧release有claim及exposed=true，20source媒体凭据与旧发布摘要关联，video_0005没有该批候选凭据，原旧发布目录缺失。没有读取旧受限语义或新建真实test数据，不能把21个既定视频整体当作新的未使用测试，也不能推定未生成候选的视频已满足独立测试条件。精确证据、机器版本和下一动作见[第52节](verification.md#linux-test-branch-source-20260913)。


2026-09-13 test使用资格只读续查：用户已授权限定范围身份调查。当前数据目录和已发现的pre-semantic-portal-20260723备份中共6个媒体receipt集合，均无video_0005；18份manifest/identity已按非语义字段核对。迁移清单只列source、derived、training_releases→releases，不覆盖sealed_test_releases；这说明verified不证明旧test发布已迁移，不能据此认定删除原因。未找回299样本的完整发布身份清单，现阶段21个source的独立使用资格均为“证据不足”，并非“全部未用”；其中20个已有与暴露release相关联的物化证据。run_identity的初始化状态不能覆盖后续gate的completed/exposed事实。下一步最小缺失材料是旧发布的无标签candidate/source清单或对应备份；不扩大读取受限语义、不重划分或放行复用。详见verification第53节。


2026-09-13 MODEL-DIAG限定目录续查：Linux只读目录与路径stat实际exit0。evidence_archive顶层5组名称不含目标concise/visual三折；现存concise-v1仅input/reference、concise-v2仅input，不能替代concise-cv；/data/mVllm_2/workspace仅data、finetune仅active_data_release.json。六个约定三折merged目标仍不存在。未检查其他发布库内容或全盘备份，不能断言模型全部丢失；没有读取权重/预测/test内容或重跑既有评分。下一步需目标身份绑定的模型/原始预测备份，或另行确认诊断方案；test资格阻塞不取消MODEL-DIAG，也不授权重训。证据见verification第54节及docs/results/model-location-followup-20260913.json。


2026-09-13 MODEL-DIAG发布库身份及恢复目标：Linux只读release-manifest核查exit0，已知legacy发布库只有v4.1-agent-pipeline-fold0-r1，origin为coverage-first单折实验，不能替代concise/visual三折。已从历史concise报告提取三折summary/records共6个SHA256恢复比对目标；尚未找回文件，报告摘要不是原件或模型权重的独立证明。已知位置线索核查到此收束，等待准确备份路径/迁移记录；不重复扫描、重训或擅自改用其他模型。详见verification第55节。


2026-09-13 条件清理授权（Codex）：用户明确旧数据和旧训练run/模型两类均包括，只删除已验证完整迁移且不再需要的旧副本。本轮Linux预检exit0：历史迁移source_root已不存在；pre-semantic备份不在该迁移清单映射内；旧LlamaFactory顶层16个模型软链接，10个目标存在、6个断链，不能当作重复权重。workspace/runs包含迁移后的实际目标，当前发布库保持保护。删除白名单为空，实际删除0、释放0字节；不是授权缺失，而是完整迁移/冗余性证据未满足。后续先建立旧备份到保留位置的逐文件映射、内容一致性和引用退出证明，再在本次条件授权内清理；不继续索取缺失三折模型备份，不把此次决定解释为取消MODEL-DIAG或TEST-POLICY。


2026-09-13 train原视频清理候选：按用户条件授权在Linux核对旧备份01_videos到workspace/data/source/videos，89个train视频逐文件大小/SHA256一致，共5852142357字节（约5.45GiB），21个test视频未读内容。两工作区tracked运行代码/配置未见该备份路径引用。删除程序的占用预检遇到不可读/proc文件句柄，实际exit1且发生于首次unlink和证据目录创建之前；sudo -n只读能力探针要求密码，未提权。删除0、释放0，旧副本保留。候选清单与完整程序已保存；后续完成有权限的占用检查后再沿用授权执行，不能把候选已验签写成已删除。


2026-09-13 用户确认工程与模型交付拆分，Plan单独提交0d3c7461。TODO新增合并前/后续模型/非阻塞清理矩阵及MODEL-DIAG方案草案；原Intent/Spec无需改写。真实GPU、服务成功路径和恢复缺口仍逐项保留，未因拆分自动通过或豁免。下一步先做train真实输入预检与具体缺口裁决单；不再以清理或找回旧模型占据主线。本轮无远端操作、训练、测试使用、删除或push/merge。


2026-09-13 train真实输入预检：Linux隔离bb73e4dd执行正式build_versioned_datasets(scope=full)，实际exit0；data-v4.1-r2 + prompt-v4.1-r1 + 原workspace/data媒体根成功生成内存输入。三折train/validation为1253/425、1014/664、1186/492，full为1678，唯一媒体1678个共165485727字节逐一哈希；媒体名提取source与既定21个test ID无交集，此项不代替内容隔离或test资格。没有Run写入、训练或GPU执行。完整结果摘要见docs/results/train-input-preflight-20260913.json及verification第59节。


2026-09-13 M4配置/资源预检：基座路径models/minicpm_v_4_5存在并解析到models/minicpmv4_5，config声明openbmb/MiniCPM-V-4_5；仅stat/配置，未验完整权重或冻结修订。4090查询时24564MiB总显存、约1081MiB使用、利用率0%；/data约3.4TiB可用。cpm45有torch/transformers/peft等训练包，但importlib.metadata未发现mlflow分发包；正式适配器在同进程调用run_training，不能假设CPU隔离环境与GPU环境已贯通。公共入口仅cross_validation三折整组或full，没有单折选项；前文“现成单折工程验证”建议收窄为待设计方案。下一步先核对完整执行环境与有限三折工程验证方案，不创建训练版本、不启动训练。


当前范围以Spec a5cfa86f/Plan efde1536为准：工程迁移收口不要求新微调，旧模型保留且质量门禁不变。下一步M4-FOLD逐折入口方案确认及agent/DVC/MLflow环境接线核对，不再推进有限真实训练。agent环境和基座完整性已核查，见verification第61节；上游master未冻结为可信修订，不能称来源验签通过。
