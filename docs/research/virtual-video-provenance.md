# 65 条虚拟视频的来源与使用情况

> 状态：只读调查结果，供审阅；不是虚拟测评集准入清单。调查基线为 2026-11-10 的本地文件；其中 Blender 项目有未提交修改，版本身份见文末。

## 结论与使用边界

65 条均列入用户确认的 `video-V1` 首批验证模拟数据包，但**尚不能直接认定为本轮固定虚拟测评集**。其中 12 条参考了当前固定真实测试来源 `video_0025` 或 `video_0032`；根据[测评设计的来源隔离](../../docs/design-test.md)，这两组不得用于训练或开发调参。其余 53 条参考 9 个当前真实开发来源；它们的场景、参数变体与真实来源需要作为关联组审计，不能随机拆到训练与测评两侧。

[Blender 项目说明](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/README.md)和[总索引](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/index.json)把 65 条记为用户确认的整体验证数据包。索引同时保留不同层级的历史状态：27 条 `user_accepted_video`、`user_accepted=true`；另 38 条仍为 `checked_pending_user_acceptance`、`user_accepted=false`。这 38 条的检查和复核记录与整包确认并存，**不能把整包接受擅自改写成逐片接受字段已更新**，需要时核对具体验收范围。所有条目 `training_released=false` 也不证明仓外从未使用。

[总索引的 `validation_dataset.scope`](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/index.json)记录该包未执行下游模型训练或评价；本次检索两项目的 README、索引、设计和划分记录及 Blender 非视频工作记录，**未找到**这 65 条进入训练、验证、模型开发推理/调参或正式测评的具体运行记录。没有完整旧训练输入清单、远端运行日志或已清理历史，不能排除仓外或历史暴露，正式用途须逐模型复核。

另对相邻原项目 `mVllm_2` 的训练、评测和数据记录目录中 3,606 个可读文本，以 65 个虚拟视频 ID、`video-V1` 及项目名定向搜索，未发现具体 V1 模型运行输入。该范围覆盖 `records`、`finetune`、`docs/results`、`data/derived`、`data/releases`、`versioning/store` 和 `store` 中存在的目录，只扫描 `.json`、`.jsonl`、`.yaml`、`.yml`、`.csv`、`.md`、`.txt`、`.log` 和 `.xml` 文件，不涵盖训练机完整历史；逐文件清单及脚本未保留。原项目的[旧测试公开记录](/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2/docs/results/v4_1_stage_d_sealed_test_release/README.md)同时保留数据准备时未启动的状态和后续获授权后的运行记录；`video_0025`、`video_0032` 也有真实源候选和审查元数据。当前没有完整逐样本运行清单，无法确认这两个真实源是否进入该次推理；这些真实源记录不能当作 65 条虚拟视频已使用的证据。

这 65 条由 11 条基础视频、9 条单参数变体、7 条组合变体和 38 条新增样片构成。本次只读匹配索引、V1 文件名与集中 CSV：各 65 项且 ID 集合一致；逐项计算 65 个已有虚拟 MP4 和 65 份元数据的 SHA-256，与索引记录一致。没有播放或重新验收这些视频，也没有读取或处理任何真实测试视频。每个视频及其历史使用记录仍须按实际画面、身份和用途复核。

## 旧标签与本轮五类标签不能直接混用

[集中 CSV](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/all_videos_tag.csv)只有 ID、模拟贯通丧失时间、旧主模式、材料和清晰度；[总索引](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/index.json)及同名 JSON 另有六组旧核验标签。它们是素材检索线索，不是[本轮五类标签](../../docs/label.md)的完整答案：

