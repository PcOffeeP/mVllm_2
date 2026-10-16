# 开发输入、交付参数与资源预算运行前核验

日期：2026-10-16。执行者：Codex。Mac起始 `feat/evaluation-development@57670abc`，工作区干净。用户要求先完成无需真实模型的核验与准备；不再追查 `self.post_init()`，不改写基座，不运行模型、训练、真实评测或使用test。本轮不创建正式model/eval/claim，不同步远端代码、安装环境、改变服务或推送合并。

## 开发输入与分母

训练机正式开发对象为显式 `data-v4.1-r2`，Prompt候选为显式 `prompt-v4.1-r1`；选择对象用于核验，不等于正式运行已冻结。限定只读采集的六份开发文件对应：

| 折 | train候选 | validation候选 | train来源视频 | validation来源视频 |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1253 | 425 | 56 | 29 |
| 1 | 1014 | 664 | 56 | 29 |
| 2 | 1186 | 492 | 63 | 22 |

开发候选全集1,678，与候选metadata全集精确一致；来源视频85。三折validation合计及并集均为1,581，覆盖80个来源视频。其余97个候选从未进入这三份validation，这是既有划分的观察事实，不能把发布总量1,678当作validation分母；本轮不重划分、不删候选，也不根据未观察到非空 `train_only` / `augmentation` 标记自行认定其设计原因（采集使用get，无法区分null与缺键）。

候选及来源视频层级的每折train/validation交集、validation折间交集均为空。这只证明所观察来源层级的划分，不证明每个来源视频对应独立试件。更高试件/同一次实验的依赖关系缺直接依据，尚未冻结可用于正式评测的 `source_groups`；已向用户询问是否有对应记录，其余工作继续。

## Prompt与契约

实际 `prompt-v4.1-r1` 在store与训练机代码仓库字节相同，正文/输出字段与旧注册 `v4.1-concise-evidence-json-v2` 相同。六份数据内嵌system/user文本与正式Prompt不同；现行 `build_versioned_datasets` 会以显式Prompt重写这两段并保留assistant标签，所以内嵌文本不同本身不是错误。本轮只核代码路径，未调用构建器读取/哈希全部媒体。本轮探测的 `workspace/runs/<旧experiment>/input` 路径不存在，但该位置并未证明是此legacy训练的权威冻结输入目录，因此不据此断言历史输入已丢失；旧实际训练Prompt尚未建立绑定，不能由注册文本相同补推。进一步沿已知训练manifest的 `training_code_commit=f54d9ca617e455454f28e31ae058eda2dfdb5ec7` 读取本地Git对象，已恢复1,535字节历史训练YAML，SHA256 `036c9c69…` 与训练manifest精确一致；当前active YAML为 `d3fd4000…`，不能替代历史字节。恢复配置绑定明确开发dataset目录与template，但没有Prompt revision/version。主Agent随后仅通过正式Python只读探测manifest所载冻结目录的 `summary.json` / `dataset_info.json`（每文件64KiB上限），两处均不在场；未扩展搜索、不读取派生dataset消息、媒体、权重或test。该补充SSH退出0、远端Git前后仍干净，脚本与输出内嵌核对材料。原始冻结路径不在场不代表其他位置不存在，故这补齐了配置材料，仍未证明旧训练Prompt正文。

候选metadata记录契约hash `47e393…`，当前契约及旧Fold0 model manifest记录 `3798f0…`。使用本地现存Git对象 `97d36a90003957be3c13b5dbfc017452a308e54d` 提取历史契约，逐项比较共四处差异：三段 `analysis.system_prompt/user_prompt/retry_prompt` 和由其推导的 `contract_hash`；两份自报hash均经canonical JSON复算。结构化标签字段、Schema、枚举、校验规则、generation及video对象相同，但分析指导确有文字变化，不能声称任务语义完全等价。正式构建器没有要求候选metadata契约hash等于当前评测契约hash；允许渲染并不证明语义等价。本轮保留两个身份及其差异，不改写原契约或发布输入。完整摘要和结构路径见[核对材料](development-runtime-readiness-20261016.json)。

## 交付参数一致性

[源码与预算核对材料](development-runtime-readiness-20261016.json)绑定本轮本地源码摘要。开发评测使用 `AutoModel` 与独立 `video_loader`；受控性能及最终服务使用 LLaMA-Factory `ChatModel` 与同一服务adapter。源码中解码数值均为 `do_sample=false`、`num_beams=1`、`max_new_tokens=256`，8帧为配置上限目标；本轮未加载Processor核定实际属性。

仍存在具体的一致性前置：

