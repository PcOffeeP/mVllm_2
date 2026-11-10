# 本地子视频人工审核工具

本工具让用户播放已有开发集候选，逐片填写五类标签，并把草稿、疑问、退回与确认保存为独立修订。源标注只作参考，不会自动填入新审核值，也不会回写原标注。工具不调用模型、不生成媒体，不执行训练、正式测评或发布；审核确认和 JSONL 导出也不等于数据发布。未审核片段不得进入正式发布。

以下命令对应本次任务工作树和本机已有媒体位置，供用户手动运行。本说明编写时未启动服务或打开真实媒体；完整流程边界见[子视频审核与评价衔接](../../docs/subvideo-review-workflow.md)，标签判据见[标签说明](../../docs/label.md)。

## 1. 在任务工作树启动，记录也留在任务工作树

使用 Python 3.10 或更新版本。服务使用 Python 标准库；当前实现依赖 `fcntl`，适用于本机 macOS 和 Linux，不提供 Windows 原生运行保证。保持启动终端打开，使用本机浏览器访问。

本次两个目录用途不同：

| 路径 | 用途 |
| --- | --- |
| `/Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench` | 任务工作树：从这里运行新工具，保存独立审核记录及导出文件 |
| `/Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune` | 原工作区：读取已有生成清单、固定划分和被请求的开发候选／开发源视频 |

在终端执行：

```bash
cd /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench
python -m script.subvideo_review.server \
  --project-root /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune \
  --records /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review/reviews.json \
  serve --port 8765
```

`--project-root` 必须指向带现有候选媒体的原工作区；Git 工作树通常没有被忽略的视频副本。默认生成清单是该目录下的 `data/subvideos/frame-aligned/manifest.json`，媒体相对该清单所在目录定位。**本次始终显式填写绝对路径 `--records`**：省略它会默认写入 `--project-root` 下的 `data/subvideo-review/reviews.json`，与本次独立记录要求不符；相对记录路径也按 `--project-root` 解释，而非当前终端目录。