| 本轮字段 | 旧记录可提供什么 | 不能直接转换之处 |
| --- | --- | --- |
| 断裂状态 | 旧的“完全断裂”和整段 v4.1 标签预览说明旧项目记录的整体结果 | 片段的未断、发生、已断或无法判断须看该片段画面；完整断裂不能自动赋给所有片段；首次可见分离不等于记录的模拟最后失贯通时间。 |
| 断裂模式 | 旧主模式及其用户确认记录是线索 | `界面脱粘` 是旧主类别，却不是新模式选项；旧 `无法确认` 与新 `无法判断` 的字面相近也不能跳过新证据检查。尤其 `video_0014` 组旧项目将均匀拉长后快速断裂作为半脆半韧视觉判据，而新标签明确要求分别指出脆性与韧性证据，不能只凭先伸长后瞬断；该组需逐片重审，不删除旧确认。 |
| 断裂位置 | 旧模拟位置、夹口根部可作检索线索 | 旧模拟标距多为作者规定，真实来源正式标距常未知；本轮按画面中夹具、试样的相对关系判断，不自动继承。 |
| 异常情况 | 旧夹持／拍摄异常分别标“无” | 新标签逐项判断未夹紧、视频异常、爆炸性断裂的“是／否／无法判断”；旧“无”不保证足以排除每个新异常。旧局部分束不等于爆炸性，新 full_span 0.2 候选已被用户否定并暂停生成。 |
| 断裂现象 | 个别来源和生成记录描述伸长、颈缩、裂纹或同步界面打开 | 新的伸长、颈缩、开裂、界面分离、断后脱夹须逐项看实际片段，分别写是、否或无法判断；缺字段与否不同。断后脱夹不自动等于未夹紧。 |

2026-11-10 的用户确认已将薄膜根部和金属平板的集中表与索引模式改为韧性，原始元数据及历史复核保留；README 较早基础表和 `generator/README.md` 仍保留此前“无法确认/未知”的描述。这里同时保留两层记录，不擅自修改 Blender 项目；新五类真值仍需依据本轮定义和画面审查。

## 11 个来源组及当前划分

这里的“来源”是索引登记的真实视频参考，“基准”是变体追溯的逻辑基准，并不保证每项都有独立保存、可重放的 Blender 场景。来源是定性视觉参照，不等同逐帧复刻；模拟时长、模型尺寸、几何、运动和微观机制未必从源实验测得。真实来源的用户确认、来源观察、作者假设与未知分别保留在各同名 JSON。基础视频及离散变体的接受不自动批准连续参数范围。

按照当前 21 个测试成员及三折划分，11 个来源组如下。开发组每个来源在列出的折作为验证，另两折为训练；这里描述的是**真实来源划分**，并不声称该组虚拟视频实际上已参加那些运行。

| 真实参考来源 | 虚拟条数 | 当前真实来源划分 | 组内旧主模式 / 位置 | 主要用途限制 |
| --- | ---: | --- | --- | --- |
| `video_0003` | 11 | 开发，fold 0 验证 | 脆性 / 标距内 | 训练暴露和相似来源待查 |
| `video_0006` | 3 | 开发，fold 0 验证 | 韧性 / 标距内 | 同上 |
| `video_0014` | 13 | 开发，fold 0 验证 | 半脆半韧 / 标距内 | 旧项目判据与本轮判据不一致，须重审 |
| `video_0020` | 10 | 开发，fold 1 验证 | 界面脱粘 / 标距内 | 界面脱粘不是本轮断裂模式取值 |
| `video_0025` | 1 | 固定 test | 韧性 / 夹口根部 | 禁用于训练或开发调参 |
| `video_0032` | 11 | 固定 test | 脆性 / 标距内 | 禁用于训练或开发调参 |
| `video_0040` | 1 | 开发，fold 1 验证 | 无法确认 / 标距内 | 旧局部分束不作爆炸性正例 |
| `video_0050` | 4 | 开发，fold 2 验证 | 脆性 / 标距内 | 源片完整分离是未知，模拟为定性扩展 |
| `video_0058` | 1 | 开发，fold 1 验证 | 韧性 / 标距内 | 源片机制与运动细节证据有限 |
| `video_0097` | 3 | 开发，fold 2 验证 | 韧性 / 标距内 | 训练暴露和相似来源待查 |
| `video_0100` | 7 | 开发，fold 2 验证 | 脆性 / 标距外非根部 | 同上 |