- 抽帧：开发评测以实际解码且PTS合格帧数采样，服务使用stream声明帧数；`frames=0`、缺少stream.duration、声明/解码帧数不同等情形不保证同帧。典型条件下均匀采样公式相同不能证明所有输入相同。
- 图像切片：开发调用Processor传 `max_slice_nums=1` / `use_image_id=false`，服务MiniCPMV视频插件传 `max_slice_nums=2`。这是真实源码参数差异，尚无实际张量或效果结论。
- 请求策略：开发每样本调用一次；服务analysis无效输出最多三次，并把前次输出放入后续上下文。解码数值一致不代表调用量、语义结果或请求耗时等价。
- 量化/精度：配置允许 `null` 或4-bit，实际device、dtype、NF4及resampler状态须加载后验真。历史Fold0 merged BF16记录不能替本次选择变体。未创建冻结配置，也未把任一选择作为默认。

这些差异并入现有 EVAL-DEVELOPMENT / EVAL-PERFORMANCE 的“评测与交付先统一再冻结”要求。未改写任一路径，未以修改一个常量代替完整对齐，也没有重开评审tokenizer或基座方案。

## 样本与资源计算材料

当前一次调用的开发实现下，Fold0每模型425次；base与一个完整Fold0配对的算术量为850次。三折每模型族1,581次，base与三折模型配对为3,162次。这些是条件情景，不表示缺失折已存在、运行范围已选或已获执行授权。

按每次最多生成256 token，以上四种情景的输出token上限分别为108,800、217,600、404,736、809,472；不包含输入token、加载、服务重试和评审成本，也不是耗时估计。具体质量GPU小时预算保持未冻结：缺已核定交付变体、对齐后的请求策略及可信每样本耗时。本轮不调用模型补吞吐，不另造质量预算上限，不缩样适配预算。多数类参照为独立纯统计过程，不作为一次GPU模型调用。

评审runner另按匿名raw摘要去重：默认两名初判，分歧样本由第三上下文先独立判读再仲裁。设U为不同raw数、D为分歧数，正常调用量为 `2U+2D`；按源码一次基础设施重试限制的上界为 `4U+3D`。U/D须等待获准推理产生回答后才知；该复用不改变质量样本分母。这只是现行独立评审runner的调用预算边界，不是开发评审部署或耗时证明。

性能沿既定上限：预检1 GPU小时、正式20 GPU小时，后端600秒/客户端660秒绝对timeout，300秒为按时判据；正式至少100请求及30分钟连续处理。GPU预算、会话TTL与请求timeout同时约束；TTL、设备数量、暖启动/缓存/重复/重试与资源增长策略仍须针对获准真实会话显式冻结。性能上限不能充作质量运行预算，未构造真实会话或补造passed。

## 结果与验证边界

[输入盘点报告](development-input-inventory-20261016.json)保存实际文件摘要、状态、聚合结果及成功采集脚本、已知尝试记录；[无标签来源关系](development-source-map-observation-20261016.json)保存1,678条candidate→source_video及85来源的折分配，标记 `independence_asserted=false`，不能直接充当已冻结 `source_groups`。输入report与runtime材料通过SHA256绑定，映射文件SHA256为 `c49be5f688a6b22816739012c4f3c4fb1611d8dcf6798e5ce141ca340955d7b2`。

训练机本轮 `main@3f200461026a59676aaac7ea864f8fadb599688d` 前后干净。未同步Mac新增实现。最终成功采集读取13,365,233字节、远端0.161秒、退出0；先前错误payload前缀探测及两次脚本错误保留记录，未保留所有中间失败脚本，不能把最终读量当整个阶段累计IO。原始开发JSON只在远端内存读取，回传材料不含逐样本标签。release的 `training_allowed=true` 是项目内训练许可标记，无单独license字段，不据此判断法律许可。已完成准备不自动关闭 MODEL-DIAG、EVAL-DEVELOPMENT 或真实服务验收。后续继续依据[唯一TODO](../project-todo.md)推进。


## 收尾核查

独立reviewer对六份增量及直接依赖核查通过；null/缺键统计表述已修正并保留原采集器，legacy猜测路径的非权威性已明确。后续历史训练YAML恢复及两份metadata精确路径探测经有界增量复核通过，无剩余可执行问题。reviewer独立复算来源/折数、历史Git对象及canonical契约摘要、22份源码/配置文件摘要、评审调用边界和条件预算算术，未再SSH或执行采集器；远端事实仍以采集脚本、输出和摘要链为边界。

主Agent最终JSON解析、跨报告/映射摘要、310个本地文件链接/锚点、37个唯一任务标识及 `git diff --check` 通过。无模型/业务CLI/单元测试执行，不以文档核验替代真实质量或性能。更高试件问题尚无用户回复，保持未知，不按默认选项冻结。已完成材料不自动关闭父任务。本次Mac原子提交可由 `git log -- docs/results/development-input-runtime-preparation-20261016.md` 追溯，未push/merge。