正常启动后，终端显示本机链接、只读清单路径和独立审核历史路径。核对后打开 [http://127.0.0.1:8765](http://127.0.0.1:8765)。服务仅监听 `127.0.0.1`，不提供局域网访问。若端口已占用，可把命令中的端口改成其他空闲值，并使用终端实际打印的链接。

页面载入时会选择首个候选并请求其媒体；实际播放由用户操作。服务在播放和保存时核对媒体 SHA-256，首次载入或保存可能需要等待。默认单个媒体上限为 512 MiB，可通过全局参数 `--max-media-mib` 显式调整；不要把大小限制报错当作标签问题。

## 2. 逐片填写并保存

先按“来源”“审核状态”筛选，或按候选／来源编号搜索，再选择候选。核对标题、来源、媒体摘要、窗口与帧映射信息，观看实际片段后填写。右侧“源标签与事件线索”是原视频参考，不是该片段的真值；窗口角色也不能代替片段判断。

首次审核当前身份的候选时，11 项均为空白：三类单选、三项异常、五项现象。单选可明确选“无法确定”，异常和现象可明确选“无法判断”；这些都是已判断后的合法值，填齐后可以确认。空白表示未完成，不能用于完整确认，也不能当成“否”。

| 按钮 | 何时使用 | 保存要求 |
| --- | --- | --- |
| 保存草稿 | 尚未完成，需要稍后继续 | 可保留空白；已填值仍须合法 |
| 记录疑问 | 画面、规则或身份存在需要讨论的问题 | 在“决定依据”填写原因，可保留未完成标签 |
| 退回 | 需要处理窗口、媒体或其他问题后再审 | 在“决定依据”填写原因，可保留未完成标签 |
| 一次确认全部 | 已逐项完成本片段判断 | 11 项全部填写，且通过取值与组合检查 |

“审核备注”可记录画面和边界说明。“决定依据”在退回、记录疑问时必填；当前身份曾有已确认修订后，再保存任何非草稿决定也须填写理由。修改不会覆盖旧修订，每次成功保存都会产生新的 `review_id`，页面显示保存状态和新修订编号。

未断裂或未夹紧时，模式和位置须由用户手动选择“无”；工具不会自动修改。未断裂与爆炸性断裂互斥；完整确认时，未断裂与断后脱夹也互斥。出现报错时按画面核对，不为通过校验而随意改标签。疑问或草稿同样需要合法取值，并遵守保存时适用的组合检查。

已有当前身份的人工修订会在重新选择候选时恢复，便于继续审核；这不同于自动继承源标签。页面同时列出修订历史。若候选、片段 SHA、生成清单 SHA、候选记录摘要或来源身份发生变化，同名旧修订会隔离，显示数量，不自动套用为当前决定。

切换候选或转看原视频前，先保存需要保留的输入。片段播放结束不会自动确认或切换；“下一候选”会主动切到筛选结果中的下一条，并尝试播放。未保存输入遇到切换／关闭页面时会有提示，但不要把浏览器提示当作保存成功。多个页面同时修改同一候选时，旧页面保存可能提示已有其他修订；重新载入后核对最新决定，再填写保存。

## 3. 待处理来源只能复看原片

展开“待处理来源与暂留原因”，查看已有原因。当前批次记录 19 个 pending 和 3 个 held，详见[本轮生成结果](../../docs/subvideo-aligned-results.md)。

待处理开发来源只有在原片路径和摘要可验证时才显示“查看原视频与源标注”。该入口只读播放完整源视频并展示参考标注，不生成候选、不修改源标注，也不保存片段审核。返回候选列表选择片段后，才能填写并保存候选决定。

三个 held 来源 `video_0002`、`video_0015`、`video_0050` 只展示暂留原因，不开放原视频入口。工具拒绝固定 test、开发归属不明的来源及关联 test／归属不明来源；不能通过换路径绕过。候选 SHA 与清单不符时拒绝播放和保存；路径缺失、符号链接或清单启动后变化也会阻止相关操作。遇到这些提示先保留错误，核对媒体、划分与清单身份；工具不会自动修复、重新生成或继承旧审核。

## 4. 导出最新决定或完整历史

导出命令不需要服务运行，读取同一份独立记录库。以下命令仍在任务工作树执行，使用与启动时相同的 `--project-root`、`--records`。输出文件名已存在时，shell 的 `>` 会覆盖该导出文件；需保留旧快照时先换新文件名。

导出当前候选身份下的最新决定：

```bash
cd /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench
mkdir -p /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review
python -m script.subvideo_review.server \
  --project-root /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune \
  --records /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review/reviews.json \
  export > /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review/reviews-latest.jsonl
```

最新导出每个当前候选一行，保留最新状态，**不只导出已确认记录**；无当前修订的候选有 `unreviewed` 占位行。若旧确认后又保存了草稿，最新导出呈现草稿，不会自动退回采用旧确认。其他身份的历史只列关联修订 ID，不作为当前标签。服务运行时也可打开 [最新 JSONL 导出链接](http://127.0.0.1:8765/api/export)。

导出记录库中的全部不可变修订：

```bash
cd /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench
mkdir -p /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review
python -m script.subvideo_review.server \
  --project-root /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune \
  --records /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review/reviews.json \
  export --all-revisions > /Users/pcoffeep/AgentPlayground/active-projects/TensileAgent-Finetune-review-workbench/data/subvideo-review/reviews-all-revisions.jsonl
```

完整历史包含记录库内旧身份和旧修订，不添加未审占位行；用于重现显式锁定的旧 `review_id`。服务运行时对应 [完整历史 JSONL 导出链接](http://127.0.0.1:8765/api/export?all_revisions=1)。它不会替评分清单选择修订，也不会自动形成正式测评或发布数据。

审核记录库 `reviews.json` 与导出 JSONL 用途不同；不要把 JSONL 覆盖到记录库路径。记录库还会使用同目录下的 `.lock` 文件，保存时以新修订追加历史。评分文件格式、修订锁定及合成示例以[五类评分工具说明](../five_label_eval/README.md)为准；本说明不提供未经该接口说明确认的清单生成命令。评分工具不自动采用最新修订，实际模型输入人审也须另行记录，不能由完整片段审核替代。

## 5. 结束与下一次继续

关闭浏览器标签页只停止当前页面，不会关闭终端中的服务。先确认页面显示保存成功；需要停服务时，在启动服务的终端按 `Ctrl+C`。尚未保存的输入不会因关页或停服务写入记录库。

下次使用同一启动命令、清单和独立记录路径，可读取已保存的当前修订。本地提交不是独立备份；清理或迁移前保留审核记录库、所需历史导出及对应清单／媒体身份，并核对新的实际路径。不要只凭同名候选恢复标签。

本工具及本说明没有运行真实模型。用户确认标签不等于完成模型输入检查或能力测评；媒体生成、训练、正式测评及发布仍须另获对应授权。所有拟发布片段须人工审核，疑问、退回、草稿及未审记录不能自动发布。

**失效条件：** 启动参数、页面按钮、保存／导出结构、身份隔离、媒体访问边界或标签规则改变后，须同步更新本说明并重新验证受影响流程；本机工作树或媒体目录改变后，先修正示例路径。本文不能代替真实媒体审核、模型运行和发布验收记录。