交叉不是仅凭名称猜测：`video_0025` 和 `video_0032` 的 Blender 基础元数据记录的真实源 SHA-256，分别与 [ROI 清单](../../data/roi/manifest.json)的对应 `source.sha256` 一致；[测试成员清单](../../data/splits/three-fold/test.json)也包含这两个 ID。这是既有元数据之间的核对，本次未重新读取测试媒体。测试参考的虚拟视频即使未来经审查纳入虚拟测评，也不能当成与对应真实测试源独立的额外实验；是否纳入以及历史暴露和标签证据仍待决定。

**可能的后续用途：** 53 条开发参考组可在明确所属折、确认未跨组泄漏的前提下考虑用于非冻结的方法试制或开发诊断；如果某个模型曾训练对应真实来源或近似场景，它们不能作为该模型的独立来源测评。12 条 test 参考视频可列为未来测评的待核候选，但必须先查模型暴露、人工复核画面和新标签，确认其与真实测试的关联，并由用户决定用途；不能将其用于试制调参。所有组均不因本报告自动准入。

## 逐组目录：视频、旧标签和变体

视频均位于 Blender 项目 `outputs/video-V1/<视频 ID>.mp4`。下面的 ID 链接指向该项在索引中登记的元数据；部分元数据位于被 Git 忽略的 `_work/`，存在清理和迁移风险，不应把本地路径当作永久备份。表内时间来自集中 CSV，含义为**模拟中最终失去适用贯通连接的时刻**，不是原实验事件时间，也不是已经核实的首次肉眼可判分离帧。

所有 65 项索引旧核验值为“完全断裂”、夹持异常“无”、拍摄异常“无”；这与本轮五类标签的逐片真值不是一回事。每组的材料、旧主模式、位置与清晰度写在组标题下；同组共用这些旧值。“单片已接受”表示索引逐片接受字段为真；“单片字段待定”表示索引保留待逐片接受字段，但已列入用户确认的整个 V1 验证包。每项的详细配置、来源观察与限定，以链接的 JSON 以及总索引为准。

下表中的颈缩参数 `A` 控制金属试样的局部轴向伸长增量；较小值是较弱颈缩的设计变化。“破坏中心”是沿模拟试样轴向的作者坐标，“材料分数”是沿模拟试样材料坐标的相对比例；它们用于调整破坏位置，不是从真实试样测得的毫米尺寸。长度和开口倍率调整所记的模拟界面分离范围与幅度，事件时间调整模拟过程中的失贯通时刻。参数差异是否在成片中可辨、是否符合新标签，仍需人工看画面。

### video_0003：金属圆棒小变形脆断（11 条）

**模板：** `metal_initial.py / brittle`；**逻辑基准：** `metal_round_brittle_baseline_v1`；**真实来源划分：** 开发，fold 0 验证。

**旧标签：** 金属 / 脆性断裂 / 标距内 / 720P。源片中圆棒小变形突断是定性参照；作者设置的几何和加载不是材料本构标定。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [metal_round_brittle_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_brittle/metal_round_brittle_baseline_v1.json) | 17.2 s | 基础样片；单片已接受 |
| [metal_round_brittle_stage1_center_p075_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_brittle/metal_round_brittle_stage1_center_p075_v1.json) | 17.2 s | 破坏中心：0→+0.75；单片已接受 |
| [metal_round_brittle_coupled_center_p075_time15_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_brittle/metal_round_brittle_coupled_center_p075_time15_v1.json) | 15 s | 材料中心+0.75；15秒；单片已接受 |
| [metal_brittle_24b9f8453ffd](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_24b9f8453ffd/299b1b60ab02fa6d/metal_brittle_24b9f8453ffd.json) | 17 s | 新增离散变体，破坏中心 0.25；单片字段待定 |
| [metal_brittle_5208fef67de7](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_5208fef67de7/e0d63d0994544642/metal_brittle_5208fef67de7.json) | 16 s | 新增离散变体，破坏中心 0.5；单片字段待定 |
| [metal_brittle_8fd177bc37cd](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_8fd177bc37cd/afbfd0a64e7ecd6c/metal_brittle_8fd177bc37cd.json) | 15 s | 新增离散变体，破坏中心 0.5；单片字段待定 |
| [metal_brittle_95bf83c84c0a](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_95bf83c84c0a/630254443bf4d0f8/metal_brittle_95bf83c84c0a.json) | 17 s | 新增离散变体，破坏中心 0.5；单片字段待定 |
| [metal_brittle_c3f0c995c8ef](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_c3f0c995c8ef/f6429b6982180419/metal_brittle_c3f0c995c8ef.json) | 16 s | 新增离散变体，破坏中心 0.0；单片字段待定 |
| [metal_brittle_cc100241b5f7](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_cc100241b5f7/d57ef5d42534ee45/metal_brittle_cc100241b5f7.json) | 15 s | 新增离散变体，破坏中心 0.0；单片字段待定 |
| [metal_brittle_d113c4e01c83](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_d113c4e01c83/139b32c24bc6bc14/metal_brittle_d113c4e01c83.json) | 16 s | 新增离散变体，破坏中心 0.25；单片字段待定 |
| [metal_brittle_dda4b5e6e727](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/metal_brittle_dda4b5e6e727/0ce641ad891eda47/metal_brittle_dda4b5e6e727.json) | 15 s | 新增离散变体，破坏中心 0.25；单片字段待定 |

### video_0006：金属圆棒颈缩断裂（3 条）

**模板：** `metal_initial.py / ductile`；**逻辑基准：** `metal_round_ductile_baseline_v1`；**真实来源划分：** 开发，fold 0 验证。

**旧标签：** 金属 / 韧性断裂 / 标距内 / 720P。源片的圆棒颈缩形态是定性参照；局部幅度和模型假设须与逐条配置区分。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [metal_round_ductile_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_neck_separation/metal_round_ductile_baseline_v1.json) | 18.366666667 s | 基础样片；单片已接受 |
| [metal_round_ductile_stage1_a2_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_ductile/metal_round_ductile_stage1_a2_v1.json) | 18.366666667 s | A：4→2；单片已接受 |
| [metal_round_ductile_coupled_a2_time12_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_round_ductile/metal_round_ductile_coupled_a2_time12_v1.json) | 12 s | A=2；12秒；单片已接受 |

### video_0014：高分子均匀伸长后斜向突断（13 条）

**模板：** `polymer_mixed.py`；**逻辑基准：** `polymer_finite_deformation_oblique_rupture_baseline_v1`；**真实来源划分：** 开发，fold 0 验证。

**旧标签：** 高分子 / 半脆半韧断裂 / 标距内 / 720P。Blender 的半脆半韧是已确认的项目视觉判据；弹塑份额未知，不能直接转成本轮更严格的五类模式。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [polymer_finite_deformation_oblique_rupture_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_finite_deformation_oblique_rupture/polymer_finite_deformation_oblique_rupture_baseline_v1.json) | 16 s | 基础样片；单片已接受 |
| [polymer_mixed_stage1_stretch115_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_finite_deformation_oblique_rupture/polymer_mixed_stage1_stretch115_v1.json) | 16 s | 伸长增量×1.15；单片已接受 |
| [polymer_mixed_coupled_stretch115_time15_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_finite_deformation_oblique_rupture/polymer_mixed_coupled_stretch115_time15_v1.json) | 15 s | 伸长增量×1.15；15秒；单片已接受 |
| [mixed_2a9499713a2b](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_2a9499713a2b/fdac8cf6db4b1b29/mixed_2a9499713a2b.json) | 15 s | 新增离散变体，最大局部伸长 1.084；单片字段待定 |
| [mixed_3568deb2ca33](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_3568deb2ca33/a598f754f98dbcae/mixed_3568deb2ca33.json) | 15.5 s | 新增离散变体，最大局部伸长 1.084；单片字段待定 |
| [mixed_474c4c10ff01](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_474c4c10ff01/cbe93e29ae240cfe/mixed_474c4c10ff01.json) | 16 s | 新增离散变体，最大局部伸长 1.084；单片字段待定 |
| [mixed_6bd6ad919f7f](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_6bd6ad919f7f/cde2e69aa79dea52/mixed_6bd6ad919f7f.json) | 15.5 s | 新增离散变体，最大局部伸长 1.08；单片字段待定 |
| [mixed_8e505bb139b5](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_8e505bb139b5/0ae78bbe2cbcc2a9/mixed_8e505bb139b5.json) | 15.5 s | 新增离散变体，最大局部伸长 1.088；单片字段待定 |
| [mixed_b6dd4440bb01](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_b6dd4440bb01/d68545a590accaf5/mixed_b6dd4440bb01.json) | 16 s | 新增离散变体，最大局部伸长 1.088；单片字段待定 |
| [mixed_c25215a9fc08](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_c25215a9fc08/b5d0e4175e96743c/mixed_c25215a9fc08.json) | 15.5 s | 新增离散变体，最大局部伸长 1.092；单片字段待定 |
| [mixed_d78ee0af8f98](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_d78ee0af8f98/9b9d7e6e89068b74/mixed_d78ee0af8f98.json) | 15 s | 新增离散变体，最大局部伸长 1.088；单片字段待定 |
| [mixed_e4b70b9f11d1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_e4b70b9f11d1/3a7403d5ea862930/mixed_e4b70b9f11d1.json) | 15.5 s | 新增离散变体，最大局部伸长 1.086；单片字段待定 |
| [mixed_f22a4a698822](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/mixed_f22a4a698822/02de1d955cdbe03f/mixed_f22a4a698822.json) | 15 s | 新增离散变体，最大局部伸长 1.08；单片字段待定 |

### video_0020：复材断裂与界面打开同步（10 条）

**模板：** `composite_initial.py / debond`；**逻辑基准：** `composite_interface_debond_simultaneous_baseline_v0_4`；**真实来源划分：** 开发，fold 1 验证。

**旧标签：** 复材 / 界面脱粘 / 标距内 / 540P。真实视频提供参考，当前同步时序还包含用户纠正和作者安排；不得直接推为完整材料破坏机制。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [composite_interface_debond_simultaneous_baseline_v0_4](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_interface_debond_simultaneous_complete/composite_interface_debond_simultaneous_baseline_v0_4.json) | 17 s | 基础样片；单片已接受 |
| [composite_debond_stage1_length080_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_interface_debond_simultaneous_complete/composite_debond_stage1_length080_v1.json) | 17 s | 脱粘长度×0.8；单片已接受 |
| [composite_debond_stage1_opening120_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_interface_debond_simultaneous_complete/composite_debond_stage1_opening120_v1.json) | 17 s | 界面开口×1.2；单片已接受 |
| [composite_debond_coupled_length080_opening120_time15_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_interface_debond_simultaneous_complete/composite_debond_coupled_length080_opening120_time15_v1.json) | 15 s | 长度×0.8；开口×1.2；15秒；单片已接受 |
| [debond_19ad315937d9](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_19ad315937d9/ce8c4c5307275b33/debond_19ad315937d9.json) | 17 s | 新增离散变体，脱粘长度×0.9，开口×1.2；单片字段待定 |
| [debond_3a83e6589f3c](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_3a83e6589f3c/750b8d5d527eb7b6/debond_3a83e6589f3c.json) | 16 s | 新增离散变体，脱粘长度×0.8，开口×1.1；单片字段待定 |
| [debond_633abced1e80](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_633abced1e80/87ef6945bd15b32e/debond_633abced1e80.json) | 16 s | 新增离散变体，脱粘长度×0.9，开口×1.1；单片字段待定 |
| [debond_9a6e9873f857](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_9a6e9873f857/29cb36efc2fe9c8c/debond_9a6e9873f857.json) | 15 s | 新增离散变体，脱粘长度×1.0，开口×1.1；单片字段待定 |
| [debond_f1b9bd026fc6](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_f1b9bd026fc6/cdd6f60e24205d15/debond_f1b9bd026fc6.json) | 15 s | 新增离散变体，脱粘长度×0.9，开口×1.0；单片字段待定 |
| [debond_f8acebcca850](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/debond_f8acebcca850/29b1720f7c8cfa14/debond_f8acebcca850.json) | 16 s | 新增离散变体，脱粘长度×1.0，开口×1.2；单片字段待定 |

### video_0025：高分子薄膜夹口根部断裂（1 条）

**模板：** `polymer_initial.py / film`；**逻辑基准：** `polymer_yellow_film_grip_root_baseline_v2`；**真实来源划分：** 固定 test。

**旧标签：** 高分子 / 韧性断裂 / 夹口根部 / 540P。参考能支持薄膜及根部位置；2026-11-10 用户将旧模式确认为韧性。根部位置本身不能证明断裂模式。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [polymer_yellow_film_grip_root_baseline_v2](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_yellow_film_root_rupture/polymer_yellow_film_grip_root_baseline_v2.json) | 16 s | 基础样片；单片已接受 |

### video_0032：高分子淡绿窄平条脆断（11 条）

**模板：** `polymer_brittle.py`；**逻辑基准：** `polymer_pale_green_brittle_flat_strip_baseline_v1`；**真实来源划分：** 固定 test。

**旧标签：** 高分子 / 脆性断裂 / 标距内 / 540P。历史记录查看过事件前后源帧，支持窄条、小变形及分离的定性参考；具体牌号、本构及微观机制未知。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [polymer_pale_green_brittle_flat_strip_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_pale_green_brittle_flat_strip/polymer_pale_green_brittle_flat_strip_baseline_v1.json) | 16 s | 基础样片；单片已接受 |
| [polymer_brittle_stage1_position055_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_pale_green_brittle_flat_strip/polymer_brittle_stage1_position055_v1.json) | 16 s | 破坏材料分数：0.50→0.55；单片已接受 |
| [polymer_brittle_coupled_position055_time12_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_pale_green_brittle_flat_strip/polymer_brittle_coupled_position055_time12_v1.json) | 12 s | 材料分数0.55；12秒；单片已接受 |
| [polymer_brittle_527d847f2741](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_527d847f2741/c9037aa8bc8a9b75/polymer_brittle_527d847f2741.json) | 16 s | 新增离散变体，断裂材料分数 0.525；单片字段待定 |
| [polymer_brittle_7c88eeeae51f](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_7c88eeeae51f/adfb7bbf8e460c61/polymer_brittle_7c88eeeae51f.json) | 14 s | 新增离散变体，断裂材料分数 0.5；单片字段待定 |
| [polymer_brittle_b0cd99f7ae30](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_b0cd99f7ae30/303aff50310f92bc/polymer_brittle_b0cd99f7ae30.json) | 12 s | 新增离散变体，断裂材料分数 0.525；单片字段待定 |
| [polymer_brittle_b9ab8a238e19](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_b9ab8a238e19/513abd4d2ec8acf4/polymer_brittle_b9ab8a238e19.json) | 14 s | 新增离散变体，断裂材料分数 0.525；单片字段待定 |
| [polymer_brittle_bcfe3a307376](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_bcfe3a307376/e1783fa01c4f150d/polymer_brittle_bcfe3a307376.json) | 15 s | 新增离散变体，断裂材料分数 0.5；单片字段待定 |
| [polymer_brittle_e2c15b3c1473](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_e2c15b3c1473/44d4b2b618c005d7/polymer_brittle_e2c15b3c1473.json) | 12 s | 新增离散变体，断裂材料分数 0.5；单片字段待定 |
| [polymer_brittle_ea23f4e39317](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_ea23f4e39317/aee88dd89417680a/polymer_brittle_ea23f4e39317.json) | 15 s | 新增离散变体，断裂材料分数 0.525；单片字段待定 |
| [polymer_brittle_f89aa7bc8961](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/polymer_brittle_f89aa7bc8961/5d3bd34030557d9f/polymer_brittle_f89aa7bc8961.json) | 14 s | 新增离散变体，断裂材料分数 0.55；单片字段待定 |

### video_0040：复材快速局部分束（1 条）

**模板：** `composite_fragmentation.py / local 旧版`；**逻辑基准：** `composite_rapid_strand_fragmentation_baseline_v0_1`；**真实来源划分：** 开发，fold 1 验证。

**旧标签：** 复材 / 无法确认 / 标距内 / 540P。旧局部样片被接受，但其主模式为无法确认；被否定的 full_span 0.2 不在65条内，也不证明爆炸性断裂。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [composite_rapid_strand_fragmentation_baseline_v0_1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_rapid_strand_fragmentation/composite_rapid_strand_fragmentation_baseline_v0_1.json) | 16 s | 基础样片；单片已接受 |

### video_0050：陶瓷狗骨脆断（4 条）

**模板：** `ceramic_initial.py`；**逻辑基准：** `ceramic_dogbone_brittle_baseline_v1`；**真实来源划分：** 开发，fold 2 验证。

**旧标签：** 陶瓷 / 脆性断裂 / 标距内 / 720P。用户确认陶瓷身份；源片有渐进裂纹，完整分离和时刻缺直接证据；模拟完整断裂是作者定性扩展。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [ceramic_dogbone_brittle_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/ceramic_dogbone_brittle/ceramic_dogbone_brittle_baseline_v1.json) | 16 s | 基础样片；单片已接受 |
| [ceramic_brittle_stage1_time12_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/ceramic_dogbone_brittle/ceramic_brittle_stage1_time12_v1.json) | 12 s | 最终失去贯通：16→12秒；单片已接受 |
| [ceramic_54c9123982ca](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009/execution/runs/ceramic_54c9123982ca/a99ea32b123b992f/ceramic_54c9123982ca.json) | 15 s | 新增离散变体，破坏中心 -0.4；单片字段待定 |
| [ceramic_fafb6d038402](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009/execution/runs/ceramic_fafb6d038402/321ad3776c4157e1/ceramic_fafb6d038402.json) | 13 s | 新增离散变体，破坏中心 -0.4；单片字段待定 |

### video_0058：金属平板有限变形断裂（1 条）

**模板：** `metal_flat.py`；**逻辑基准：** `metal_flat_limited_deformation_rupture_baseline_v1`；**真实来源划分：** 开发，fold 1 验证。

**旧标签：** 金属 / 韧性断裂 / 标距内 / 540P。源片支持平板狗骨和夹持，动态颈缩幅度、精确分离及断后轨迹未知；2026-11-10 用户确认该片为韧性。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [metal_flat_limited_deformation_rupture_baseline_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/metal_flat_limited_deformation_rupture/metal_flat_limited_deformation_rupture_baseline_v1.json) | 17 s | 基础样片；单片已接受 |

### video_0097：高分子狗骨大伸长断裂（3 条）

**模板：** `polymer_initial.py / dogbone`；**逻辑基准：** `polymer_black_dogbone_baseline_v2`；**真实来源划分：** 开发，fold 2 验证。

**旧标签：** 高分子 / 韧性断裂 / 标距内 / 540P。源片用于定性形态及大伸长参考；模拟的行程、时间和装置运动不等于源实验测量。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [polymer_black_dogbone_baseline_v2](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_black_flexible_dogbone/polymer_black_dogbone_baseline_v2.json) | 16 s | 基础样片；单片已接受 |
| [polymer_black_dogbone_stage1_stretch085_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_black_flexible_dogbone/polymer_black_dogbone_stage1_stretch085_v1.json) | 16 s | 伸长增量×0.85；单片已接受 |
| [polymer_dogbone_coupled_stretch085_time17_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/polymer_black_flexible_dogbone/polymer_dogbone_coupled_stretch085_time17_v1.json) | 17 s | 伸长增量×0.85；17秒；单片已接受 |

### video_0100：复材近下夹口脆断（7 条）

**模板：** `composite_initial.py / brittle`；**逻辑基准：** `composite_brittle_lower_feedback_v0_3`；**真实来源划分：** 开发，fold 2 验证。

**旧标签：** 复材 / 脆性断裂 / 标距外非根部 / 540P。源片提供试样和低位破坏参考；侧视、附件遮挡及作者几何近似限制精确断面和机制判断。

| 视频 ID（链接为元数据） | 贯通丧失时间 | 变体及历史状态 |
| --- | ---: | --- |
| [composite_brittle_lower_feedback_v0_3](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_brittle_lower/composite_brittle_lower_feedback_v0_3.json) | 17 s | 基础样片；单片已接受 |
| [composite_brittle_stage1_position_minus012_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_brittle_lower/composite_brittle_stage1_position_minus012_v1.json) | 17 s | 破坏中心：−1.83→−1.95；单片已接受 |
| [composite_brittle_coupled_center_minus195_time12_v1](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/outputs/current/composite_brittle_lower/composite_brittle_coupled_center_minus195_time12_v1.json) | 12 s | 材料中心−1.95；12秒；单片已接受 |
| [composite_brittle_40de05bc8db6](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/composite_brittle_40de05bc8db6/cf31a152fc1a013c/composite_brittle_40de05bc8db6.json) | 12 s | 新增离散变体，破坏中心 -1.83；单片字段待定 |
| [composite_brittle_71add4d43545](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/composite_brittle_71add4d43545/4b01eabc2cde4b14/composite_brittle_71add4d43545.json) | 15 s | 新增离散变体，破坏中心 -1.89；单片字段待定 |
| [composite_brittle_85e1faca3a2f](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/composite_brittle_85e1faca3a2f/ca57a89fe68b9e1b/composite_brittle_85e1faca3a2f.json) | 15 s | 新增离散变体，破坏中心 -1.95；单片字段待定 |
| [composite_brittle_f8c38a77a63d](/Users/pcoffeep/AgentPlayground/active-projects/BlenderTensileVideo/_work/training-batch1-20261009-fastcheck/execution/runs/composite_brittle_f8c38a77a63d/bf0ef0b2a0346004/composite_brittle_f8c38a77a63d.json) | 12 s | 新增离散变体，破坏中心 -1.89；单片字段待定 |

## 依据、可复核方法与失效条件

- 本报告从 TensileAgent-Finetune 当前工作分支 `codex/evaluation-framework` 的提交 `61f29eb546aa89d844a238e9d3e59cb3f664c1e5` 出发；[标签说明](../../docs/label.md)、[测评设计](../../docs/design-test.md)、[划分结果](../../docs/split/data-split-result.md)、[固定 test 清单](../../data/splits/three-fold/test.json)及三折成员是适用基线。
- Blender 项目检查时所在提交 `d9cdbf26fb96db83454653cc2d15834b11b34dac`，但 README、生成器说明、导出器、索引与 CSV 存在未提交修改；本报告使用当时工作树，不将它说成该提交的原始内容。README SHA-256 `084b2d7b953139a2b2167591c248593aaf2e23a8901cabdc12a37bb83cd6bb43`；索引 `820b8983d1c249ca7b655ebb4854cff59f6fcf217b8d2b283a720100846a0de8`；CSV `58ad4322b6b1a92927afe7975c0a5499db133c41e0fcc41345a047f62cc39d28`。复核时若这些内容变化，不能仅依据提交号恢复本次未提交状态。
- 本次通过索引 `items`、`validation_dataset.member_ids`、CSV 的 `id` 和目录内文件名关联，并核对每条索引记录的媒体及元数据 SHA；来源归组依据 `source_id`，逐项父基准、参数、时间和假设依各自元数据。真实测试源交叉使用已有清单及元数据摘要，不读取测试视频。源素材之间是否存在不同 ID 的近似来源、完整外部训练/开发历史以及未来画面真实性均未验证。
- 本文对应的测试覆盖、待补数据与后续制作步骤见[虚拟测评数据要求](evaluation-data-requirements.md)。

**失效条件：** 索引或集中标签、用户验收记录、源视频身份与划分、训练或开发暴露、新五类标签定义、Blender 模板及其元数据任一变化时，应重核受影响的来源组和结论；若本次工作树快照或 `_work` 证据被清理，本地链接和细节可能无法再核对。后续实物画面、人工标签或正式评测证据不能以本静态调查替代。
