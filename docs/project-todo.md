# Project TODO

本文件是唯一项目任务台账，记录当前目标、差距、依赖和验收证据。维护规则见 [AGENTS.md](../AGENTS.md#todo-执行与维护)。固定标识不随排序或关闭改变。

## 当前状态与下一步

**当前阶段（2026-10-16）**：工程与流程基础设施基本建成，真实模型效果与独立验收仍缺证据。数据处理、审查交接、版本管理及训练/评测/服务入口已有工程实现与合成验证；真实 GPU 训练、真实 test、最终模型质量、真实服务成功路径与整机恢复均无证据，真实验收未升级。本节只保留结论与最新增量，逐条事实、状态、授权与限制以下方子条目及[最近维护记录](#最近维护记录)为准。

**开发侧输入与预算（2026-10-16，Codex；分母口径与试件分组详载 EVAL-DEVELOPMENT）**：起始 Mac `57670abc` 干净，训练机限定只读核实际 `data-v4.1-r2` / `prompt-v4.1-r1`；候选/来源视频、三折 validation、未进入 validation 的候选数及试件分组的分母与依据以 EVAL-DEVELOPMENT 与本轮准备记录为准，来源层级无泄漏不等于独立试件，试件分组依据为用户确认而非独立现场验真。仍未冻结：旧 Fold0 实际训练 Prompt 未证实；评测与服务存在切片1/切片2、抽帧边界及一次调用与最多三次重试的差异；质量 GPU 小时预算未虚填、实际变体未冻结，性能 1/20 小时为既定上限但不能冒充质量预算。详见[训练数据台账](results/training-data-ledger-20261017.md)「2026-10-18 并入原始核验材料」节（原开发输入核验材料已于 2026-10-18 并入台账并移除原文件）。未运行模型/真实评测/训练/test、不改基座，真实验收未升级。

**基座来源与评审侧准备（2026-10-15～2026-10-16，Codex；权威表述见 EVAL-DEVELOPMENT / MODEL-DIAG（基座来源）与 EVAL-HOLDOUT / EVAL-PERFORMANCE / EVAL-INTEGRATION（评审与显示测点））**：官方固定 revision 的配置/tokenizer/processor 与四份权重身份已比对，唯一代码偏差为实际基座构造函数多 `self.post_init()`；框架用途已静态核定，历史来源/动机追查按用户要求取消，不改写基座、不冒称原样官方快照，来源声明与正式登记仍不放行，见[固定来源核验](results/minicpm-fixed-source-audit-20261016.md)、[核验收口](results/minicpm-postinit-origin-purpose-20261016.md)。评审 tokenizer 的 HF NFC / GGUF NFD 差异经本机安装包 x86 词表实测复现，原生 arm64 server 未实测（[分词核验](results/ollama-tokenizer-verification-20261015.md)、[固定来源与材料](results/evaluation-tokenizer-materials-20261015.md)；原 [A/B 草案](plans/2026-10-15-review-tokenizer-alignment-design.md)已撤回为历史探索）；此后按用户授权以原方案完成本地兼容修复及两个模型各 9 条 golden 的 v2 受审映射，真实评审仍未执行（兼容修复记录，该记录已随 2026-10-18 清理移除）。评审隔离 canary 预检与显示测点桥接已在本机合成闭环通过，真实部署、独立账户、DOM 测点与真实密钥仍缺（运行前接线，该记录已随 2026-10-18 清理移除）。以上均为合成或无模型范围，不以合成结果授真实资格；不改判读、质量门与样本分母，不关闭 TLS 校验；不创建正式 eval/claim、不启动完整服务、不改外部客户端、不读真实 test、不生成真实回答。

**工程迁移、环境与测评准备（2026-09-14 / 2026-10-13 / 2026-10-15～16，Codex）**：数据处理及活动入口的工程迁移已解决（`5acebc27` 先推迁移分支再快进 Codeup main 并同步训练机正式代码，见[验证第67节](results/version-control-migration/verification.md)），不表示真实 GPU 训练、最终模型质量、独立 test、真实服务成功路径或整机恢复通过。DOC-INTEGRATION、REMOTE-STATE-REFRESH 已完成；ENV-ACTIVATION 已在训练机建立 `mvllm2`（Python3.11.17）并通过环境验收（部署记录，该记录已随 2026-10-18 清理移除），agent/cpm45 保留、未同步代码、未启动数据处理/训练/推理/评测，环境可用不等于模型质量或恢复通过；候选模型来源及实际运行授权仍须核定，指定 store 尚无新体系正式训练/评测/模型记录。测评[方案](model-evaluation.md)与[实施计划](plans/model-evaluation-implementation.md)已入库，主仓侧 A/B 及 C/D/E 工程接线与合成验证已完成并经独立复核，真实环境证据待补（[接线记录](results/evaluation-independent-performance-admission-20261015.md)、推进记录，该记录已随 2026-10-18 清理移除）；新准入统一要求独立质量与性能，旧六指标/七门不代表新协议；授权不包含真实模型调用、训练、test 使用、账户部署、外部 Agent 发包或性能运行，资产在场不等于部署或真实性能合格。

新体系正式入口为 `python -m versioning`，显式使用五类完整可读身份。train 数据分支用于三折开发验证和 full 训练，test 分支只用于最终独立测试；代码中的 `development` / `holdout` / `test_audit` 保留原值。旧媒体仍被新 store 引用，不得按“迁移完成”删除旧目录。

| 顺序/定位 | 固定标识 | 当前任务与状态 | 依赖、下一动作 |
| --- | --- | --- | --- |
| 已完成前序 | DOC-INTEGRATION | 已解决：正式整合文档目录 | 根README及三份正文正式启用，覆盖旧说明清理；独立核查通过，台账/设计/证据保留 |
| 已完成前序 | README-PUBLIC-INTRO | 已解决：项目介绍与新人快速开始 | 独立核查通过；验证第69节，无动态执行 |
| 已完成前序 | DOC-CONSOLIDATION | 已解决：文档及台账收敛 | 独立核查通过；验证第68节；候选手册及运行约定见文档整理记录 |
| 本轮已完成 | REMOTE-STATE-REFRESH | 已解决：限定范围训练机只读刷新 | 实时事实及缺口已记录；未执行同步、环境切换或模型运行 |
| 文档交付 | EVAL-PROTOCOL | 已解决：四项前置与多 Agent 判读已入库 | 本批独立源码核查及静态检查通过；只关闭文档增量，代码与真实验收未完成 |
| 本轮已完成 A | EVAL-SEMANTICS | 已解决：纯语义评分与封存判读基础 | 102项新增关键测试通过、独立复核通过；真实隔离归C，模型效果另验 |
| 开发接线 B | EVAL-DEVELOPMENT | 进行中（Codex）：工程接线已完成，待真实环境证据；输入契约未冻结，取得授权也不能直接开跑；开发评测侧已对齐、Prompt 已统一到 `prompt-v4.1-r2`，未重测 r0 | 开发data/Prompt/来源视频及分母已核；试件分组依据已由用户确认；旧训练Prompt绑定仍缺；切片、像素、时序组、Prompt版本已在开发评测侧对齐，抽帧实测定为同帧，重试按裁决保留；服务侧部署的像素/时序/超时预算未取证；下一步在训练机重测 r0 后冻结变体、计算质量预算，真实运行另授权 |
| 独立评分 C | EVAL-HOLDOUT | 进行中（Codex）：工程及无模型环境核验完成 | 实际tags/show、来源/依赖/18golden及canary已核；待真实独立账户/完整服务；真实test仍依赖HOLDOUT-BUILD |
| 性能接线 D | EVAL-PERFORMANCE | 进行中（Codex）：主仓工程已完成；外仓跨库测点、签名链与密钥托管未做，需跨库授权 | 会话/loader/双签名接收已接线；候选客户端缺原ID/nonce/单调显示测点/签名链，跨库实施及真实运行另授权 |
| 完整绑定 E | EVAL-INTEGRATION | 进行中（Codex）：工程已完成，待真实联合验收 | 77项准入/恢复/服务/开发合成通过；旧passed不继承新资格，真实服务另验 |
| 模型准备 | MODEL-DIAG | 进行中（Codex）：输入核验已推进，诊断未执行 | 基座静态身份及开发data/Prompt/分母已核；试件分组材料已备；旧训练Prompt和开发/交付差异待补，诊断未运行 |
| 独立验收前置 | HOLDOUT-BUILD | 阻塞：21 source 重建 test release 的构建条件 | 既定 21 source 已定位，使用资格已按用户 2026-10-17 裁决视为已定；缺构建授权、非语义来源清单及真实审查/媒体验证条件 |
| 本轮已完成 | ENV-ACTIVATION | 已解决：正式Conda环境与checkout绑定 | mvllm2 Python3.11.17、241锁项一致、doctor/pip check通过；真实业务未运行 |
| 备份验收 | RECOVERY-VALIDATION | 阻塞（Codex）：容量/已知位置已核，真实恢复未执行；待恢复目标路径与恢复操作授权（备份根已由用户 2026-10-17 裁决给定为 `/data`） | 缺恢复目标及完整模型、SQLite、外部依赖snapshot |
| 后续训练 | FINAL-TRAIN | 阻塞：full 最终候选 | 按新门槛三折通过、test 构建冻结与预注册准备就绪及适用训练授权 |
| 总体验收 | MODEL-QUALITY | 阻塞：最终质量及晋级 | FINAL-TRAIN、HOLDOUT-BUILD、新语义验收和性能/绑定证据；真实服务及批准另核 |
| 非阻塞清理 | MODEL-ARCHIVE | 阻塞（主 Agent）：归档与条件清理准备；待完整迁移核验与独立备份达成 | 证明完整迁移、冗余、引用退出及诊断保护；候选未删除 |
| 目标裁决 | RELEASE-POINTER | 待确认：旧指针目标适用性 | 新入口已显式选版本；不恢复旧写入、不阻塞新数据选择 |
| 本轮已解决 | CONTRACT-NAMING | 已解决：候选契约与下游发布复用边界已澄清 | 两module仅docstring、AST行为相同；索引/数据指南一致，不重命名或改身份 |
| 口径裁决 | TEST-SOURCE-REUSE | 待处理：21 个既定 test source 重建 test release 的口径已裁决，真实构建未执行 | 三条边界（不入任何训练分支／非盲参考性口径／结果不回流）约束构建与报告；构建仍待授权、人工审查与真实媒体验证 |
| 归档纪律 | ARTIFACT-RETENTION | 进行中：备份节奏、过期文件管理与清理红线已定，待按节奏执行 | 首次适用待全量训练+评测归档；清理红线三项不得进入任何清理候选 |
| 后续主任务 | R2-REALTRAIN | 待处理：用 `data-v4.1-r2` + `prompt-v4.1-r2` 完成 fold 0 → 三折真实训练与评测，未开始 | 待清理收尾后；依赖 r2 训练 YAML 冻结 + 用户 GPU 授权；预算均为推算，需首 50 步实测校准 |

MODEL-QUALITY 是总目标。先冻结 test 数据及预注册准备，再训练最终候选；绑定 model/eval 的一次性 claim 在最终身份确定并获测试使用授权后、首次模型调用前建立。不能倒置为先测试通过才允许训练该候选。

## 2026-10-17 用户裁决：执行口径与全局纪律

本节集中登记用户在 2026-10-17 作出的一批裁决，逐条来源均标注「用户 2026-10-17 裁决」。测试集口径与产物归档纪律的完整边界分别见固定标识 `TEST-SOURCE-REUSE`、`ARTIFACT-RETENTION`；本节只记跨任务通用部分，不改变任何既有验收阈值或门限数值。

- **测试集口径（用户 2026-10-17 裁决）**：虽然存在“已用于测试的数据不得再用于后续训练”的设计规范，但项目数据总量有限，明确使用既定 21 个 test source 重新构建一份 test release 用于最终测试；三条边界（绝不进入任何训练分支、最终测试结论为非盲参考性口径、test 结果不得回流）以 `TEST-SOURCE-REUSE` 为准。HOLDOUT-BUILD 原解除条件中的「核清既定 test source 独立使用资格」按本裁决视为已定。
- **当前模型定位（用户 2026-10-17 裁决）**：`v4.1-agent-pipeline-fold0-r1` 冻结为参考基线 r0，禁止参与任何准入、晋级或 production alias，仅作后续训练的配对比较锚点。
- **数据处理粒度（用户 2026-10-17 裁决）**：复用已冻结的 `data-v4.1-r2`（1,678 候选 / 85 来源），不重做 ROI 人工审查；所称「全流程重跑」指训练 → 三折 → 评测 → 性能。
- **产物保存与身份四元（用户 2026-10-17 裁决）**：数据/媒体/审查包走现有 DVC（data 身份）；Prompt 正文与身份、训练评测配置 YAML、四字段契约、三折划分进 Git（按 prompt/train/eval 身份钉住）；adapter/merged 与实验指标走 Registry + MLflow。每次 train/eval 记录必须同时引用 data 身份 + prompt 身份 + 代码 commit + 配置哈希，使「哪份数据、哪个 Prompt、哪套配置、哪版代码」可反查。
- **阶段硬门（用户 2026-10-17 裁决）**：每个阶段进入下一阶段前，上一阶段产物必须先落盘并记录身份；未落盘不得进入下一阶段。
- **备份根与节奏（用户 2026-10-17 裁决）**：`/data`（`/dev/sda1`，3.4 T 空闲，独立于主仓 `/dev/nvme0n1p2`）为第一级备份根，1 T 移动硬盘为第二级；节奏为每完成一次全量训练+评测归档一次，不做持续同步；备份须另开目录（如 `/data/mVllm_2-backups/`），不得混入 store 内部。细节见 `ARTIFACT-RETENTION`。

## 待处理、待确认与阻塞事项

### R2-REALTRAIN — 用 r2 数据与 Prompt 完成三折真实训练与评测

- **状态/来源**：待处理（Pi，2026-10-18；未开始，排在当前清理收尾之后）；用户 2026-10-18 指示把「新一轮 R2 数据的真实训练与评测」登记进台账，并标注它排在清理收尾之后、后续按时间推进。父任务 FINAL-TRAIN / MODEL-QUALITY（三折开发验证口径）；本条不改变这两个父任务的阻塞状态，不改任何既有阈值。
- **目标**：用 `data-v4.1-r2` + `prompt-v4.1-r2` 完成 fold 0 → 三折的真实训练与评测，产出新体系（`python -m versioning`）的第一条 `train` 记录、第一个 `model` 身份、第一份正式 `eval` 记录。本轮不含 test 分支与 full 训练。
- **已就绪（逐项带证据）**：
  1. **数据**：`data-v4.1-r2` 为 sealed / development / `training_allowed: true` / active，1,678 候选 / 85 来源；三折 1253-425、1014-664、1186-492（每折 train∪val=1678、交集 0、dup 0）。证据：`docs/results/training-data-ledger-20261017.json`（`state`、`status`、`training_allowed` 字段）与同目录 `.md` 的分折表。该台账为训练机只读实测 + 本机只读统计，未重跑训练。
  2. **Prompt（Git 记录 + store 注册）**：Git 侧 `records/prompts/prompt-v4.1-r2.yaml` 已建（sha256 `9c6ec527…26f9`，1808 字节），store 侧 `prompt create` 已执行且两侧 sha256 相同；其 system/user 与契约 `3798f00c…38ab` 正文逐字节一致。证据：仓库外，他机不可达 `~/pi-workspace/mVllm_2-audit/dev-eval-alignment-20261017.md`（Git 侧正文与哈希）、`~/pi-workspace/mVllm_2-audit/eval-r0-realign-20261017.md`（训练机 `prompt create` EXIT=0、两侧哈希一致）。
  3. **开发评测侧预处理**：8 帧 → 8 组、时序组全 `-1`，训练机 CPU 实测六项断言全 PASS（`all_pass: true`）；**视觉 token 512 是推导值，服务侧一致性仍是同一 `mm_plugin` 路径的推定，像素、时序与超时预算未取证**。证据：仓库外，他机不可达 `~/pi-workspace/mVllm_2-audit/eval-r0-realign-20261017.md`（六项断言逐项实测）；服务侧推定的边界见同前 `dev-eval-alignment-20261017.md`。
  4. **门禁路径**：已摸清全链 61 行门禁（C1）与从零训练按实际报错顺序 14 道门（C2）的顺序、位置与触发条件。证据：仓库外，他机不可达 `~/pi-workspace/mVllm_2-audit/pipeline-and-gates-20261018.md`。该报告 C3 九行汇总只把 2 行判为当前已满足，且限于 data/prompt 的**产物存在性**；prompt 双份字节一致在 C3 中列为当前未满足（该项已由上述训练机 `prompt create` 取证），train/model/eval/serve 侧前置全部当前未满足。
- **2026-10-17 已完成进展（Pi，训练机侧；未训练、未评测）**：
  1. **代码同步**：训练机 `feat/evaluation-development` 从 `6cdda256` 经 `git bundle` 以 `--ff-only` 快进到 `32bd5138`（`32bd5138c08a886f1d3a77fb9d4f5542134fe451`），两端 bundle sha256 逐字符相同（`e57a8f033bfc11334707f7c07107f83d88ea74bdde815cc1c37642dba099de23`），未产生合并提交，同步后 `git status --porcelain` 仅 `?? store/`。
  2. **Prompt 已注册进 store**：训练机执行 `python -m versioning prompt create --root <store> --version prompt-v4.1-r2 --protocol v4.1 --definition records/prompts/prompt-v4.1-r2.yaml`，EXIT=0；store 侧与 Git 侧 sha256 同为 `9c6ec5274cd804d21bf54585343344a67443f94b8396fe5bc01f41ab2de7269f`（1,808 字节），`prompt show` EXIT=0；`prompt-v4.1-r1` 未被触碰，sha256 仍为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`（1,200 字节）。
  3. **CPU 复验六项全部通过**（`all_pass: true`；全程 `CUDA_VISIBLE_DEVICES=''`、`torch.cuda.is_available()=False`、未加载任何权重）：`temporal_ids` 全 `-1`（flat `[-1]×8`，depth `1/8/1`，由 processor 回填）；8 帧 → 8 组、每组 1 帧；帧索引 `[0, 54, 109, 164, 218, 273, 328, 383]` 与生产形态 A8 逐项相同（PTS 差值全 0.0，解码总帧 384）；规整尺寸 `(229, 286)`（`tgt_sizes` 全 `[36, 29]`，单帧 `pixel_values` 为 `(3, 14, 14616)`）；`max_slice_nums` 生效值 2；切片次数 0（`get_sliced_grid=None`、`len(get_sliced_images)=1`）。
  4. **评测被阻断的事实**：store 只有 `records/prompts/`（r1/r2），`store/records/{trains,models,evaluations}` 与 `store/workspace/{mlflow,evaluations,models}` 均不存在，因此 `eval prepare` 无法通过——`versioning/registry.py` 的 `get_model` 处必然抛 `RegistryModelNotFound`。本轮只做只读核验，未执行 `eval prepare` / `eval run`，**GPU 推理耗时 0，未产出任何 425 指标**；解除阻塞需先有真实 train 记录，再由该 train 执行 `model register`。
  5. **证据来源**：`~/pi-workspace/mVllm_2-audit/eval-r0-realign-20261017.md` 与原始输出副本 `~/pi-workspace/mVllm_2-audit/_raw-20261017-p13/`；两者均在仓库外、他机不可达，**不写作链接**。
- **未就绪（明确差距）**：
  1. **r2 训练 YAML 不存在**：训练机 `finetune/` 下没有任何引用 `data-v4.1-r2` 的配置；「3 epoch / bs 1 / ga 8 / eval 每 50 步」是沿用历史 run 的假设，必须先冻结成三折 YAML 才能过 `train prepare` 的配置门。
  2. **GPU 训练授权未给**：训练机真实训练授权属执行纪律，无代码门可替代。
  3. **训练输入其余门未逐项复核**：`train prepare` 还会挡 data 验证路径（committed receipt 或显式 `--data-inputs`）、折计数与成员和 release 元数据一致、媒体根、基座完整清单、`environment` YAML 与 `git_commit`；`pipeline-and-gates-20261018.md` 的 C2 把其中多道判为「待核」或「当前未满足」，均未在训练机逐项跑过 prepare。
  4. **训练预算未定，全部为推算**：3 epoch 按 epoch-based 语义推算 1,290 步（468/378/444）× 10.94 s/step，加 27 次 eval（训练内 24 次 + 每折训练后最终 3 次），三折约 **5.78 h**；单折约 1.86–1.99 h；2 epoch 约 3.93 h；若改为 1 epoch，按 5.78 h 线性折算三折约 1.9 h（该折算值由本条给出，重算报告只给到 2 epoch 的 3.93 h）。以上**均为推算，非实测**，且 10.94 s/step 是在旧 prompt/release 下测得，须用 r2 首 50 步实测校准。口径说明：`docs/results/training-data-ledger-20261017.json` 的 timing 段用的是 eval-inclusive 14.9309 s/step 与 ceil 语义，得 1,296 步 / 5.3751 h，与本条 10.94 s/step + 27 次 eval 的口径不同，两个数字不可互指矛盾。证据：仓库外，他机不可达 `~/pi-workspace/mVllm_2-audit/training-time-recalc-20261018.md`。
- **依赖**：清理收尾完成（本轮清理批次，非 `MODEL-ARCHIVE` / `ARTIFACT-RETENTION` 项下执行，收尾状态以清理批次记录为准）+ r2 训练配置冻结 + 用户 GPU 授权。
- **下一动作（按序，不跳步）**：① 冻结 r2 训练 YAML（三折参数、epoch 数、eval 频率、`cutoff_len`/`video_maxlen` 等），同轮补齐 `environment` YAML、`git_commit`、媒体根与 data 验证路径；② 首 50 步冒烟实测 s/step 校准预算 ③ 跑 fold 0 ④ 三折 ⑤ 各自 export → `model register` → `eval prepare`/`run`。
- **验收标准**：三件产物齐全——新体系第一条 `train` 记录（`records/training/<train>/manifest.yaml` + `training-evidence.json`（落在 `workspace/runs/<train>/` 并作为 MLflow artifact 上传，与 manifest 不同目录））、第一个 `model` 身份（Registry Model Version）、第一份正式 `eval` 记录（`records/evaluations/<eval>/manifest.yaml`）；每个结论可追溯到 data 身份 + prompt 身份 + 配置哈希 + 代码 commit；全程不读 sealed test、不跑 full（除非另有授权）。
- **证据位置**：`docs/results/training-data-ledger-20261017.json`、`docs/results/training-data-ledger-20261017.md`、`docs/results/model-r1-effect-profile-20261018.md`、`docs/results/model-r1-effect-profile-20261018.json`；以下四份在仓库外，他机不可达，不写作链接：`~/pi-workspace/mVllm_2-audit/pipeline-and-gates-20261018.md`、`~/pi-workspace/mVllm_2-audit/dev-eval-alignment-20261017.md`、`~/pi-workspace/mVllm_2-audit/eval-r0-realign-20261017.md`、`~/pi-workspace/mVllm_2-audit/training-time-recalc-20261018.md`。
- **限制声明（不得越界引用）**：① **R1 与 R2 不可直接比较**——R1（`v4.1-agent-pipeline-fold0-r1`）是 legacy 命名、旧体系产物，R2 是新体系第一代，中间没有任何记录把两者接起来；② R1 的全部 425 数字测于 1 组融合 / 64 token 的旧预处理链路，与生产链路（8 帧 → 8 组、视觉 token 512）口径不同，数值差异不能归因于模型能力；不可比的原因在预处理链路而非契约哈希——R1 的 425 记录中也有在 `3798f00c…` 契约下产出的（见 `docs/results/model-r1-effect-profile-20261018.md`），不得以契约相同或不同解释可比性。③ 本条登记不构成训练、评测或读 test 的授权。
- **2026-10-18 实测（换管线重测 R1，未训练）**：用 8 帧 / 8 组 / 512 视觉 token 的新管线重测 R1 同一模型、同一数据、同一 Prompt，425 条结果：已断裂仍 **0/33**，joint 由 **41.18%**（旧口径 1 组 / 64 token）升至 **50.59%**，发生断裂 recall 由 45.83% 升至 59.72%，strict_valid 0.9906，临界未断裂 recall 由 0.2281 降至 0.1053。结论：**换管线不是零召回的原因**；已排除管线、模型版本、数据、评测标准四项因素。边界：仓库内 `docs/results/model-r1-effect-profile-20261018.md` 是**旧口径**结果，新口径 425 结果**尚未入库**，仓库内无对应结果文件，补登记后才可作为可追溯证据；本条不据此声称本机可复现。
- **标签判据现状（2026-10-18 订正）**：标签判据已在契约与 Prompt 中定义（非缺失项）；待验证的是标注与可见画面的一致性、ROI 帧的视觉可辨识性、以及模型判档逻辑三项。权威语义不变：**已断裂 = 首帧即断；发生断裂 = 片段内发生；区别是时间位置，不是严重程度**。
- **标签存疑（2026-10-18）**：抽样发现部分「已断裂」样本首帧无可见分离，比例高且分散；标签由 `event_time` 几何规则推出、非视觉判据。此处数字仅表示与这批标签的一致程度，**不得作为模型能力结论**。
- **R2 开训前置（全部满足方可开训；任一未过不得开训）**：① 全链路验证 14 环节全部 passed（`docs/plans/2026-10-18-full-chain-validation.md`）；② 标签重建完成（PB-015 closed，新 release_id 落盘）；③ 门禁 v2 定稿（分层 + L0 清单 + 两轴指标 + 塌缩检测 + 门槛由代价比 k 推导）；④ T1 判读器可用并完成校准（判例集 ≥100 条，与人工一致率 ≥0.85）；⑤ 门槛 k 值由用户给定（不沿用现有 0.65 / 0.4006 等来源不明的数值）；⑥ 预算由首 50 步实测校准（现有 5.78 h 为推算）；⑦ 用户 GPU 授权。前置未完成前开训，评测结论将无法与 R1 同口径比较。
- **2026-10-18 决策（用户裁决，本轮不改实现）**：T 判读器使用 **API 调用**（本地只能跑 89B 级模型，性能不足）；M3（相邻档位混淆，如「已断裂 → 发生断裂」）**不计入严格正确，但必须单列报告**：它是零召回的直接影响指标；**格式合法率降为参考指标**，允许模型返回非标准字段，只要语义可识别，形式校验仍由脚本执行，但不再作为门禁的通过条件；本轮**不改字段、不改实现、不改 Prompt**；设计定稿后开新分支一次性改造测评与门禁，设计稿见 `docs/plans/2026-10-18-evaluation-pipeline-redesign.md`。
- **2026-10-18 设计稿入库（Pi）**：测评链路与门禁 v2 设计稿已入库（`docs/plans/2026-10-18-evaluation-pipeline-redesign.md`），其中标签判据、两轴指标、门禁分层为 R2 前置；两轴指标接门禁、门槛 k 值仍待定。

### EVAL-DEVELOPMENT — 基座、已完成单折登记与开发门槛

- **状态/来源**：进行中（Codex，2026-10-15；工程接线已完成，待真实环境证据；输入契约未冻结——旧 Fold0 训练 Prompt 未证实、质量预算未对齐，取得授权也不能直接开跑；原列的开发切片1与服务切片2、抽帧边界、一次调用与最多三次重试差异已于 2026-10-17 定位，并在开发评测侧完成对齐：切片、像素与时序组按训练侧口径统一（服务侧为同一 `mm_plugin` 路径的推定，未取证），Prompt 统一到 `prompt-v4.1-r2`，抽帧边界经实测确定为同帧，重试按用户裁决保留，详见下方「开发评测侧对齐训练/服务 + Prompt 统一 r2（服务侧仅为推定，待取证）」条；r0 尚未重测，输入契约仍未冻结）；父任务 MODEL-DIAG；用户授权 A/B 代码及合成验证，未授权真实模型执行。
- **已实现事实**：同一 Registry 的 base/trained 互斥来源及实际字节快照，FINISHED 完成折独立诊断登记且父 partial 不变；显式 semantic-v4.1 的 prepare/validate/run/score/export、完整来源组映射、每折与 pooled 门、多数类及真实 base 配对 CLI、MLflow/manifest 重验和来源备份兼容。base/诊断不授服务 alias 或生产资格；原 strict 历史仅按已核精确适配保留原义。
- **验收标准**：不伪造 train/缺折/中途 checkpoint；诊断仅对应完整 validation。每折 macro≥65%、各状态≥50%，完整三折 pooled joint≥50%、机制F1≥50%、位置F1≥60%；特殊类报告。双方同媒体/Prompt/抽帧/生成与真实基座字节，缺类/缺折/漂移/评审未完成不放行。完整链路来源、分母及判读尝试可追溯。
- **本轮验证**：主 Agent 新增关键集102 passed（64.23s，退出码0）；独立 reviewer 最终14项接线专项均通过（13+1，两次间只修测试fixture chmod），包含完整三折 passed、单折坍缩 failed、导出/Registry、诊断父 partial、旧 strict/holdout 兼容、attempt 篡改/改判/超额 retry 拒绝。无剩余可执行问题。最终受影响eval回归315 passed / 1 skipped（正常退出码0）；并行实施广回归1028 passed / 1 skipped / 2 failed，两失败已在最终关键集覆盖通过，解释器退出GC中止清理限制如实记入证据。完整数字见[实施记录](results/evaluation-development-implementation-20261015.md)。
- **本轮输入核验（2026-10-16）**：训练机main@3f200461干净，较本轮起始Mac少17提交，未同步。基座23个白名单文件与旧Fold0 adapter共24文件完整SHA已核；四片权重共17,391,890,184字节与官方main LFS观察一一相同。后续本轮已完成HF固定revision逐项比对，配置/tokenizer/processor和四权重身份匹配；README/额外配置由官方MS历史树解释，构造函数多`self.post_init()`仍不同，不能把实际目录作为未经修改的官方快照登记。未补造source-provenance，不据此运行。指定store的model/train/eval与默认MLflow记录未创建，符合尚未开展新体系业务阶段，不造空记录补目录。证据见推进记录（该记录已随 2026-10-18 清理移除）。
- **固定来源收口（2026-10-16）**：官方HF `daef484c35ec93210ec93c5e901f8f3e9b78ee34`完整23tree对象Gitblob核验通过，tokenizer正文及4权重固定LFS身份已核。训练机19小文件及缓存元数据只读采集，7仓内代码文件AST闭包可追；官方MS `2626e837a54905aab70fae9325153ef3454387ab`历史树与cache23条revision对应、22/23身份相同，只有`modeling_minicpmv.py`新增`self.post_init()`与官方来源不同。后续已核框架用途，历史来源/动机追查按用户要求取消，见[核验收口](results/minicpm-postinit-origin-purpose-20261016.md)。未知修改不能用verified_by空泛签字补过，既有来源helper在未附证明时实际拒绝。见[固定来源记录](results/minicpm-fixed-source-audit-20261016.md)。
- **开发输入现场（2026-10-16）**：r2 sealed/development/active、training_allowed=true；六份开发JSON与metadata候选全集1,678精确匹配，85来源视频。validation三折425/664/492、合计1,581且无候选/来源视频跨折交集；97候选不在任何validation，不改既有划分或以1,678作validation分母。正式Prompt在store/代码仓库字节相同、正文与旧注册v2相同；正式构建器显式重渲染system/user并保留标签，数据内嵌Prompt不同不是自动错误；已从记录的训练代码Git对象恢复与manifest摘要一致的旧Fold0训练YAML；原冻结目录两份摘要不在场，实际训练Prompt仍未证，不以当前active YAML替代。后续用户明确每个试样仅对应一个来源视频且无重复，已按source_video备齐1,678候选/85试件组材料；物理身份依据为用户确认，非独立现场验真，正式eval输入尚未创建/冻结。契约字段差异与代码行为分开记录，不补造语义等价。见[训练数据台账](results/training-data-ledger-20261017.md)（原开发输入核验材料已于 2026-10-18 并入台账并移除原文件）。
- **交付一致性前置（2026-10-16）**：解码数值一致但开发/服务Processor切片为1/2、抽帧元数据边界不同、一次调用/analysis最多三次且追加上下文；受控性能复用服务链路。未选择改任一路径、未声称整体等价，按既有“与实际交付统一后冻结”要求保留前置。质量预算已按425与1,581完整validation提供条件算术量，GPU耗时与量化/device/dtype未冻结；性能上限不能冒充质量预算。本条记录的是 2026-10-16 当时状态；2026-10-17 已在开发评测侧对齐切片、像素与时序组并把 Prompt 统一到 `prompt-v4.1-r2`，抽帧边界经实测确定为同帧，重试按用户裁决保留，更新后的现状见下条。
- **开发评测侧对齐训练/服务 + Prompt 统一 r2（服务侧仅为推定，待取证）（2026-10-17，Pi；未重测 r0）**：代码改三处，判分逻辑、分母与阈值零改动。像素与常量：`finetune/validation/constants.py:45-52` 新增 `VIDEO_MAX_PIXELS=65536`、`VIDEO_MIN_PIXELS=256`、`VIDEO_SLICE_MAX_NUMS=2`、`INFERENCE_TIMEOUT_SECONDS=600.0`，并以 `TEMPORAL_FUSION_LEGACY=False` 作为旧行为回退开关。抽帧分组与像素规整：`finetune/validation/video_loader.py:20-31` 的 `load_video_frames` 默认 `temporal_fusion=False`，返回 `temporal_ids=None`（`:114`），交给 processor 回填全 `-1`，逐帧成组；8 帧即 8 组，视觉 token 为推导值 512（8 帧 × query_num 64，需加载 resampler 前向才能实测）。这与训练侧 LlamaFactory `MiniCPMVPlugin` 一致（训练机 CPU 实测复刻 `patch_processor` 与 `mm_plugin`）；服务侧经 `pipeline/server_proxy.py` → LlamaFactory `ChatModel` → `hf_engine` → `mm_plugin` 共用同一路径，属推定。改动前返回 `[[0]*n]`，是单组时间融合，1 组等于 64 token。同文件新增 `_regularize_frame_pixels`（`:121-141`），在 `:112` 逐帧调用：先按 `video_max_pixels` 下采样、再按 `video_min_pixels` 上采样、最后转 RGB，逐语句对齐 `LlamaFactory/src/llamafactory/data/mm_plugin.py:218-235` 的 `_preprocess_image`。运行时：`finetune/validation/model_runtime.py:129-131` 的 `max_slice_nums` 由硬编码 `1` 改为常量 `2`（`finetune/validation/constants.py:48` 的 `VIDEO_SLICE_MAX_NUMS`，取训练侧 `MiniCPMVPlugin` 的同名默认值）；像素预缩后 `w*h/448²<1`，两侧都不发生切片，服务侧该参数的实际部署取值本轮未取证。`finetune/validation/model_runtime.py:172` 新增单次推理超时调用，实现见 `:188-212`，默认 600 s。该 600 s 取自受控性能会话的请求级绝对上限（`versioning/performance.py:535-538`，`:538` 注释写明该绝对超时覆盖全部 adapter 重试；`:577-578` 为二次校验），不是服务端单次推理预算；拿它当单次推理预算属于更宽松的近似，不能声称与服务后端逐字一致。超时抛 `InferenceTimeoutError`（`:204`）；被打断的 `generate` 可能残留未释放显存，且 SIGALRM 在阻塞调用期间为延迟投递（best-effort，非硬保证）。该异常按既有 runtime failure 口径记录（`finetune/validation/run_evaluation.py:90-92` 写入 `runtime_error`、`:194` 计数、`:256` 写 `runtime_failures.csv`），不重试，保持开发侧严格单次的属性；非 POSIX 主线程无法强制超时时 fail-closed 拒绝执行（`:197-200`）。Prompt：`records/prompts/prompt-v4.1-r2.yaml` 用 `versioning.prompts.create_prompt` 正式 API 写入，键序与 r1 一致（version/protocol/system_prompt/user_prompt/output_fields）；其 `system_prompt` 与 `user_prompt` 正文逐字节等于运行期契约 [tensile_vlm_v4_1.json](../pipeline/contracts/tensile_vlm_v4_1.json) 的 `analysis.system_prompt` 与 `analysis.user_prompt`，该契约 `contract_hash` 为 `3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab`。两侧 `system_prompt` sha256 同为 `c9cde7a213b6a118b4ea06b5b27d38993c71e48a49ec3ce78502226afc328980`（285 字节），`user_prompt` sha256 同为 `d06d167b7d67e09c9518f364c175e2d3678b241ff1cc10ae5be1bc3afd9b1a45`（1360 字节）；r2 文件 sha256 为 `9c6ec5274cd804d21bf54585343344a67443f94b8396fe5bc01f41ab2de7269f`（1808 字节）。演进关系：`prompt-v4.1-r1`（concise-v2 内容）作为历史版本保留不删、未修改，文件 sha256 仍为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`；`prompt-v4.1-r2` 承载服务版正文，是现行目标。`analysis.retry_prompt`（sha256 `651e0f1036b4141ec3a27c5ea858ea874a17f92a6b56a6ac0710868aa7597068`，224 字节）只属于服务/运行期重试链路，不是训练输入，因此没有写进 r2 记录，r1 也没有该字段，不为它新增字段，记录无漏项。抽帧边界：本轮未改代码层积分口径，实测也未命中残留差异，因此处置为同帧。判定依据是训练机 CPU 实测：在 2 个源视频与 6 个生产子视频上，开发侧与训练侧复刻的 `patch_processor` 与 `mm_plugin` 送进的帧索引与 PTS 逐一相同，差异只在分组方式与像素重采样路径，后两者本轮已对齐。该实测报告 `~/pi-workspace/mVllm_2-audit/preprocess-probe-20261017.md` 是这条同帧结论的唯一依据，属仓库外材料、未入库、他机不可达，后续应择要入库以固定证据。残留差异（未改，实测未命中，风险已知）：`stream.frames == 0` 分支生产侧走 `linspace(0, video_maxlen-1, maxlen)`，开发侧用实际解码帧数；分母来源不同（生产侧取 `stream.frames` 元数据，开发侧取实际解码帧数）；`video_fps` 开发侧硬编码 `2.0`，生产侧取 `model_args.video_fps`（当前值相同，来源不同）；开发侧额外做去重；采样区间为 `[start, end)` 半开。重试：按用户裁决不对齐，开发侧保持严格单次，服务侧 analysis 最多 3 次；本轮只把失败可观测、不重试的行为写实。重测入口为 `python -m versioning eval prepare/validate/run/score/export`，显式 `--root` 与完整版本身份，并使用 `--prompt-version prompt-v4.1-r2`；`finetune/validation/run_evaluation.py:48-54` 仍读 `pipeline/prompt_library.yaml`（旧 v2.1.0 schema），不在本轮范围，重测不得使用。`finetune/eval_run.py` 与 `finetune/eval_holdout.py` 本轮零改动，字节与 `versioning/eval_compatibility.py:9` 的 `STRICT_ADAPTERS` 一致，因此本轮不需要适配复核。验证：新增 `tests/test_dev_eval_preprocess_alignment.py`，先 14 项红、后 22 项全绿，`.venv/bin/python -m pytest tests/test_dev_eval_preprocess_alignment.py -q` 得 `22 passed`；其中 3 项是对生产语义的静态锚点用例，2 项是回退开关经 runtime 透传的用例，回退开关的 runtime 层透传已由变异实验证明有覆盖（删除传参即变红）。3 项静态锚点只锚定生产源码中的关键语句，不代表前向数值已实测。相关既有套件回归 `165 passed, 1 skipped`，skip 为既有 workspace data 缺失，与改动前基线相同。**尚未重测 r0**：重测须在训练机加载真实权重执行，本轮只做代码与 Prompt，因此仍未验证对齐效果、输入契约仍未冻结；旧的 425 与 1,581 指标全部产自改动前管线，与新管线不可直接比较，须重测后才能作为基线。本机验证仅合成与 mock，未跑真实模型、未加载权重、未 SSH、未在训练机执行任何推理。服务侧部署实际使用的像素预算、时序分组与单次超时，仓库内没有现场取证（部署清单 `pipeline/deployments/v4_1_intermediate_stage_b_8e1fdb09f8e6.json` 只记 `processor_version` 与 `max_frames: 8`），这是尚未闭合的缺口，不据此声称服务侧已对齐。
- **差距/依赖/下一动作**：构造调用历史来源追查已按用户要求移出待办；保留实际字节差异及来源登记约束。实际data/Prompt及来源层级已核；试件分组依据已由用户确认并材料化；旧模型实际训练Prompt绑定仍缺，开发/交付切片、像素与时序组、Prompt版本三项已于 2026-10-17 在开发评测侧对齐，抽帧边界实测定为同帧，重试差异按用户裁决保留。下一步是在训练机重测 r0（425 与完整三折），以验证对齐并冻结变体，同时按完整样本计算质量资源预算；取得适用授权后依次推进 baseline → 对应完整单折 → 完整三折。模型不可加载或来源不明停止，不任意换模型/Prompt，不用裸目录绕 Registry。
- **证据/限制**：[实施记录](results/evaluation-development-implementation-20261015.md)、[操作入口](../versioning/SCRIPTS.md#语义开发协议)、[模型工作流](model-workflow.md)。本轮 Mac 合成及微型文件验证，没有真实新登记、推理或质量结果；没有训练机证据时不关闭本条或 MODEL-DIAG。

### EVAL-HOLDOUT — 多 Agent 权限与独立质量接线

- **状态/来源**：进行中（Codex，2026-10-15；工程已完成，待真实环境证据）；用户授权批次C工程接线和合成验证，禁止真实模型评测或使用真实test；父目标 MODEL-QUALITY，衔接 HOLDOUT-BUILD；旧协议不重开。
- **事实与差距**：新独立协议已实现匿名包、独立封存/仲裁、exposed/consumed及最终12门，原strict七门不变。真实full/test资格、评审模型部署和真实运行证据仍缺；受审 tokenizer 等价映射已于 2026-10-16 以两个模型各 9 条 golden 的 v2 受审映射补齐并经离线 build/verify 通过，其现场真实性与独立审计仍未验证（见下文「兼容修复完成」）。
- **基本内容与做法**：匿名只读评审包发到独立低权限Agent工作区，只允许读本包/规则及写自身判读，不可读GT/视频/训练目录，初判互不可见；仲裁仅在自身初判封存后按授权读取分歧；受限端保留原raw、脱敏映射和审计。第三Agent先独立判读再处理分歧；用户复核也盲态。仅提示词或同一高权限账户不算权限隔离。已确认本机 Ollama：Qwen3.5 9B＋Ornith-1.5 9B，第三独立上下文仲裁，同时间一个模型；仅匿名回答＋字段/手册，无云端回退。8K上下文、512输出token、温度0，支持时关闭思考；120秒超时，运行故障最多重试一次；超长不截断。同族模型共错风险保留。
- **授权与恢复**：首次推理前claim锁定；现行score才读truth、完成提交才consumed是代码事实。新协议增加评审包发放即预测exposed记录，不能退回未使用；只能同model/eval/data/rules/包内容补传或继续判读，不重推理/改规则/清claim。普通MLflow/公开manifest保持gate与完整性；消费封存后授权验收负责人可看受限聚合指标，不用于调参，逐样本真值/错误例和公开详情不默认开放。
- **依赖/下一动作**：C工程已接入A纯评分和判读证据；下一步补核真实本地模型隔离部署及 runtime 输入（tokenizer 受审映射已按 v2 补齐，见下文「兼容修复完成」），真实运行依赖 HOLDOUT-BUILD、冻结full及单独使用授权。新权限设计已确定，不再重复讨论；账户/Agent环境部署并未执行。
- **验收标准**：新旧身份/协议分开、旧test不复用、授权不重置；越权读取/看GT改判/串看初判/漂移/重试挑答案均拒绝；最终所有门及覆盖证据合格才通过，缺类不放行，未获公开许可内容保持受限。
- **本轮进展**：工程已完成，先完成143 passed（新增33＋旧holdout110，71.40s，退出0），总deadline窄修后新增35＋兼容/CLI6共41 passed（29.61s，退出0）；独立reviewer新C35 passed（20.50s）。包括实际Mac sandbox拒绝探针、新最终门/缺类、显式聚合授权、封存/仲裁、exposed/consumed恢复、runtime采集及可信部署receipt。曾失败的受限启动已修，只证明合成worker隔离。HF raw prompt与token计数同构；每次判读120秒为覆盖metadata与生成的统一monotonic总deadline，终态不明持久阻后续；GGUF/HF受审等价映射/basis/golden案例必须未来现场提供（此句保留为兼容修复前的历史反证与当时限制，已被 2026-10-16 兼容修复与 v2 受审映射取代：两个模型各 9 条实际 golden 的 v2 映射已补并经离线 build/verify 通过，见本条目下文「兼容修复完成」；旧冻结证据不追认），代码验绑定，真实性信任独立审计者，不提供则拒真实执行。
- **前轮现场快照（2026-10-15，Codex；本轮补齐见下条）**：本机Ollama0.33.1已有两个批准标签，tags与manifest摘要匹配冻结digest，声明blob在场/大小一致；随后只读复验全部7个唯一blob SHA256，6.6秒内全部匹配且stat稳定，无未核项；未推理，ps无驻留模型。限定标准缓存和源码资产检查未找到匹配HF tokenizer或真实独立GGUF↔HF audit/basis/goldens；项目Python3.11 `.venv` 缺transformers/tokenizers，不能混用系统Python3.12。当时缺HF来源/隔离依赖；本轮已补齐候选资产和环境，后续发现的Unicode兼容问题已在2026-10-16修复并补审，见下文「兼容修复完成」——该条已取代本条中"未找到匹配 HF tokenizer 或真实独立 GGUF↔HF audit/basis/goldens"的当时状态，不为准备创建空eval/claim。离线盘点工具与不能通过生产校验的来源草稿已完成，主Agent38项合成测试通过；只核静态结构/字节，不认证auditor或执行golden，不生成部署receipt。证据见运行前核验（该记录已随 2026-10-18 清理移除）及当时的模型库存快照（原记录已移除）。
- **本轮补齐（2026-10-15，Codex）**：已核官方HF固定候选 Qwen/Qwen3.5-9B@c202236235762e1c871ad0ccb60c8ee5ba337b9a、ornith-ai/Ornith-1.5-9B@489cb97981b8654bcfcf30ce1f94ed1b62e07b53；10小文件完整SHA/API对象核验，分别保存独立Jinja。独立Py3.11.14环境29包hash锁/官方wheel/5010安装文件字节通过，实际离线tokenizer加载/渲染通过，无Torch。provider仅白名单增Jinja，旧冻结字节不追认；76项相关合成回归通过，独立reviewer41项及16+16+6个tokenizer材料复核通过，准备交付无剩余可执行问题，但正式等价映射（当时）不通过（该结论为 2026-10-15 当时状态，2026-10-16 兼容修复后已按 v2 受审映射补齐，见下文「兼容修复完成」）。详见[固定来源与材料](results/evaluation-tokenizer-materials-20261015.md)。
- **前轮映射反证及本轮处理**：固定llama.cpp vocab-only counter共16case仅14完整ID相同，两个Unicode case均HF31／GGUF32；原始HF资产及直接加载均NFC，GGUF counter保留NFD，不能归因为缺包或仅待auditor签字。固定HF来源不证明本机GGUF转制历史，Ornith官方Q4与本机blob也不同。保留全部反证，不改raw/模板/模型、不删除失败case、不伪造已审mapping；前轮已核官方Ollama0.33.1/b10630及安装包x86词表观察。现按用户2026-10-16授权修复本地兼容并重做准备证据，不再以新方案选择为前置；修复/来源/隔离等证据不足时真实调用仍拒绝。真实模型评测/test仍未授权。
- **本轮实际分词核验（2026-10-15）**：App/工件签名及架构已核：arm64 server静态嵌入，库仅x86。通过已有Rosetta和安装包实际签名x86库vocab-only执行24公开case（不tensor/context/GPU/生成），实测重现NFC/NFD差异；16与HF同ID，22/22与旧counter相同。预算反例HF4013+512=4525，实际x86库8013+512=8525，8K安全判定相反。28项合成保护和独立复跑通过，最终24词表case亦独立完整复现；实际loaded images/角色/摘要/批准manifest受控，准备审查无剩余可执行问题。原生arm64未实测，不能用x86放行native。证据见[核验记录](results/ollama-tokenizer-verification-20261015.md)。
- **兼容修复完成（2026-10-16，Codex）**：provider已保留HF模板渲染并构建内存兼容编码器，完整校验冻结manifest/GGUF元数据，覆盖两个模型的不同追加/控制/unused规则。实现者原24组公开回归与新增566组词表专用case全部完整ID匹配安装包x86库；NFD预算8013+512越界被正确识别，原文/HF文件不改。独立reviewer另582组完整ID全部匹配，并复跑新增29＋旧semantic35共64 passed；tester新增29 passed，inventory最终63 passed。两个模型各9条实际golden的v2受审映射已补、离线build与verify通过，旧证据不追认；实际离线库存两模型v2结构/来源/依赖绑定匹配；库存不授真实资格，最终独立审查通过，无剩余可执行问题，不代表真实模型或native服务通过。见修复记录（该记录已随 2026-10-18 清理移除）。
- **隔离运行前接线（2026-10-16，准备完成／Codex）**：现有canary探针及只读匿名worker可复用，但尚无脱离正式eval的显式预检CLI；本轮新增仅合成输入的独立入口，并实际核当前Mac的文件/进程/网络拒绝及三actor匿名请求生成。不调用Ollama/broker、不创建正式eval/claim，不将预检作为独立账户或真实评审部署证明。实现者Mac CLI已实测8项canary通过、三actor各2条匿名请求，新增29项保护与相关联合92 passed（17.08秒，旧pytest清理299 warnings）；独立指定新basetemp复跑57＋35共92项通过、无warning；实际CLI再跑/输出0600/拒覆盖通过，证据见运行前接线记录（该记录已随 2026-10-18 清理移除）。
- **兼容修复授权（2026-10-16）**：用户明确按原方案处理本地兼容问题，不再另起方案讨论；前轮[A/B草案](plans/2026-10-15-review-tokenizer-alignment-design.md)已撤回为历史探索，不再是待用户决策的前置。保持原方案和原文，修复现有provider内部计数兼容，核验完整GGUF元数据与既有公开词表结果；旧冻结证据不追认，真实调用授权门不放宽。
- **实际环境核验（2026-10-16）**：独立Py3.11实际加载固定tokenizer/兼容映射，18条golden通过；现有Ollama仅tags/show/ps元数据，批准digest/模板匹配、前后无驻留模型变化，三个provider/source SHA前后一致，8canary及匿名worker通过。已保存真实无模型环境报告（该记录已随 2026-10-18 清理移除），未调用generate/chat或制造生产deployment receipt；独立账户/真实上下文及完整服务仍未验证，ready_for_real_review=false。
- **证据/限制**：[本轮接线与验证记录](results/evaluation-independent-performance-admission-20261015.md)；[方案](model-evaluation.md)、[计划](plans/model-evaluation-implementation.md)、现行 `finetune/eval_holdout.py` / `versioning/holdout.py`；未读取受限语义、创建账户或claim、发送评审包。

### EVAL-PERFORMANCE — 受控加载与五分钟交互基准

- **状态/来源**：进行中（Codex，2026-10-15；主仓工程已完成，外仓 TensileAgent 的跨库测点、签名链与真实密钥托管未做、需跨库授权，待真实 GPU/E2E 证据）；父目标 MODEL-QUALITY；用户授权受控性能工程接线与合成验证，未授权真实模型/性能运行或真实test。
- **事实与差距**：已实现受控performance会话、实际loader核验与可信显示回执接收；外部客户端/instrumentation尚未部署，真实GPU与E2E证据仍缺。smoke timeout=300不是性能成绩。
- **基本内容与做法**：在eval领域新增performance用途及临时受控入口，精确Registry模型数值版本、有效来源/权重、Prompt/预处理/生成配置、开发媒体白名单、设备/预算/会话期限/执行身份全绑定。可加载未质量或性能通过的已核验base/诊断fold/full，只走本机受控端点，跨机用受控通道；不借candidate/production alias、不接受裸路径或test。测后仅退出本会话进程，不影响已有服务。
- **依赖/下一动作**：D加载权限、生命周期、计时/计数、资源采集与双签名接收工程已实现；下一步现场核定真实执行资产及客户端测点，获得适用授权后运行。沿用已确认视频规格（≤60秒、≤100MiB、MP4/H.264 8bit、长边≤1920/短边≤1080、≤60fps），不得据此删质量测试样本；300秒达标、后端600秒/客户端660秒绝对超时，全上传处理及重试总计时；预检≤1 GPU小时、正式性能≤20 GPU小时，达到预算停止并报告未完成。质量预算按冻结样本数事前计算，不中途缩样。TensileAgent测点及跨库写入另授权，后端证据不冒充完整显示。单用户单请求不外推并发。
- **验收标准**：全部合格请求≥95%在300秒内自动显示完整结果，失败/超时/需评测Agent或人工判读不算按时完成；失败率≤1%、无OOM/崩溃/持续增长；≥100请求且≥30分钟连续处理，预热/冷启动分开，不通过重试重置时间和分母。具体持续增长判断口径在执行前冻结。
- **本轮进展**：受控plan/session、Registry实际loader、事件/双签名显示回执接收及export已实现；视频加载器摘要一致性已补齐并由实际两侧input builder测试保护，最终61项合成测试通过（6.15s，退出0；实现者来源），独立reviewer另61 passed（2.36s）。实际runtime核NF4六项与resampler；OOM可观测、clean finish、线程超时终态不明停止接新请求、warmup.request_ids冻结及增长算法已实现。外部客户端未部署，本轮synthetic不能获正式passed；独立审查通过，无剩余可执行问题，限工程及合成范围。
- **交付参数准备（2026-10-16）**：受控性能与最终服务共用ChatModel/adapter，开发评测另用AutoModel/video_loader；解码同值不等于整体一致，开发slice1/服务视频slice2、抽帧边界及1/最多3次调用差异已并入EVAL-DEVELOPMENT前置。性能预检1/正式20GPU小时及600/660秒timeout已核代码停止条件；未创建实际session/TTL，不据静态配置认加载device/dtype/NF4/resampler已验真。见[训练数据台账](results/training-data-ledger-20261017.md) 的 `runtime_readiness.resource_budget`（原参数及预算材料已于 2026-10-18 并入台账并移除原文件）。
- **运行前客户端核验（2026-10-15，Codex）**：仅只读本地TensileAgent候选 `codex/competition-demo-chat-mock@86e50c65`（有未跟踪tmp未读）；上传、VLM调用/重试及React结果render未贯通原request ID/nonce、upload→render单调ns与签名回执。已有服务finished_at/event不能作显示端点。保留单次视觉自动结果口径，Agent多轮另报；需未来获得跨库授权后实现专用测点、签名/密钥保管、版本化冻结与部署，本轮只准备既有receiver契约交接清单、不改外仓/生成密钥/启动客户端。详见运行前核验（该记录已随 2026-10-18 清理移除）。
- **显示测点运行前接线（2026-10-16，准备完成／Codex）**：按既有receipt协议新增主仓薄客户端适配，贯通稳定ID/nonce、显式上传完成/完整显示回调的同一单调时钟、backend签名绑定与签名回执提交；transport/signer注入，先以公开合成输入验证，不选择真实密钥托管、不改候选外仓UI或将回调称为DOM部署证据。候选TensileAgent当前分支/HEAD与上轮相同，6个tracked文件已只读摘要盘点，仅未跟踪tmp未读；真实页面、单次视觉请求与密钥冻结仍未部署。新增47＋现有61共108项合成通过（2.66秒），现有ASGI三路由/临时双密钥闭环仍synthetic；独立reviewer另108 passed（2.75秒）、无warning，当前代码/结果/候选源码绑定复验通过；详见运行前接线记录（该记录已随 2026-10-18 清理移除）。
- **证据/限制**：[本轮接线与验证记录](results/evaluation-independent-performance-admission-20261015.md)；[方案](model-evaluation.md)、[计划](plans/model-evaluation-implementation.md)与现行服务；未启动临时端点、跨机通道或真实计时。

### EVAL-INTEGRATION — 来源、评审及质量/性能用途绑定

- **状态/来源**：进行中（Codex，2026-10-15；工程已完成，待真实环境证据）；父目标 MODEL-QUALITY；用户授权批次E用途/准入工程接线和合成验证，真实服务、模型和test仍不执行。
- **事实与差距**：Registry/manifest/MLflow及服务已统一复验新质量＋性能用途和同模型配置；旧strict只保留既有绑定读取与同身份幂等恢复。真实新质量/性能证据和服务验证仍缺。
- **基本内容与做法**：更新配置/冻结摘要/MLflow/manifest/export/finalize/服务门的用途校验，视觉质量passed和performance passed互不替代；精确绑定同模型权重、Prompt和运行变体。旧对象按原契约读，不补字段、改原结果或改消费事实；受控加载不授candidate/production或生产批准。
- **依赖/下一动作**：E联合合成验证核对B/C/D来源、分母、判读、授权、输出、恢复及准入；下一步补真实证据后复验服务，不以合成状态升级；统计采用原精度判门、百分比两位显示、同源组95%CI/2000次重采样（固定种子），不增加CI门槛，不因“证据不足”文字自动改底层状态机。
- **验收标准**：错用途/错版本/缺证据/规则或模型漂移/性能冒充视觉均拒绝；开发和test报告权限分开，保留既有批准。代码合成检查与训练机真实质量/交互/恢复证据分别记录。
- **本轮进展**：工程已完成；最终77 passed（54恢复/准入＋9服务＋14开发，89.08s，退出0），精确旧源码兼容＋CLI另6 passed。独立reviewer准入/恢复/兼容/CLI/服务69 passed。新增purpose/protocol、联合复验、私有工作区备份、0400受控位置receipt及scoped MLflow client；异根sealed续score与consumed不重truth通过。按用户裁决拒旧strict新晋级，仅保留既有批准/alias读取及同绑定幂等。相邻旧Registry/materialize158、manifest/model_registry204及CLI57个不同用例分轮通过，不作为新真实准入证据。
- **当前前置（2026-10-16）**：C的HF固定资产及独立环境已备，2026-10-16兼容修复与v2映射已补，实际服务/隔离证据仍缺；D缺可信客户端实际测点/冻结部署；库存和离线草稿均不能授予新准入。先补资产/环境及跨库实现准备，再取得适用真实运行授权；本轮不解除MODEL-QUALITY等父任务。
- **证据/限制**：[本轮接线与验证记录](results/evaluation-independent-performance-admission-20261015.md)；[实施计划](plans/model-evaluation-implementation.md)；本轮不登记真实模型、不更改真实alias/服务或真实评测记录；合成store中的新旧准入动作仅用于测试。

### RECOVERY-VALIDATION — 真实大型产物与外部依赖组合恢复

- **状态/来源**：阻塞（Codex，2026-10-16；只读准备已推进，真实恢复未执行；解除条件：恢复目标路径与恢复操作授权（第一级备份根已由用户 2026-10-17 裁决给定为 `/data`，见固定标识 `ARTIFACT-RETENTION`））；迁移 Spec 保留的物理恢复限制，工程交付后继续单独验收。
- **事实与差距**：store 级异根恢复、SQLite/artifact 小对象联合恢复已通过；真实移动硬盘、大型 adapter/merged、SQLite、外部媒体与基座的整机组合恢复未完整验收，新 store 不自包含。
- **本轮核定（2026-10-16）**：训练机/data可用约3.65TB、/home约383GB，容量不证明备份独立或可恢复；本机/Volumes仅观察到系统盘入口，未获得准确外置盘/完整snapshot根。指定store尚无实际模型/训练/评测及默认MLflow，真实大型组合恢复缺可执行完整来源与目标，保留源、不创建空对象。见推进记录（该记录已随 2026-10-18 清理移除）。
- **依赖/下一动作**：只读刷新已完成；继续核定备份、源/目标、设备容量及受保护引用，准备明确恢复任务单及适用操作授权；不删除唯一源。
- **验收标准**：恢复对象和外部依赖范围明确，摘要一致；原路径不可用时，恢复副本可解析并支持约定读取/准入；原备份和不可变事实保持。GPU 加载/模型效果另按授权验收。
- **证据/限制**：[验证记录](results/version-control-migration/verification.md)第33、39、41、66–67节；已有 CPU/store 证据不能外推为灾难恢复通过，本轮不执行恢复。


### MODEL-ARCHIVE — 中间模型证据归档与权重清理准备

- **状态/来源**：阻塞（主 Agent；归档准备可推进，执行受条件限制；解除条件：完成完整迁移核验与独立备份后，逐 run 确定归档口径并确认删除清单与执行窗口）；用户要求验证能否保留历次训练参数和结果后清除训练机 run 下模型文件。用户已授权在完整迁移核验通过后清理旧数据与旧模型副本；未满足条件的文件继续保留。
- **已证实事实与差距**：2026-08-31 训练机 `workspace/runs` 约 90.253 GiB；原清单漏列两组 source-aware，concise-cv 约定路径不存在；r1 来源仍有 5 个 checkpoint，merged 为发布库软链接。5 组未发布模型 merged 权重合计约 80.988 GiB，各 root LoRA 约 439.1 MiB。原清单不足以放行删除；当时快照未哈希权重，未归档原始预测和完整训练日志。
- **现场增量（2026-10-13）**：旧Fold0及5个phase run的索引分片在场；coverage-first seed3407 merged仍共享发布库。concise/visual只在限定位置检查，未全面搜索或哈希权重、核验备份，清理条件仍未满足。见[现场报告](results/remote-state-refresh-20261013.md)。
- **现场增量（2026-10-16）**：已核旧Fold0 adapter完整SHA及基座字节；minimal试点归档MANIFEST在场，指定归档evaluation_records.jsonl缺失；原run相同文件存在432,796字节，仅stat未读，指定配置/日志在场。仍缺独立备份/完整归档，不能将原run在场当作副本验收，不扩大搜索concise/visual，不删除任何文件。见[完整性及归档报告](results/remote-base-integrity-20261016.json)。
- **依赖**：MODEL-DIAG 对历史/当前模型和阶段 checkpoint 的需求；当前发布模型及 `pipeline/checkpoint_policy.json` 保护边界。权重清理不隐含取消诊断任务。
- **下一动作**：按[归档模型清单第 8 节](results/model-inventory.md#8-2026-08-31-清理可行性核查)归档实际配置、模型/数据/Prompt/评测身份、完整日志和原始预测、文件哈希及备份校验；仅按已知身份和准确备份线索核查，不持续搜索缺失三折模型。逐 run 确定仅留研究记录还是保留 adapter 以便重新合并，形成显式候选清单并核对既有条件删除授权。保留 adapter 的方案先验证准确基座与合并链路，不以直挂 4-bit 代替 merged BF16。
- **验收标准**：每模型每 fold 有可核查的原始配置和结果链、缺失证据明确、归档已备份并校验；2026-09-13 新增 visual 三 fold merged 断链与concise缺失归入同一保护依赖（验证第48节）；清理路径不跟随链接误入发布库，不删除在用模型和未完成诊断所需文件；训练机按获准清单执行并记录删除前后体量、保留文件完整性及对应机器提交。完成可行性审查不等于归档或删除完成。
- **证据/版本/验证限制**：[模型清单](results/model-inventory.md#8-2026-08-31-清理可行性核查)、[训练机快照](results/model-inventory-audit-20260831/remote_snapshot.json)、模型归档证据包索引与试点证据包 `v4.1-prompt-minimal-v1-seed3411` README（该记录已随 2026-10-18 清理移除，逐文件指纹与 SHA-256 见 `pi-workspace/mVllm_2-audit/deleted-artifacts-manifest-20261018.tsv`，来源与限制结论见[模型清单](results/model-inventory.md)）。本地核查基线 `7b8192bd`，远端 `main@f1b7d8a3` 干净，本地独有 3 提交、远端独有 0；2026-08-31 调查的 SSH 仅执行 Git 状态、文件 stat/目录/链接与轻量 JSON 读取，不启动 GPU 任务、训练、合并或评测，不读取受限测试语义结果。仅快照及文档落本机，未同步/删除远程文件。独立 reviewer 的原稿 findings 已核对：保护条件缺失 P1、模型清单过期/证据不足/效果结论过度 P2；修订后独立 reviewer 复审通过，无剩余可执行文档问题；10 个清单链接、指标/契约对照与 `git diff --check` 通过。修正归档要求仍不代表已满足删除条件。
- **后续证据**：2026-09-13 条件清理授权涵盖旧数据及旧 run/model 的已核实冗余副本；89 个 train 视频大小/SHA 一致，但占用预检权限不足，删除 0、释放 0。新 store 的外部媒体与当前发布库仍受保护；见[验证记录](results/version-control-migration/verification.md)第56–58节。下一轮刷新后核定候选，不能将历史验签当作今日可删除证明。

### ARTIFACT-RETENTION — 产物归档、过期清理与备份节奏纪律

- **状态/来源**：进行中（Pi，2026-10-17；纪律已生效，首次按节奏执行待全量训练+评测归档）；用户 2026-10-17 裁决，用户明确要求主动管理过期文件、不要积累。父任务 MODEL-ARCHIVE / RECOVERY-VALIDATION；本条只补纪律与红线，不改变这两个父任务的阻塞状态与既有条件删除授权范围。
- **备份根与节奏（用户 2026-10-17 裁决）**：`/data`（`/dev/sda1`，3.4 T 空闲，独立于主仓 `/dev/nvme0n1p2`）为第一级备份根；1 T 移动硬盘为第二级，按「每完成一次全量训练+评测归档一次」的节奏，不做持续同步。备份必须另开目录（如 `/data/mVllm_2-backups/`），不得混入 store 内部。
- **store 与备份物理分离（用户 2026-10-17 裁决）**：授权把活 store 从 `/data/mVllm_2` 迁到训练机项目目录根下 `/home/liuyang/文档/mVllm_2/store`（nvme），`/data`（sda1）此后只放备份；2026-10-17 已完成归位（见本条 store 迁移），`/data/mVllm_2` 不再是现役 store。`versioning` 的 `data`/`train`/`eval`/`model`/`backup` 子命令 `--root` 显式指向 store 根（其下含 `data/`、`records/`、`workspace/mlflow/` 等，非穷举；迁移后新 store 的实际布局待现场核验）。`prompt`/`train`/`eval`/`model`/`backup` 的 `--root` 默认值为 `.`（`versioning/cli.py:91-104`，默认值在 `:96`），不显式传会把当前目录当 store 根；迁移后 checkout 根物理包含 `store`，误传会静默取错根；`store/records/prompts/` 已由 `.gitignore` 逐级白名单放行（迁移后随 store 一并进 Git，当前仓库尚无被跟踪文件），不得把它当临时目录清理。`data` 各 stage 的 `--root` 无默认值，缺省即 fail-closed（`versioning/cli.py:127`、`:479`、`:490`、`:495`）；`data claim` 例外，缺省回落当前目录（`versioning/cli.py:426-427`）。
- **`--root` 例外：migration 子命令**：`versioning migration` 的 `--root` 必须是**同时容纳 legacy 源与目标集合**的那个根——源按相对路径解析为 `pipeline/prompt_registry/<id>/`（`versioning/migration.py:61`、`versioning/migration.py:713`）、`workspace/data/releases/`（`versioning/migration.py:73`）、`finetune/active_data_release.json`（`versioning/migration.py:79`），目标对象与 `migration_receipts/` 同样相对该根（`versioning/migration.py:658`、`versioning/migration.py:1225`），`history-build`/`history-write` 也使用同一根。历史实际执行不是同一个根：Prompt 迁移用项目 checkout 根（`docs/results/version-control-migration/verification.md:425`），Data 迁移先把来源镜像进 store 根 `/data/mVllm_2` 再执行（`verification.md:323`）；按动作分别指定，不要套用日常 store 口径。
- **Prompt 记录位置与「进 Git」口径的冲突（2026-10-17 已裁决，见下条）**：`prompt` 子命令的正式记录固定落在 `<root>/records/prompts/<版本>.yaml`（`versioning/prompts.py:73-83`）；`train` 用同一 `--root` 同时定位 `<root>/data` 下的数据记录与 `<root>/records/prompts` 下的冻结 Prompt（`versioning/cli.py:569`、`versioning/cli.py:570`、`finetune/train_prepare_run.py:485`；`eval` 同构见 `versioning/cli.py:866`、`:867`），而 `train` 子命令没有数据根／Prompt 根的分域覆盖参数（只有 `backup` 有 `--data-root`/`--prompts-root`，`versioning/cli.py:280-281`）；`backup` 的 `prompts_root` 默认也取 `args.root`（`versioning/cli.py:988`、`versioning/backup.py:496`）。`model` 侧另有 `--records-root` 可单独指定 Git records 根（`versioning/cli.py:267`、`versioning/cli.py:961`）。原 store 根整段被 `.gitignore` 的 `/workspace/` 忽略（`.gitignore:13`），因此单一 `--root` 无法同时满足「data 记录在 store 内」与「Prompt 记录在 Git 工作树内」。可行方向至少三条：① 给 `train` 增补数据/记录分域参数；② Prompt 记录改置 store 内并在别处同步进 Git；③ 迁移时把 `records/` 从 store 根裁出。受影响子命令至少含 `train`、`prompt`、`backup`。本条登记冲突与代码依据；裁决见下条——方案 A 下单一 `--root <项目>/store` 即同时满足「data 记录在 store 内」与「Prompt 记录在 Git 工作树内」，①②③ 不再需要。
- **Prompt 进 Git（2026-10-17 用户裁决：方案 A，已在训练机完成归位，见下方 store 迁移条）**：活 store 目标位置为项目根 `<项目>/store`，`.gitignore` 以逐级白名单仅放行 `store/records/prompts/`；Prompt 等小体积配置随 `records/prompts/` 进 Git，媒体与大权重不进 Git。训练冻结的 Prompt 副本仍落 `store/workspace/runs/<train_version>/input/prompt.yaml`（`versioning/prompts.py:86-88`），属 `store/workspace/` 忽略范围、不进 Git。
- **备份命名规则（用户 2026-10-17 裁决）**：`/data/mVllm_2-backups/` 是备份总目录；单次备份的 `--backup-root` 必须显式指定为该目录下的子目录，历史基线命名 `baseline-YYYYMMDD`，本轮训练归档命名 `round<N>-YYYYMMDD`。`--backup-root` 为平铺写入且不自动建日期子目录（各对象直接落在 `backup_root/<种类>/<对象ID>`、Prompt 为单文件 `backup_root/prompts/<对象ID>.yaml`、mlflow 落 `backup_root/mlflow`，`versioning/backup.py:683-717`），因此不得把总目录本身当作 `--backup-root`：`backup verify` 先要求根下有 `backup_catalog.yaml`（`versioning/backup.py:800-805`），再要求根下文件集合与 catalog 精确一致、存在额外文件即失败（`versioning/backup.py:1090-1118`），而 `backup create` 是先复制对象、后做额外文件预检查（`versioning/backup.py:1151-1172`），误把总目录当备份根会先污染总目录。据用户口径，`/data/mVllm_2-backups/20261017/` 是历史旧物搬运落点（本机未核），不是本轮训练归档目录：新规则不追溯改名旧目录，但旧目录不再写入。
- **迁移过程产物不算备份（用户 2026-10-17 裁决）**：隔离目录 `mVllm_2-migration-7eeb93a7` 按用户口径先导出未提交改动 patch（`migration-7eeb93a7-uncommitted-20261017.patch`）再删除，本机无该操作的现场证据、结果待核；该目录位于家目录 `/home/liuyang/文档/` 而非备份盘，过程产物不作为备份保留。它同时是 `docs/results/version-control-migration/verification.md` 多处证据的原始落点，删除后这些路径以已导出的 patch 与该验证记录为准，不得再把该目录当作可访问证据。
- **活 store 位于 Git 工作树内（运维红线）**：`/home/liuyang/文档/mVllm_2/store` 在 Git 工作树内，除 `store/records/prompts/` 由逐级白名单放行外整段被 `.gitignore` 忽略，`git clean -xdf` 会直接删除活 store；禁止在训练机项目目录执行带 `-x` 的 `git clean`。（2026-10-18 训练机核查）
- **store 迁移（2026-10-17 已完成）**：2026-10-17 已将活 store 从 `/data/mVllm_2` 归位至 `/home/liuyang/文档/mVllm_2/store`，逐文件 sha256 核验 48/48 一致；旧目录改名 `/data/.store-old-20261017` 保留 7 天回滚窗口。核验记录见仓库外 `~/pi-workspace/mVllm_2-audit/cleanup-execution-20261017.md` 第六轮（48/48、sha256 0 处不一致，本机未复跑；本机 checkout 无 `store/` 现场）。
- **Prompt 双份与一致性门（2026-10-17 代码核查）**：Prompt 正文另有 Git 跟踪副本 `records/prompts/prompt-v4.1-r1.yaml`（仓库根；`records/prompts/` 下唯一被跟踪的 Prompt 记录，legacy `pipeline/prompt_registry/*/prompt.yaml` 3 份、`pipeline/prompt_control/active_prompt.yaml` 与含 v2.1.0 正文的 `pipeline/prompt_library.yaml` 仍被跟踪、不在新体系校验范围；sha256 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`），而训练/评测实际读取的是 store 内 `store/records/prompts/`：训练在 `finetune/train_prepare_run.py:489` 把 `--root/records/prompts/<版本>.yaml`（构造见 `versioning/prompts.py:78-88`）逐字节冻结到 `workspace/runs/<train>/input/prompt.yaml`，评测侧同源读取（以结构化字段写入 `evaluation.yaml`，非字节冻结）见 `finetune/eval_run.py:788`。已有门只覆盖 store 内部：冻结副本字节被 sha256 钉入 `input-manifest.json`（`finetune/train_prepare_run.py:490-491`）并在 validate/run 复验，`verify_frozen_prompt` 结构化比较冻结副本与 store 正式对象（`versioning/prompts.py:315-352`、`finetune/train_prepare_run.py:560`），服务绑定再比对训练冻结副本与 store 正式对象（整体相等，含 protocol）、以及 eval 冻结的 version/system_prompt/user_prompt/output_fields 四字段（`pipeline/model_registry.py:323-348`；eval 的 passed 前置由 `versioning/registry.py:522` 保证），缺失或漂移即拒绝（fail-closed）。**该缺口已于同日实现**（见下方「Prompt 双份一致性门」条）：缺口成立时的依据是 `versioning` 不调用 git、也不读项目 checkout 根的 `records/prompts/`，`--root` 指向 store 时 Git 那份从未参与比较，风险落点在 `train prepare`（它冻结的是 store 当前内容，无法发现与 Git 正文不一致）；该历史依据保留为缺口来源记录。仍未纳入本门的是 `prompt create/verify --root .` 在 checkout 根执行时直接读写 Git 那份——该路径不经过新门，不得视为已加固。
- **Prompt 双份一致性门（2026-10-17 实现，方案 A）**：按用户 2026-10-17 裁决走方案 A——先按 `versioning/eval_compatibility.py` 模块 docstring 既定流程做一次适配复核，再更新 `adapter_sha256`——新增 `versioning/prompts.py:360 verify_prompt_checkout_copy`：`parse_prompt_id` 校验完整版本名后，要求 store 侧 `records/prompts/<版本>.yaml` 存在（`:385`，走既有 `PromptNotFound`），随后比对两侧 sha256 与字节数；`checkout_root` 缺省按 `<store 根>/..` 推导（`:392`），显式传入时只比对传入位置（`:402`），两种情形都要求该位置已有同名副本；两侧解析到同一文件即拒绝（`:410-411`，自比不构成比对证据）；字节或长度不一致抛 `PromptCheckoutDrift`，消息给出两侧绝对路径、完整 sha256 与字节数（`:423-429`）。行为为 fail-closed：副本缺失、路径推导不到、解析到同一文件、字节不等一律拒绝，不猜测哪侧权威、不自动回退、不提供忽略开关；该函数只读，不写任何文件（成功分支 `:420-421` 直接 `return None`）。接入点三处：训练冻结 `finetune/train_prepare_run.py:460`；评测输入构造 `finetune/eval_run.py:779`（在 `prompt_version` 确定之后、`build_versioned_datasets`（`:786`）与任何评测产物落盘之前）；full holdout 分支经 `finetune/eval_run.py:725` 透传到 `finetune/eval_holdout.py:200`（在读训练冻结副本 `:201` 之前）。CLI：`versioning/cli.py:166`（train）、`:207`（eval）新增 `--prompt-checkout-root`，`:550-551` 限定 train 仅 `prepare` 可用，`:688` 只对 eval 的 `prepare/validate/run/score` 放行、`review_prepare/review_seal/review_run/review_verify/restricted_summary` 与 `performance_*`（`:635` 的 forbidden 集合）一律拒绝该参数。用例 17 项见 `tests/versioning/test_prompt_checkout_guard.py`：15 项覆盖门行为，另 2 项覆盖 CLI 动作白名单；两侧一致通过、漂移拒绝并给出两侧证据、train prepare 漂移与副本缺失均拒绝且不产出冻结输入、store 侧缺失走 `PromptNotFound`、显式 checkout 根选中一致第三方副本、显式根指向漂移副本、eval prepare 漂移拒绝、holdout prepare 漂移拒绝、checkout 根解析到 store 同一文件拒绝、train/eval CLI 透传、`_formal_input` holdout 分支透传、`execute`/`resume` 的 live 校验逐个透传（用例以注入异常截停在各自首个 live 校验，后续校验节点未逐步断言）；其中 2 个单元级用例（`tests/versioning/test_prompt_checkout_guard.py:241`、`:356`）钉死两侧绝对路径、完整 sha256 与字节数，4 个入口级拦截用例断言异常类型加「未产出冻结输入」，2 个 CLI 白名单用例断言退出码 2 与拒绝文案（删除 `versioning/cli.py:550-551` 或 `:687-688` 任一处即变红），均不只断言「未发生」。注意 `STRICT_ADAPTERS` 的 `adapter_sha256` 同时服务 strict 映射（`versioning/eval_compatibility.py:12-15`）与 A/B／语义映射（`:27-34`），因此更新该字段必然同时把 A/B 记录的「当前字节白名单」挪到新字节；本次未改表结构，属既有设计，在此披露。
- **一致性门未覆盖边界（2026-10-17，不得越界引用为已覆盖）**：① 只比字节不比语义——两侧 YAML 语义等价但注释、键序、空白或行尾不同即判漂移；字节相同即通过，本门不额外做语义一致性判断（store 内部语义一致性仍由既有 `load_prompt`/`verify_frozen_prompt` 负责）。② 不覆盖历史已冻结产物——门只在「取用或新冻结之前」比较当前两侧内容，已冻结进 `workspace/runs/<train>/input/prompt.yaml` 与 `evaluations/<eval>/input/evaluation.yaml` 的历史字节不重算、不回写、不改历史结论，历史证据仍以其冻结字节与既有摘要校验为准。③ `eval review_prepare/review_seal/review_run/review_verify/restricted_summary` 与 `performance_*` 不接受 `--prompt-checkout-root`（用户 2026-10-17 裁决保持不放开）：这些动作依赖自动推导；生产布局下 store 位于 `<项目>/store`，`<store 根>/..` 即项目根，checkout 副本天然在 `<项目>/records/prompts/`；若 store 不在项目根下（例如旧的 `/data/mVllm_2` 布局），这些动作会在 `PromptCheckoutDrift` 处 fail-closed，不会静默放行，也不存在经由 review 动作绕过门的路子。④ `versioning prompt freeze` 直接写 `<store>/workspace/runs/<train>/input/prompt.yaml`，本身不过本门；其下游 `train prepare` 无条件过门（`finetune/train_prepare_run.py:460`），若已有冻结输入则先比文件集（`:495-497`，不同即拒绝）、再逐个逐字节比较（`:498-499`，不等即拒绝），因此不构成绕过路径。
- **本轮适配复核结论（2026-10-17）**：本轮对 `finetune/eval_run.py`（49 行改动）与 `finetune/eval_holdout.py`（30 行改动）的改动全部属于「新增可选参数 `prompt_checkout_root` 并逐层透传 + 一处新增门调用 + import 补充」三类，不含判分、输出、口径、阈值、来源变更。逐项依据：判分逻辑——`_execute_formal_fold`（`finetune/eval_run.py:939`）及 `evaluate_one`、`summarize_records`、`_score_records`、`_metric_definitions`、`_public_metrics`、`_outcome`、`_verify_private_scoring`、`_verified_judge`、`validate_holdout_execution` 在 diff 中零改动行；输出字段集合——diff 中没有任何字典字面量增删键，新门成功分支返回 `None`，`_formal_bytes`（`:541-542`）未改，因此门通过时 `evaluation.yaml` 与改动前逐字节一致；分母口径——`samples` 仍由 `build_versioned_datasets`（`:786`）的 validation 折行组装（`:791` 起），聚合仍为 `pooled` 且 `_formal_config` 未改；holdout 的媒体摘要循环 `finetune/eval_holdout.py:196` 在 diff 中是上下文行，门调用仅插在其后；阈值——diff 中无任何门限数值变化，`config["thresholds"]` 键与取值路径未变；Prompt 内容读取来源——eval 仍读 store 侧 `load_prompt`（`finetune/eval_run.py:788`），holdout 仍先读训练冻结副本 `training_root/'prompt.yaml'`、再与 `load_prompt(root, model.prompt_version)` 整体相等比较（`finetune/eval_holdout.py:201-202`，比较行未改）。历史记录复核路径为何不误拦：`eval validate` 与 `eval review_*`（经 `_review_context`，`finetune/eval_holdout.py:631-634`）走 `verify_versioned_evaluation`（`finetune/eval_run.py:874-903`）的 live 重算分支，新门在其中同样执行；`eval export`（`finetune/eval_run.py:1431`）以 `live=False` 调 verify（`:1435`），不重算输入、不经过本门；`eval compare`（`:1445`）连 verify 都不调用。新门在 live 重算里不误拦的原因是：（a）它不向任何产物写入字节；（b）`prompt_checkout_root` 缺省按 `<store 根>/..` 推导，生产布局下正好是项目的 Git checkout 根，Git 侧副本 `records/prompts/prompt-v4.1-r1.yaml` 的 sha256 为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`（本机实测；该副本与 store 副本字节一致依据 2026-10-17 store 迁移核验 48/48，本机无 `store/` 现场、未复算 store 侧摘要），故 live 复核通过且冻结字节不变；（c）历史 strict / AB 记录的 `implementation_sha256` 差异由 `_historical_strict_comparison`（`finetune/eval_run.py:564`）配合 `versioning/eval_compatibility.py` 的审计映射单独放行，与 Prompt 门是两条独立机制。适配摘要更新（`versioning/eval_compatibility.py:9`，只改两个 `adapter_sha256` 值，`frozen_sha256`、`AB_FROZEN_SOURCES`、表结构与函数、以及任何「忽略漂移」开关均未改）：`finetune/eval_run.py` 由 `e8b61ba6cfe5965f3e3bc358e7155638ccc63029710367086bfe9c39c58b64b2` 更新为 `b80cacca8c8939128ddbe6bfdec2c21f3c2ac8d3af7e760bde8956c924049a39`；`finetune/eval_holdout.py` 由 `2c7a38e9259139b46f7f68ee62a7289b9ae05b5f73edf39d915ce9607390f12f` 更新为 `f96e56568d04c94eda43f1a2a653ca874c0c08dc3b8fa077bf5d25a1ad1718fc`。恢复验证：`tests/test_eval_development_wiring.py` 2 个与 `tests/test_eval_admission_compatibility.py` 2 个（strict-v4.1 / semantic-v4.1 参数化）合计 4 个用例已恢复通过，`tests/versioning/test_prompt_checkout_guard.py` 17 用例（15 项门行为 + 2 项 CLI 白名单）仍全绿；其中 `test_actual_archived_holdout_uses_its_original_seven_gates` 另需一处测试侧模块装载顺序修正（归档 512cc8b4 版 `eval_holdout` 的 `build_holdout_input` 无新参数，原用例在调用当前 `verify_versioned_evaluation` 之后才把当前模块装回 `sys.modules`），已把该装载上移、断言零删改，并以「把 `eval_holdout.py` 的 `adapter_sha256` 改回旧值即变红、改回新值即变绿」的变异自证确认是真实通过而非被绕过。台账 39 个固定标识与全部阈值零改动。
- **家目录去重（用户 2026-10-17 裁决）**：训练机家目录下本项目只保留一个项目目录，作为后续开发的唯一目录；重复项目副本、旧 checkout、未发布模型 merged 与历史 checkpoint 走「迁移 → 核验 → 清理」顺序，删除前须过 `/data` 7 天隔离区。已发布/部署 merged 与 registry 不进入本去重清理范围，见下方清理红线。
- **过期文件管理纪律（用户 2026-10-17 裁决，用户明确要求主动管理）**：(a) 一次训练一次归档，不留中间态；(b) 每个产物目录必须有 manifest（是什么、哪次训练、保留期限），无 manifest 默认视为临时；(c) 主 Agent 在每次训练完成或用户开启新任务时主动输出「过期候选 + 体积 + 建议动作」清单，用户确认后执行。
- **待办（用户 2026-10-17 裁决，用户要求记住）**：把 `/data` 下归档数据定期拷贝到用户的 1 T 移动硬盘，在每次训练完成后执行。
- **清理红线（用户 2026-10-17 裁决，任何清理提案都不得包含）**：① 原始视频源 `workspace/data/source/videos`（被 `data-v4.1-r2` manifest 引用）；② 基座权重（约 17 G / 23 文件）；③ 部署模型本体 merged 与 registry。以上三项属活数据，既不进入过期候选清单，也不因「已备份」而从保护范围移出。**归属标注（2026-10-18 训练机实测）**：这三类媒体与 store 侧 Prompt 的保留义务在训练机（`workspace/data/source/videos` 6,662,518,177 B / 110 个 mp4、`workspace/data/derived/subvideos` 208,117,755 B / 2,027 文件、`store/records/prompts/` 含 r1 1,200 B 与 r2 1,808 B），不在本机 checkout；本机 `workspace/data/` 父目录整体缺失、无 `store/`。
- **保留清单（不得随清理删除；媒体与 store 侧 Prompt 属训练机侧保留）**：删除任一项前必须先确认零引用与副本存在，任何过期候选清单一律排除。**本机 checkout 内**：`.venv/`（本机轻量验证环境，可 `uv sync` 重建但日常依赖它）；`workspace/base-source-audit/`（源审计证据包，可能为唯一副本）；`LlamaFactory/` 子模块（含 6 个 MiniCPM-V 补丁，仅存于 Gitee fork）；`records/prompts/`（Prompt Git 副本，漂移门依赖）；`finetune/results/`、`docs/results/`（评测与发布原始证据；**2026-10-18 起保留范围收窄为 B 组（R1 线）与 C 组**：A 组 7 项 116 个 2026-07 legacy／v2.0.0 实验产物已由用户 2026-10-18 明确裁决删除，逐文件指纹见仓库外 `pi-workspace/mVllm_2-audit/deleted-artifacts-manifest-20261018.tsv`）。**训练机侧**（`/home/liuyang/文档/mVllm_2`，本机 checkout 无对应实体）：`workspace/data/source/videos`（6,662,518,177 B / 110 个 mp4）、`workspace/data/derived/subvideos`（208,117,755 B / 2,027 个文件，含 2 个 candidate-plan：1,617 + 410）——r2 媒体实体，删则数据失效；`store/records/prompts/`（store 侧 Prompt 副本，`store/` 实测 47,288,387 B / 49 文件，该目录含 r1 1,200 B 与 r2 1,808 B）。上述训练机数字与「本机 `workspace/data/` 父目录整体不存在、本机无 `store/`」均取自 2026-10-18 训练机实测（记录见仓库外 `~/pi-workspace/mVllm_2-audit/training-machine-audit-20261018.md`）。本条与上方「清理红线」并列，不替换其三项。
- **2026-10-18 用户明确裁决（覆盖「`finetune/results/archive/` 下 17 个 `evaluation_records.jsonl` 绝对不能删」红线）**：本批 A2／A3 删除的 17 个 `evaluation_records.jsonl`（`archive/legacy/` 4 个 + `archive/v2/` 13 个）原被任务书列为「绝对不能删」，本次经用户 2026-10-18 明确裁决纳入删除；理由：这些记录属 2026-07 legacy / v2.0.0 旧训练，与 R1、R2 无对应关系，用户判定对后续无参考价值。留痕证据：116 条逐文件 path/size/sha256/跟踪状态见仓库外 `~/pi-workspace/mVllm_2-audit/deleted-artifacts-manifest-20261018.tsv`（含该 17 条），内容仍完整保存在 Git 历史 HEAD `793dc725`。本条覆盖只针对该 17 个文件，不改变上方「清理红线」三项（原始视频源／基座权重／部署 merged 与 registry）。
- **诊断脚本迁入（2026-10-18）**：迁入 2026-07 诊断工具 14 个脚本至 `pipeline/scripts/diagnostics/`，其中 6 个在 main 无等价物被保留、8 个有等价物仅作历史留存；判定详见该目录 `SCRIPTS.md`。
- **待确认（技术债，2026-10-18 审查发现）**：A1 删除 `docs/results/model_evidence/` 后，`versioning/migration.py`（`:1890`、`:2712` 以 `docs/results/model_evidence/<run_id>/MANIFEST.json` 为 H9 归档参数的唯一可信来源）对 5 个非 R1 run（`v4.1-prompt-minimal-v1-seed3411`、`v4.1-phase2-source-aware-v1-seed3407`、`v4.1-phase2-source-aware-v1-seed3411`、`v4.1-phase2-coverage-first-v1-seed3411`、`v4.1-phase2-coverage-fallback-v1-seed3413`）的 H9 归档参数提取将降级为字段级 `unknown`（fail-closed，方向安全）；`docs/results/version-control-migration/verification.md:87` 仍以契约形式描述该来源，与磁盘现实不再对应。影响：今后重跑这 5 个 run 的 `versioning migration` 缺归档包。下一动作建议：若后续需要这些 run 的 versioning 身份，须从 Git 历史（`git show 793dc725:docs/results/model_evidence/<run_id>/MANIFEST.json`）或训练机侧原 run 目录重建归档包；本批不恢复该目录，也不改 `versioning/migration.py` 语义。
- **隔离区不等于已清理**：同盘 `mv` 到隔离区不释放磁盘空间，只有真删才释放；报告“已清理”时必须区分“已隔离”与“已释放”。
- **真删前置条件**：删除任何模型产物前，必须核实 adapter + 训练配置 + 基座三者齐备，缺一不得删；且必须保留 `MANIFEST.json` 等身份证据。
- **首次执行记录（2026-10-17，训练机实测）**：首轮清理将 193 G 移入隔离区 `/home/liuyang/文档/.trash-20261017/`，`/home` 可用空间未变（366 G，同盘 rename 不释放）；第二轮真删 5 个未发布 merged（各 17 G）+ conda setup run（7.6 G）+ 两个旧 venv（2.3 G），共约 91.7 G，`df` 实测 used 524 G → 441 G、可用 366 G → 449 G（+83 G），`du` 与 `df` 差额约 8 G 未解释，如实记录不推断；adapter 保护核实：5 个 merged 目录内无 adapter（`find` 空输出），5 个 adapter（各 455 M）在位，基座在位；项目目录 134 G → 52 G。尚待完成：备份迁移到 `/data`、73 G 与 30 G 两项删除（另单执行中），完成后由后续任务补记。
- **与 RECOVERY-VALIDATION 的关系**：本节给出第一级备份根，但真实整机组合恢复仍未执行，恢复目标路径与恢复操作授权仍缺，该父任务保持阻塞。
- **验收标准**：每次全量训练+评测后有对应归档与 manifest；过期候选清单按体积与建议动作逐项给出且经用户确认后才执行；清理红线三项在每次候选清单中明确排除；备份目录位于当轮活 store 之外（2026-10-17 归位后为 `/home/liuyang/文档/mVllm_2/store`）。
- **证据/限制**：备份根与容量取自 [训练就绪现场记录](results/training-readiness-20260913.json) 的 `df` 记录（`/dev/sda1 3.6T 已用 46M 可用 3.4T /data`、`/dev/nvme0n1p2 937G /home`）与 [连接态准备审计](results/remote-preparation-audit-connected-20261016.json) 的 `df`/`lsblk` 记录（`/dev/sda1 ext4 /data`）；`df -h` 记 3.4 TiB（十进制约 3.74 TB），2026-10-16 推进记录另记约 3.65 TB，属两次不同读数，本台账不把二者当作同一精确值；本条未执行任何归档、拷贝、迁移或删除，未 SSH（该结论对应本条目建立时的记录；2026-10-17 清理执行结果见上方「首次执行记录」）。

### HOLDOUT-BUILD — 构建并授权既定的 test 数据分支

- **状态/来源**：阻塞（代码与接线已实现 abafdbf2：test 数据分支处理、封存发布与最终测试入口；未使用的新 test/holdout 数据未构建（旧 sealed-test 曾构建并已暴露）、原发布目录已缺失、未使用的新 release 未发现；解除条件：取得适用真实构建授权、完成全量人工审查及真实媒体验证（原「核清既定 test source 独立使用资格」已按用户 2026-10-17 裁决视为已定，真实构建尚未执行））；由TEST-POLICY拆出，数据冻结支撑FINAL-TRAIN，最终候选测试支撑MODEL-QUALITY。
- **事实与差距**：既定test分支21个视频及三折隔离已在训练机找到，不再以“source未指定”阻塞定位。旧release `v4.1-sealed-test-5546b8bf1ec3` 的一次性claim与completed/exposed凭据仍在；其摘要20source与332份媒体凭据的20source集合相关联，video_0005无该批候选凭据。原发布目录已缺失，不能把“缺文件”解释为“没用过”，也不能仅据无候选就认定video_0005可独立覆盖七门。当前缺口是正式输入证据与非语义来源清单（使用资格已按用户 2026-10-17 裁决视为已定，见固定标识 `TEST-SOURCE-REUSE`），不是初始划分不存在；未使用的新release尚未发现。
- **数据来源**：定义并人工审查一个独立于开发/调参的 source；沿用 `development_source_isolation_verified`、`test_split_binding_verified` 的隔离要求，纳入前核对 source 边界，避免与现有 sealed-test 或开发验证集混用。按用户 2026-10-17 裁决，本条改为以既定 21 个 test source 重建 test release（见固定标识 `TEST-SOURCE-REUSE`），原「未使用 holdout」表述由该裁决取代；此处所称隔离指相对开发/调参集并不得复用旧 sealed-test 身份与 claim，具体边界以 `TEST-SOURCE-REUSE` 为准。
- **人工审查**：对候选样本执行有效视图/剪裁人工审查（对应 `review_*` 流程），核对批次与 source 分层，形成冻结的 review batch 后再生成 release。
- **发布入口与差距**：test七阶段显式使用`--purpose holdout --test-config ...`，新模块`versioning/holdout_pipeline.py`在owner-only工作区复用媒体算法，所有候选必须人工审查。train默认路径不变。真实输入必须为独立于开发/调参的 test 批次、具备冻结train版本的source清单及旧测试非语义来源清单；当前既定test source已定位（使用资格已按用户 2026-10-17 裁决视为已定，见固定标识 `TEST-SOURCE-REUSE`）；完整非语义来源清单仍须核定。新入口及完整参数/产物来源见[入口说明](../versioning/SCRIPTS.md#test-数据分支处理全量人工审查与封存)。
- **已确认实施与限制**：用户于 2026-09-13 确认 test 分支方案，Mac合成完整builder→claim→prepare→run→score通过。原审查发现真值摘要未校验P1和发布rename后封存尾步恢复P2均修复并专项复核；公开input仅固定整体receipt摘要，真值pin在授权score读取。当前test分支不自动向DVC remote发布受限数据；2026-09-13 源码与 Mac 验证完成不表示真实数据已构建，随后 Linux 同代码 427 passed/1 skipped 通过，见第52节。
- **授权流程**：预注册一次性授权 + one-time claim，沿用现有 stage_d 流程；授权条件 `one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，首次模型调用前原子写入 claim，只允许同一 run identity 恢复。
- **现行旧协议阈值（历史及代码兼容事实）**：`stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **新方案衔接**：已确认的最终视觉门与格式分离规则见[测评方案](model-evaluation.md)，由 EVAL-HOLDOUT 实现；本任务不直接修改旧七门或授权。多Agent匿名访问与受限聚合报告设计已确认；实际调用身份/数据发送和环境须核定，逐样本及公开详情仍受限；来源资格、全量人工审查和封存职责不变。
- **依赖/边界**：本任务只负责构建、审查、发布与授权一个 test release（按用户 2026-10-17 裁决以既定 21 个 source 重建，见固定标识 `TEST-SOURCE-REUSE`），不隐含“策略已确定即已构建”；完成本项不等同于最终模型已通过该 holdout 验收。不得读取现有 sealed-test 受限语义结果来构造 holdout。
- **下一动作**：按用户 2026-10-17 裁决，使用既定 test 分支 21 个 source 重建一份 test release 用于最终测试（三条边界见固定标识 `TEST-SOURCE-REUSE`）；取得适用真实构建授权后按 `review_*` 流程完成全量人工审查、构建并封存新 test release、补齐完整非语义来源清单；真实媒体验证与预注册准备就绪后才可用于最终测试。
- **验收标准**：新的 test release（既定 21 个 source 重建、非盲参考口径，见固定标识 `TEST-SOURCE-REUSE`）已构建并经人工审查，source 隔离与 test-split binding 校验通过，manifest/ground-truth/quality_report及预注册准备可追溯。数据冻结就绪先支撑FINAL-TRAIN；最终model/eval身份确定并获使用授权后，首次模型调用前建立绑定claim，再支撑MODEL-QUALITY。不能要求先有最终模型claim才能训练该模型。
- **证据/限制**：[验证第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)及轻量证据（该记录已随 2026-10-18 清理移除，结论见 `docs/results/version-control-migration/verification.md` 第 48 节）。2026-09-13 已核查新 store 集合与公开入口，未全盘扫描旧sealed-test集合，不推断历史对象已消失；未读取受限语义或创建真实holdout。最终候选model/eval身份形成前不提前创建绑定它们的一次性claim；保留预注册和首次模型调用前claim的要求。

### TEST-SOURCE-REUSE — 既定 21 个 test source 重建 test release

- **状态/来源**：待处理（Pi，2026-10-17；口径已由用户裁决，真实构建未执行，等待适用构建授权）；用户 2026-10-17 裁决：虽然存在“已用于测试的数据不得再用于后续训练”的设计规范，但项目数据总量有限，明确使用既定 21 个 test source 重新构建一份 test release 用于最终测试。父任务 HOLDOUT-BUILD / MODEL-QUALITY；由 TEST-POLICY 原「新建未使用 holdout」策略调整而来，TEST-POLICY 本身保持已关闭且原结论不改。
- **三条边界（用户 2026-10-17 裁决，不得放宽）**：
  1. 这 21 个 source **绝不进入任何训练分支**（含 full 最终训练），`tuning_use: forbidden` 继续有效；train 侧任何入口与 manifest 均不得消费这批 source。
  2. 因这批 source 历史上已被评测暴露，最终报告的测试结论口径为**非盲、参考性**，不得表述为无偏独立估计，也不得作为「数据未被使用」的证明。
  3. test 结果**不得回流**用于调 Prompt、调阈值或挑选 checkpoint。
- **与 HOLDOUT-BUILD 的关系**：本条目只承接口径裁决，不改变 HOLDOUT-BUILD 的阻塞状态；原「核清既定 test source 独立使用资格」按同一裁决视为已定，适用真实构建授权、全量人工审查与真实媒体验证仍未完成，真实构建尚未执行。
- **事实与差距**：既定 test 分支 21 个 source 已在训练机定位（其中 20 个有该批媒体凭据，`video_0005` 无该批候选凭据）；旧 release `v4.1-sealed-test-5546b8bf1ec3` 的一次性 claim 与 completed/exposed 凭据仍在，原发布目录已缺失。按本裁决重建的 test release 须生成新的 release 身份、manifest 与人工审查记录，不复用旧 sealed-test 身份，也不把已消耗 claim 当作可用授权。
- **验收标准**：新 test release 以 21 个既定 source 为来源、经全量人工审查与真实媒体验证；train 侧配置与 manifest 可核未引用这批 source；最终报告明确标注非盲、参考性口径；无任何 test 结果回流记录。
- **证据/限制**：[验证第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)、轻量证据（该记录已随 2026-10-18 清理移除，结论见 `docs/results/version-control-migration/verification.md` 第 48 节）；本条目为口径裁决记录，未构建、未运行、未读取受限测试语义。

### MODEL-DIAG — 诊断并改善三折类别坍缩与契约退化

- **状态/来源**：进行中（Codex，2026-10-16；输入完整性/来源核验已推进，真实诊断未执行）；用户已确认单折诊断后完整三折验证、开发质量门、全样本语义评分及基座公平对比，见[测评方案](model-evaluation.md)。方案确认不是实验授权，不再重复要求确认已确定的阈值。
- **事实与差距**：已同步报告记录 `v4.1-prompt-concise-cv-v1-seed3411` 的 1581 条评测：contract 合法率 79.63%、joint correct 32.07%、`clip_state` 35.80%，322 条非法输出中 311 条缺 `special_case`，“临界未断裂”和“已断裂”召回为 0%。这支持退化症状，不证明 Prompt、采样或早停中的任何一个是单独根因。
- **差距与依赖**：本轮 EVAL-SEMANTICS / EVAL-DEVELOPMENT 已实现 semantic-v4.1、冻结判读导入、逐折召回门、基座及成功折快照登记，新增关键集102项及独立复核通过；真实开发质量证据仍缺。旧 strict-v4.1 记录保留其六指标定义，不能代表新门。partial train 可按真实 FINISHED 折证据进入独立诊断分支，不能伪造完整训练或三折资格。候选基座配置/tokenizer/processor与固定HF版本已匹配，官方MS历史来源亦已追到；构造代码多self.post_init()，框架用途已核，历史来源追查按用户要求取消；仍不能声明未修改官方基座。后续实际data/Prompt及来源视频层级已核（见EVAL-DEVELOPMENT）；试件分组依据后续已由用户确认并材料化；旧训练Prompt、开发/交付预处理及请求差异、实际变体和质量资源预算仍须补齐；不伪造 completed train，不用裸目录绕 Registry。
- **下一动作**：保留原基座与代码差异，移除构造调用历史来源追查，不以取消追查代替可登记来源证明；沿既有新评测协议完成其他输入准备；获相应授权后做基座/多数类参照、对应完整单折 validation 诊断，再完整三折。每轮冻结其他因素，保留逐样本配对改善/退化；不自动引入 canary、任意交叉替换训练 Prompt 或重新划分数据。
- **入口与产物**：保留 `python -m versioning eval prepare/validate/run/export` 的正式身份和原始预测/manifest 链；新语义与逐折判定通过显式 semantic-v4.1 配置接线，不能把新阈值填入旧 strict 配置即运行。历史缺失权重继续记录，不全盘反复搜寻，也不把报告视为可加载模型。
- **验收标准**：每折四状态 macro recall≥65%、每状态 recall≥50%；pooled 语义 joint≥50%、机制 macro F1≥50%、位置 macro F1≥60%；特殊情况完整报告。身份链、原始预测、盲评记录和配对分析可追溯；缺类/来源覆盖不足不自动通过。达到新三折门才支持 FINAL-TRAIN，运行完成与效果改善分别下结论。
- **授权/限制**：只读公开开发证据准备不等待 HOLDOUT-BUILD；本轮仅授权 A/B 代码实施与合成验证，实际训练/推理未授权。禁止使用 sealed-test 调参、修补原始输出伪造合法率或删除受保护 checkpoint。历史现场/环境记录不作为本轮重新验证。
- **证据/限制**：三折报告（该记录已随 2026-10-18 清理移除）、[模型门禁基线](results/model-gate-baseline-20260914.md)、[交付配置](../delivery/model_component.json)。原报告已随 2026-10-18 清理移除，其第 10.2 节「下一轮训练只改受控变量」的内容仅存于 Git 历史（提交 c7a99772），此处仅保留当时结论记录；2026-09-13 在 Linux 重算历史 visual 的 1216 条开发原记录，concise原始预测仍缺且未复算。新增[第48节证据](results/version-control-migration/verification.md#delivery-preparation-20260913)记录三fold模型断链和能力前置，不能据历史输出关闭改善任务。

### RELEASE-POINTER — 安全更新并激活数据 release 指针

- **状态/来源**：待确认（迁移后适用性）；原“release 指针文件更新自动化”。旧指针原目标保留追溯，未授权恢复其活动写入。
- **事实与差距**：原 legacy 指针为手动维护；运行时校验契约内容哈希和 manifest 文件哈希，原方案仅更新两个字段不完整。
- **本轮适用性核定（2026-10-16）**：`finetune.release_validate`省略release-id仍会调用`v4_1_runtime.validate_release`读取旧指针；兼容消费者存在，不能按迁移完成关闭误报。仅精确定位旧消费边界，不恢复写指针，保持待确认且不阻塞新versioning显式身份。
- **下一动作**：先裁决旧指针维护目标在迁移后的适用性；以下保留原目标而非当前执行指令：成功验证后整体原子更新 `release_id`、`release_dir`、`manifest`、`expected_contract_hash`、`expected_manifest_sha256`，记录选中该 release 的依据。构建自己的产物再自算哈希只证明一致性，不冒充独立信任校验。
- **入口与产物**：正式新数据发布走`python -m versioning data release/release_validate`和完整data身份，训练显式选择版本；旧`release_build_phase2.py`CLI已退役。原active_data_release.json作为历史保护证据保留，不能再将修改五字段旧指针写成新release切换前置。
- **依赖**：迁移后本条原“旧指针自动激活”目标适用性待用户裁决；当前不阻塞显式选择新data身份的诊断。若仍需legacy只读消费者维护，先明确精确范围，禁止恢复旧正式写入。
- **验收标准（原目标，待裁决）**：若保留legacy专用维护，五字段同源一致、预检失败不写、原子更新且可追溯；若取消此目标，依据用户决定关闭。新体系以显式完整data身份及冻结引用验证为准。
- **证据/限制**：[运行时](../finetune/v4_1_runtime.py) 的 `_load_active_release_pointer` / `load_release_expectations`；实现未开始，REL-VERIFY 通过不代表本项完成。

### FINAL-TRAIN — 全量开发数据训练最终候选

- **状态/来源**：阻塞；从原“独立测试 release 与 full-data final”拆出，是 MODEL-QUALITY 的前置。
- **事实与差距**：当前发布模型只用 Fold0，`full_data_final: false`；development release 有 1678 条发布候选。候选数不自动等于最终训练行数，训练资格与采样策略仍须冻结。
- **依赖**：MODEL-DIAG 达到开发侧三折标准；HOLDOUT-BUILD 的 test 数据构建/审查/冻结与预注册准备就绪（模型绑定 claim 在最终候选产生并获测试使用授权后、首次模型调用前建立）；适用训练授权。
- **数据粒度与阶段门（用户 2026-10-17 裁决）**：复用已冻结的 `data-v4.1-r2`（1,678 候选 / 85 来源），不重做 ROI 人工审查；「全流程重跑」指训练 → 三折 → 评测 → 性能；上一阶段产物未落盘不得进入下一阶段，见「2026-10-17 用户裁决：执行口径与全局纪律」一节。
- **下一动作/解除条件**：MODEL-DIAG 达到开发侧三折标准、HOLDOUT-BUILD的数据构建/审查/冻结及预注册准备就绪（模型绑定claim在候选产生并获测试使用授权后建立）并取得适用训练授权后，冻结最终数据范围、Prompt、采样、训练日程与模型身份。
- **入口与产物**：独立full能力已由fed9bcfc实现且双机隔离CPU验收；正式入口为`versioning train prepare --scope full`，消费同一开发release全集、每候选一次及显式full配置，继而validate/run/export产生一个full/adapter，登记时`--source-scope full`。详见[新入口说明](../versioning/SCRIPTS.md#独立全量训练)。不再安排重做full代码；真实运行仍等待上列模型、holdout及训练授权前置。
- **验收标准**：全部合格开发数据按冻结方案纳入，未混入测试来源；真实 full 训练及 adapter 执行证据完整，模型与数据/配置/代码/哈希可追溯，保存最终候选及轻量 manifest。完成本项不自动获得 production approval。
- **证据/限制**：[开发 release 摘要](results/v4_1_phase2_development_release/release_summary.json)、[当前模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json)、[模型流程](model-workflow.md)；截至既有记录无全量最终模型证据；2026-10-13只读刷新了限定文件位置，未执行全量训练或模型质量验收。

### MODEL-QUALITY — 最终模型质量验收与晋级

- **状态/来源**：阻塞；原“当前发布模型质量门未通过”，作为总目标，依赖 MODEL-DIAG、FINAL-TRAIN、HOLDOUT-BUILD 及 EVAL-HOLDOUT / EVAL-PERFORMANCE / EVAL-INTEGRATION；HOLDOUT-METRICS 已解决的旧协议实现保留；RELEASE-POINTER原目标适用性另待裁决。
- **事实与差距**：`v4.1-agent-pipeline-fold0-r1` 已用于工程链路验证，但历史质量阶段标志均为 false——`historical_quality_status` 中的 `stage_b_passed` / `stage_c_completed` / `stage_d_passed` / `stage_g_passed` 全部为 false，见[部署摘要](results/v4_1_agent_pipeline_fold0_r1/deployment_summary.json)；`production_approved: false` 见模型注册。标志为 false 不等于每一门都已执行失败，须查各门证据。
- **当前模型定位（用户 2026-10-17 裁决）**：`v4.1-agent-pipeline-fold0-r1` 冻结为参考基线 r0，禁止参与任何准入、晋级或 production alias，仅作后续训练的配对比较锚点；冻结为基线不改变其历史质量标志为 false 的事实。
- **下一动作**：按已确认[测评方案](model-evaluation.md)落实新语义/性能证据与准入绑定；最终候选、测试资格和适用授权齐备后完成一次独立验收。视觉质量、输出使用能力、交互性能分别报告；旧 passed 或历史工程 smoke 不替代新结论。
- **入口与产物**：参照 [发布证据](results/v4_1_agent_pipeline_fold0_r1/README.md) 和 [模型流程](model-workflow.md) 核对执行入口；冻结报告和模型哈希，经注册表发布新身份并同步 delivery，核对服务加载对象。缺可执行入口则先补任务单/实现，不把历史归档命令写成现成流程。
- **验收标准**：预定质量门与身份校验均有证据，模型/报告/注册表/delivery/服务一致；新候选不覆盖旧模型历史结论，工程成功不能替代质量通过。
- **证据/限制**：[交付配置](../delivery/model_component.json)、[模型注册](../pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json) 及现有 sealed-test 公开结果；目前不满足最终交付标准；历史阶段标志的真实所在为[部署摘要](results/v4_1_agent_pipeline_fold0_r1/deployment_summary.json) 的 `historical_quality_status`，模型注册 JSON 不含 stage 字段。

## Skill 改进候选（待确认，不属于当前实现范围）

### SKILL-FEEDBACK — 用实际迭代案例评估 explain-project 的维护能力

- **状态/来源**：待确认；用户要求后续结合经验考虑针对性改进，当前未要求修改 skill。
- **现有规则**：本机 Pi skill 位于 `/Users/pcoffeep/.pi/agent/skills/explain-project/SKILL.md`，模板位于同目录 `references/todo-document.md`。原调查只读核对：它支持初次介绍及后续问答时维护 TODO，但不负责完整任务执行流程；模板“已解决”偏向代码修复，不充分表达误报澄清、远端验收和多 Agent 交接。后续修改前须核对当时版本，不假定其他机器同路径可用。本条所记路径为历史调查时记载，当前本机未复核到该目录，不据此宣称该 skill 现状。
- **案例/候选调整**：REL-VERIFY 是环境验收，CONTRACT-HASH 是误报关闭，都无需业务代码修复；TEST-POLICY / FINAL-TRAIN 体现任务拆分与排序；DOC-INDEX 体现解决后发现文档残留。候选包括证据来源/机器标记、关闭原因、固定标识与拆分关联、新问题去重和交接。
- **下一动作/边界**：继续积累案例，区分项目流程约束与通用文档能力；用户决定修改时再加载适用的 skill 创建/修改规则，选取有证据的最小改动。不把 4090、封存测试或本项目排序推广为通用要求，不宣称 skill 已有当前执行循环。
- **依赖**：用户对“是否修改 explain-project skill 及其最小范围”的裁决；当前不属实现范围，不阻塞其他任务。
- **证据**：本条判断来自历史调查记录；该记录记载的路径为 `/Users/pcoffeep/.pi/agent/skills/explain-project/SKILL.md` 及同目录 `references/todo-document.md`，当前本机未复核到该目录，仓库内无对应产物。
- **验收标准（未来获准修改时）**：改进有案例和边界，保留项目介绍与任务执行职责分离，用初次创建、后续更新、误报关闭、执行中新发现等案例验证；当前只记录候选。

## 已解决与已关闭

### EVAL-SEMANTICS — 全样本语义评分与多 Agent 判读

- **状态/来源**：已解决（2026-10-15，Codex，批次 A 纯基础能力）；用户授权按已确认方案实施代码及合成验证，父目标 MODEL-DIAG / MODEL-QUALITY 不因此关闭。
- **结果**：新增 `finetune/eval_semantics.py`，严格/规则/离线盲评/不可读互斥分支、缺失与显式 null、全样本分母、GT 适用子集、状态召回/机制位置 F1/特殊类 P/R、来源组 bootstrap 均已实现。参与者/规则/手册与结果封存、先独立后仲裁及未完成状态可审计；正式接线保留全部故障尝试、成功初判锁定和最多一次故障 retry，不能挑答案。
- **验收证据**：主 Agent 最终执行四个新增测试文件：102 passed，64.23s，退出码0；其中语义28、baseline30、来源30、开发接线14。独立 reviewer 已核分母/缺类/规则漂移/仲裁顺序与成本/恢复拒绝逻辑，无剩余可执行问题；详见[实施记录](results/evaluation-development-implementation-20261015.md)。提交由相关文件 git log 追溯。
- **交接/限制**：原始严格合法率独立报告；评审未完成不给最终视觉率或 passed，不补模型未表达字段。匿名包/seal 不证明真实低权限隔离，本机 Ollama 调用与实际隔离由 EVAL-HOLDOUT 继续完成；本轮仅合成数据，不证明模型质量。

### EVAL-PROTOCOL — 已确认测评方案与差距实施计划入库

- **状态/来源**：已解决（Codex，2026-10-15，本机文档补充）；用户明确授权落项目文档、列功能缺口与实施计划、同步 TODO，禁止改代码或运行模型。
- **本批补充**：四项前置设计已确认，评审从多人改为可扩展多Agent（默认2+分歧第三）；同步方案/计划/现行说明与TODO，不把设计确认记为功能完成。本批独立源码核查通过，139个本地链接/锚点有效、37个原固定标识完整且唯一、视觉门槛表与前版一致；6文件仅Markdown，diff检查通过。只关闭文档，不关闭功能或真实验收。
- **前批交付范围**：[完整方案](model-evaluation.md)、[实施计划](plans/model-evaluation-implementation.md)及模型流程/现状/根导航/接口索引的边界同步。方案来自本会话逐项确认；实际能力以 b827f73f 本地源码核查为基线，不引用旧模型历史测试为本轮运行。
- **验收标准**：数值与用户确认一致；开发、full与一次性test、性能各环节输入/现行入口/产物可追溯；拟新增能力不写成现成命令；新旧协议、权限/待决接口和授权边界明确；原任务标识保持、链接及 diff 检查通过，并经独立 reviewer 对照源码核查。
- **前批验证/限制（ee2b3af2）**：独立 reviewer 已对照契约、严格评分、holdout/Registry及服务实现核查通过。首轮发现单折 partial 无法登记、受控测量加载与最终准入依赖未闭合两项缺口，已写入实施前置并专项回验，无剩余可执行文档问题。179 个本地链接/锚点有效，原31个固定任务标识保留、现37个唯一，8个变更文件全为 Markdown，`git diff --check`通过。提交由 `git log -- docs/model-evaluation.md docs/plans/model-evaluation-implementation.md docs/project-todo.md` 追溯；仅本机文档，不SSH、pytest、训练、推理、评测、test语义读取或push/merge，后续实现任务全部未关闭。

- **本批验证/限制**：独立 reviewer 已复验来源/折证据、严格评分/旧七门、claim/truth-access/consumed及服务实现，并核对多Agent初判/仲裁可见性和批准端点边界，无剩余可执行文档问题。本批无pytest、业务、SSH、真实Agent判读/发包、训练、推理、评测或push/merge；具体实施版本沿用本条git log追溯。

### CONTRACT-NAMING — 候选规划与训练发布契约边界：已解决

- **状态/来源**：已解决（Codex，2026-10-16）；按当前可执行TODO授权完成原澄清目标，不引入模块重命名。
- **结论/变更**：两个candidate模块仅补module docstring，说明候选规划校验tensile-vlm/v3、媒体绑定计划/处理器/编码，下游V4.1审查/训练发布另载契约；pipeline/SCRIPTS和数据指南一致。新versioning仍显式完整身份，legacy重建仅为复用关系证据。
- **验收/证据**：两模块去除module docstring后与a0f1e1ab完整AST相同，imports/函数/身份构造未变，源码SHA不参与候选/媒体派生身份；compileall/diff-check和独立核查通过。见本轮记录（该记录已随 2026-10-18 清理移除）、[模块索引](../pipeline/SCRIPTS.md#候选规划与媒体物化的契约边界)、[数据指南](data-workflow.md#候选层与发布契约)。纯文字澄清，未另跑业务测试、真实模型或真实test。

### REMOTE-STATE-REFRESH — 训练机现状只读刷新

- **状态/来源**：已解决（2026-10-13，Codex）；用户授权只读现状核查，禁止远程写入、同步代码、训练与评测。
- **结果**：训练机 main 与实时 Codeup main 均为 `3f200461` 且训练机/子模块干净；Mac 起始 `59dee2d1` 比该基线领先 5 提交。Conda agent/cpm45 为 Python3.11.15，但当前锁依赖与源码绑定仍有缺口；历史 mirror venv 绑定隔离 checkout。r2 active，1678 个去重媒体引用 stat 缺失0；旧Fold0与基座索引分片在场，concise/visual在限定路径仍有权重缺口；指定store正式运行记录尚未产生。
- **后续/依赖**：MODEL-DIAG、MODEL-ARCHIVE 与 RECOVERY-VALIDATION 保持原状态；ENV-ACTIVATION由随后获授权的新Conda环境部署解决；正式 Registry 配置根与模型来源随环境/诊断准备核定，不据指定目录缺失推断全盘无记录。
- **验收/证据**：[现场报告](results/remote-state-refresh-20261013.md)、[返回快照](results/remote-state-refresh-20261013.json)记录机器、起始版本、命令、退出结果、覆盖范围与限制；独立reviewer已核查返回快照、锁项与正文链接；普通git status潜在索引刷新偏差已披露，无其他可执行问题。报告及台账提交由 `git log -- docs/results/remote-state-refresh-20261013.md` 追溯。
- **限制**：模型盘点一次普通git status可能刷新.git/index，未采集前后元数据，不能证明或排除；这不影响工作区内容干净的结论。没有加载模型、导入torch、执行doctor、读取测试语义、哈希大型产物或全面验证媒体链接/解码；不存在性结论限指定路径。只读刷新完成不代表正式Conda合格、真实质量/test/服务或恢复通过。

### ENV-ACTIVATION — 正式解释器与最终 checkout 绑定

- **状态/来源**：已解决（Codex，2026-10-13）；用户同意按当前GPU锁新建Conda Python3.11环境、保留旧环境并绑定正式checkout。
- **结果**：训练机 `/home/liuyang/miniconda3/envs/mvllm2/bin/python` 为Python3.11.17；GPU锁241个精确项缺失0/版本差0，244包兼容检查通过，doctor errors为空、CUDA可见且训练模块导入通过。LlamaFactory editable绑定正式 `/home/liuyang/文档/mVllm_2/LlamaFactory`，checkout/submodule为3f200461/4447137e且保持干净。
- **保护与后续使用**：agent/cpm45的发行包元数据、conda-meta和指定pycache快照前后相同；没有修改用户shell默认环境。后续显式使用新Conda解释器，checkout/依赖/子模块变动后重新核验绑定；历史venv和旧环境继续保留，不重新打开已解决部署功能任务。
- **验收/证据**：部署报告（该记录已随 2026-10-18 清理移除）、执行快照（该记录已随 2026-10-18 清理移除）；安装及审计SSH均exit0，冻结脚本通过独立执行前审查，结果独立核查通过：脚本身份及返回快照一致、241锁项和旧环境保护证据匹配，原31任务标识保留，83本地链接/锚点有效；未关闭模型/test/恢复任务。Mac本地记录提交由 `git log -- docs/results/conda-environment-setup-20261013.md` 追溯。
- **限制**：没有同步代码、初始化业务store、处理媒体、加载模型、训练、推理或评测；环境验收不关闭模型/test/真实服务及恢复门槛，旧环境摘要比较不等于所有文件逐字节审计。
- **凭证降级说明**：原始验收凭证已随 2026-10-18 清理移除，本条为历史结论记录，不再作为当前可复核凭证。


以下保留前序任务原验收依据，历史测试未因文档整理而复跑。工程任务关闭不自动关闭模型、test 或真实恢复验收。

### DOC-INTEGRATION — 正式整合项目文档目录：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户认可四份说明并授权正式替换根README、清理覆盖旧说明，保留任务台账、设计决策和原始验证证据。
- **结果/验收**：正式入口为根README与docs下data-workflow、model-workflow、project-status；删除七份重复说明及候选目录，完整归档模型现场基线、模型清单和阶段一审计报告。同步AGENTS/架构/接口索引和停用CLI提示导航，不改变运行入口行为或授权。Mac uv、训练机Conda Python、3.11.x及两平台依赖分工保持。
- **独立核查**：reviewer结论通过，无可执行问题；冻结版本50份Markdown、289个本地链接/锚点0错误，25个shell块语法通过。原30个任务标识保留，31标识唯一；65份非Markdown原结果、ADR/迁移确认链/研究材料及决策日志完整性核对通过，归档统计和清理标准未丢失；十个Python变更严格仅停用提示路径文本。
- **证据/限制**：正式整合记录（该记录已随 2026-10-18 清理移除）；提交由 `git log -- README.md docs/project-todo.md` 追溯。本轮不执行pytest、业务CLI、安装、UI/server、SSH、实际数据处理、训练、推理或评测；历史结果未复跑，不关闭模型/test/Conda现场或真实恢复缺口。下一步仍为REMOTE-STATE-REFRESH。
- **凭证降级说明**：原始验收凭证已随 2026-10-18 清理移除，本条为历史结论记录，不再作为当前可复核凭证。

### README-PUBLIC-INTRO — 项目介绍与新人快速开始：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户要求根README面向首次访问者介绍项目概念、实际用途、初步成果及快速开始。
- **结果/验收**：README以项目介绍和快速开始为核心，解释窗口采样/四字段、ROI/LoRA/三折，介绍历史Fold0开发集成果并保留未通过最终独立test的限制；给出两平台部署、检查入口、资产前置和分目标手册导航。没有虚构公开下载、许可或可直接推理的演示。
- **独立核查**：reviewer对照部署脚本、锁文件、子模块、契约、历史逐项结果及Registry，结论通过，无可执行问题。用户已有顶部治理块删除保留。
- **证据/限制**：[验证第69节](results/version-control-migration/verification.md#readme-public-intro-20261012)；文档命令未运行，未安装、SSH、训练、推理或评测。提交由 `git log -- README.md` 追溯。

### DOC-CONSOLIDATION — 现行文档与任务台账收敛：已解决

- **状态/来源**：已解决（Codex，2026-10-12，本机）；用户授权统一迁移后状态、正文和导航，保留设计/决定/验证证据，清除过期下一动作并独立核查。
- **结果/验收**：前序现行数据、训练与服务正文退出旧 CLI 操作；当前状态、完整数据身份与入口导航一致。工程迁移等已解决事项统一进入关闭区；MODEL-DIAG 待确认，模型/test/真实恢复限制保留。已执行 Plan 保存范围、选择与最终矩阵，详细历史仍在验证记录和 Git。
- **后续成果**：新候选手册在 `389c797e` 完成交付及独立核查，`f8af0bba` 修复 ROI 直接文件导入并统一 Mac uv/训练机 Conda Python 及 Python 3.11.x；具体实际检查和限制见文档整理记录（该记录已随 2026-10-18 清理移除）。这些结果没有刷新训练机或关闭真实环境、模型/test 与恢复缺口；正式目录切换由 DOC-INTEGRATION 承接。
- **独立核查**：reviewer 对照代码及历史证据核查17份正文；首轮服务模板路径 P2 已修复并复核，最终无剩余可执行问题，结论通过。输入来源、七阶段产物、UI交接、claim/评分、alias服务参数及证据边界均静态核对。
- **证据/限制**：[验证第68节](results/version-control-migration/verification.md#document-consolidation-20261012)记录该次覆盖、检查和限制；该次未 SSH、训练、推理、评测、运行应用或 pytest，历史动态结果未复跑。提交由 `git log -- docs/project-todo.md` 追溯。

### VERSION-CONTROL-FORMAL-MIGRATION — 正式迁移可读版本控制体系：已解决

- **状态/来源**：已解决（已确认工程范围，2026-09-14）；用户授权先模型调查落文档、再推任务分支、后合并 main；`5acebc27` 按序进入 Codeup main 并同步训练机正式代码，双机 CLI 核验通过。
- **关联与已确认范围**：[Intent](tasks/2026-09-07-readable-version-control-migration/intent.md)、[Spec](tasks/2026-09-07-readable-version-control-migration/spec.md)、[已执行 Plan](tasks/2026-09-07-readable-version-control-migration/plan.md)。承接核心基础设施，迁移两个已发布 data 与一版 Prompt，保留历史模型事实，接管活动入口；单写、完整身份、恢复不丢事实及原质量门保持。
- **结果/验收**：数据真实媒体对照、审查包双机往返及 r1/r2 内容保持完成；训练/评测/服务执行接线、旧 CLI 退役、store 异根恢复、七门、test 分支、部署及逐折工程验收完成。最终整包及后续增量独立审查、授权集成、双机代码落点已闭环。
- **证据**：[验证记录](results/version-control-migration/verification.md)第12–24节（迁移与真实媒体）、25–47节（接线/退役/恢复/完整审查）、48–55节（交付与模型/test证据）、59–65节（输入/部署/逐折）、66–67节（最终范围与集成）；[入口清单](results/version-control-migration/entrypoint-map.md)、[交接](results/version-control-migration/handoff.md)。历史详细施工记录由验证记录与 Git 追溯，不再作为下一动作。
- **保留限制与后续任务**：新 store 引用原 workspace 媒体，不能删除被引用路径；真实 GPU 训练、独立 test、最终质量与真实服务成功路径归 HOLDOUT-BUILD / MODEL-DIAG / FINAL-TRAIN / MODEL-QUALITY；真实大型/外部依赖组合恢复归 RECOVERY-VALIDATION，正式解释器激活归 ENV-ACTIVATION。远端记录未在本次2026-10-12整理中刷新，不把 CPU 工程验收写成模型效果通过。


### HOLDOUT-METRICS — 已冻结七项holdout门槛与正式评分入口衔接

- **状态/来源**：已解决（Codex，该批代码/CPU范围，f1be1060）；HOLDOUT-BUILD该批准备发现，用户已明确“确认，按原七项门槛补齐”，Spec55b3f4d4/Plan061d2598已单独提交。保持TEST-POLICY原定义和阈值，validation不变。
- **发现时基线事实（第48节，修复前）**：`finetune/eval_run.py::_formal_config`当时仅接受六项通用正确率，holdout共用此配置与最小值比较。七项既定门槛中仅`joint_correct_rate`可原名表达；宏召回、两类召回、runtime失败数及strict合法率均不能原样输入。纯配置反例拒绝七项、单joint控制通过，未访问数据/Registry。
- **完成结果**：已接入七门完整配置、私有数值指标及公开二值gate，Mac两进程614 passed/1 skipped、Linux首组加拆组167/240合计614 passed/1 skipped，实际各exit0，独立93项及篡改/Registry探针通过。Linux原合并组文件句柄耗尽exit1保留，不声称单进程通过。原f04ca7cb定义核对：runtime失败数等于0，其余为下限，缺四状态拒绝；原函数200组合成差分一致。不自动重命名或遗漏门槛，也不把全部指标当下限。
- **验收标准**：七项可冻结并与预注册精确一致，原输出重算可追溯；缺类、非法输出、runtime失败、边界值、恢复及下游准入均按原规则决定，不消费真实测试集来验代码。
- **证据/限制**：[第48节](results/version-control-migration/verification.md#delivery-preparation-20260913)、轻量JSON的`threshold_probe`；第48节保留缺口发现快照；该批已按确认实施，最终验证与代码版本见第49节。既有整包代码审查保留原冻结范围，新增变更另行验收。

### DOC-INDEX — 修正脚本索引的过期缺陷描述

- **状态/来源**：已解决；关联已解决的 PIPE-INDEX，该批 M7a 文档同步完成。
- **结果**：脚本索引已删除“promote 未传播 source/split 索引”的过期描述，说明历史 promote 业务函数在快照移入正式 workspace 后更新集合索引，同时标明公开 rebuild_data CLI 已停用。
- **验收/证据**：对照 `pipeline/data_rebuild.py::_update_snapshot_collection_indexes` 及 promote 中的调用顺序核对；实现来源 `cdb8632c`，该批仅修正文档。历史业务联合回归本机 57 passed；修改提交由 `git log -- pipeline/scripts/SCRIPTS.md docs/project-todo.md` 追溯。
- **限制**：不重新开放 legacy CLI，不代表索引库已退役；未执行真实数据 promote。

### M8-R7 — 训练入口路径优先级测试依赖全局导入顺序：已解决（该批范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务整仓测试在 `e1d70c58` 发现，原第46节为失败证据。
- **已证实事实与修复**：原测试受其他测试收集时的 `sys.path` 变动影响。路径优先级断言现由新 Python 进程验证，训练器对实际 LLaMA-Factory 模块来源的运行时拒绝门保留。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：原失败顺序组合 Mac/Linux 各 1 passed/49 deselected、exit0；Mac 整仓 2694 passed/11 skipped、实际 exit0；独立复核另验证错误实际来源仍被拒绝。11项 skip 均因本机历史数据/fixture 缺失，不代表真实模型效果。

### M8-R6 — 外部训练初始化权重未纳入冻结输入：已解决（该批范围）

- **状态/来源**：已解决（Codex；代码 `d9ec1227`）；父任务完整独立审查在 `e1d70c58` 发现 P2，原 adapter/checkpoint 漂移反例见第46节。
- **已证实事实与修复**：当前契约不支持外部 adapter 或 checkpoint 初始化/恢复；CV/full 的 prepare 在冻结前拒绝两类非null配置，旧冻结记录在 validate/run/export 与 Registry 训练证据门拒绝。旧完成/失败事实不改写，缺少来源证据的模型不能登记或进入后续准入。
- **验收与证据**：[验证第47节](results/version-control-migration/verification.md#m8-r6-r7-20260913)：Mac 相关179项、Linux同组179项各exit0；独立审查重用原两类漂移 fixture，旧记录各拒绝且Run/ModelVersion/状态/params不变；整包代码差异审查对140提交/152文件结论通过。上述为CPU合成验证，未声称外部权重路径已获支持或真实GPU训练通过。

### M8-R5 — 服务Prompt来源未与被评冻结输入绑定：已解决（该批范围）

- **状态/来源**：已解决（该批实现范围；Codex；用户2026-09-13确认兼容策略，Spec789fa4fc/Plan511cfc14）；父任务VERSION-CONTROL-FORMAL-MIGRATION的最终完整独立复审发现P2，代码ab5c71ae。
- **已证实事实与差距**：第43节发现时，prompt-v4.1-r1保持原concise-v2内容，与固定service analysis的system/user不同。独立CPU链路在真实证据门下构建合法candidate后，server_proxy.main仍在加载器前拒绝；不是缺alias的允许拒绝，不能宣称此Prompt对应模型端到端可服务。反例还证明同ID当前定义替换为固定契约后，resolver指纹不变且错误放行服务，未与训练/eval冻结内容绑定。
- **已确认决定与结果**：用户2026-09-13已确认采用模型冻结并验签的Prompt，保持输出/评分/alias/审批/备份门禁，并同步请求识别、重试和交付契约。Spec789fa4fc/Plan511cfc14记录，代码de1b51dd已实现。Mac广回归195 passed/1 skipped及新增5项通过，独立25+5项和操作说明通过；Linux最终200 passed/1 skipped、两组exit0，保护文件保持；该批R5闭环。后续实际GPU加载/模型效果另验；父任务full/holdout接线及双机隔离CPU验证已完成（fed9bcfc，第45节），第46节原整包驳回已由第47节R6/R7修复及更新的独立代码审查闭环，真实holdout仍未验证。
- **验收标准**：当前迁移Prompt的合法模型可以通过实际服务CLI路由并使用其冻结输入；不兼容输出结构、模型版本/文件漂移、非法alias继续拒绝。训练/eval冻结Prompt及其摘要必须进入服务绑定，当前同ID内容漂移在加载前拒绝。CPU替身证据与GPU模型加载/效果证据分别标记，不将修复外推为模型质量通过。
- **证据/验证限制**：[第43节](results/version-control-migration/verification.md#m8-final-20260913)，pipeline/server_proxy.py:447–452；独立fixture`/private/tmp/mvllm2-final-concise-service-0bdr7oux`。修复证据见[第44节](results/version-control-migration/verification.md#m8-r5-prompt-20260913)，代码de1b51dd；旧行号/fixture仅追溯发现时事实。未运行GPU或读取受限测试结果，不以该批局部通过代替整体验收。

### M4-FOLD — 三折分次执行入口

- **状态/来源**：已解决（本批工程实现，61effebd）；用户确认逐折接口与复用/partial规则并授权工程实施，Spec b1aaf315、Plan902d8c9d。
- **发现时事实（修复前，e7efb56b）**：prepare需要三折完整配置；当时run循环执行全部折，已存在任一输出即拒绝；底层有fold子Run，但不能绕过公共入口手工记完成。2026-09-14核对e7efb56b：CLI虽然解析`--fold`，train run未传入执行器，不能用该参数实现单折；详见verification第64节。
- **已确认方案**：同一train版本冻结三折，`train run --fold 0/1/2`仅执行指定折；省略`--fold`保留整组三折行为（续办时仅执行未完成折），full拒绝`--fold`；分次执行同一父Run，已完成折验签复用不重训，部分成功不标整组completed；三折真实证据齐全后汇总；full独立。失败折不自动覆盖或续训。
- **验收**：逐折真实适配器调用边界用合成替身验证，子/父状态与产物一致；已完成折不重跑、并发/漂移/失败保留、缺折不晋级、旧full行为不退化。无需为了此功能启动实际模型训练。
- **结果/限制**：实现及独立审查通过；Linux 最终 123 项合成回归通过，见验证第65节；集成已完成（第67节）。真实训练与模型效果不在此工程验收内。


### ENV-DEPLOY — 环境依赖与可重复部署

- **状态/来源**：已解决（本批部署实现与双平台新环境验收，83724995）；用户确认统一部署入口与隔离验证，未修改旧环境。
- **发现时事实（修复前）**：见verification第62节。agent现有GPU训练依赖自洽但缺DVC/MLflow/cropper；cpm45有7缺包和4版本冲突且editable来源旧项目；隔离环境为CPU集成环境且pandas违反MLflow声明。README缺少cropper安装；finetune说明引用不存在的requirements/minicpm-v.txt。pyproject与GPU依赖的AV区间不兼容，不能直接合并安装。
- **实施结果/剩余边界**：已实现Mac轻量/Linux GPU锁定配置、兼容DVC/MLflow/pandas、cropper、单入口与doctor，双平台新环境通过；详见第63节。正式激活解释器须结合最终checkout路径核定，不能让editable引用被删除；正式激活另记 ENV-ACTIVATION。
- **验收**：新建环境可按文档自动部署，pip check无冲突，DVC/MLflow及活动CLI可导入，LLaMA-Factory来源正确、ffmpeg/ffprobe可用；Mac不装GPU栈，Linux明确CUDA包；合成链路与入口验收通过，过程不训练模型或使用test。
- **前轮核查边界（第62节）**：当轮仅包元数据、pip check和文件审阅；没有下载解析安装测试、安装依赖、改环境或训练。pip check通过仅证明已安装包声明不冲突，不证明项目所需包完整。


### VERSION-CONTROL-MIGRATION — 可读版本控制核心基础设施：已解决

- **结果**：`refactor/readable-version-control` 已完成 B0–B12。新增独立 `python -m versioning` 六领域入口、五类完整可读身份、数据封存与 DVC 七阶段、Prompt 冻结、MLflow train/eval、不可覆盖 manifest、唯一 `mVllm2` Registry、严格 model layout 与 alias/current、分级离线备份及灾难恢复；当时尚未进行 legacy 入口迁移。
- **最终证据**：核心修复提交 `9965dc1b`；`tests/versioning/` `1399 passed`，整仓 `2082 passed / 11 skipped`，均正常退出；9 个目标 Markdown 本地链接、2 个 YAML、172 个 tracked JSON、编译、CLI help、diff/未跟踪/大文件检查通过。独立 reviewer 对 R1–R11 执行相关套件、故障注入、备份恢复与跨进程锁攻击，结论为无剩余 P0–P3 actionable finding。完整提交与 finding 证据见[实施台账](plans/2026-09-01-readable-version-control-implementation.md)。
- **验证限制**：未连接训练机，未执行 GPU/真实模型/正式数据/真实移动硬盘操作；`fcntl.flock` 已在当前 macOS 双进程验证，基础设施验收时 Linux 训练机 smoke 尚未执行（随后正式迁移已补）。未 merge、未 push、未正式迁移或删除 legacy。
- **后续拆分**：正式迁移另记 VERSION-CONTROL-FORMAL-MIGRATION，按用户单独确认与授权实施；该正式迁移现已解决，核心基础设施的历史关闭依据不变。

### AGENT-INSTRUCTIONS — Codex/Pi 共用指令契约修正：已解决

- **结果**：项目根 `AGENTS.md` 补建 Document Contract；新体系身份明确为 `<kind>-v<协议>-r<N>`，legacy ID/index 规则整体限定到 `pipeline/`、`finetune/` 旧入口；提交尾注按 Codex/Pi 真实执行平台区分；临时分支状态、SSH 明细、评测字段明细和 skill 起源历史从长期根指令移出或下沉，委派要求改为平台无关的结果约束。`ARCHITECTURE.md` 的三处身份简写同步修正。
- **Pi 配套**：Pi 用户级 `SYSTEM.md` 增加项目约束传递字段和 Gate；Pi 用户级 `AGENTS.md` 的平台名称修正。Pi 的具体角色集合继续由其用户级配置独立维护，不在项目根 Instruction 中复制。
- **证据/限制**：`versioning` 身份测试、Markdown 链接检查、Document Contract/Decision Log 唯一性、Pi JSON/frontmatter 静态校验及 `git diff --check` 作为该批验收；未连接训练机，未启动真实 Pi 模型会话，也未执行图片生成任务。Pi 用户级文件位于仓库外，不随项目 Git 提交同步到其他机器。

### RUNBOOK-CONTRACT — 数据处理运行手册初始契约化与版本解耦：已解决

- **结果**：为当时的 `docs/DATA_PROCESSING_RUNBOOK.md`（现行说明由[数据处理](data-workflow.md)承接，原文可查 Git）补建独立、精简的 Document Contract；标题和长期定位不再绑定特定链路版本，正文集中声明当前数据处理链路版本为 4.1，并保留候选计划使用 v3、审查与发布使用 v4.1 的真实契约边界。README 导航已同步。
- **文档决定**：文档级 Decision Log 的 D001 记录继续维护单一、不带版本号的主手册；版本升级时同步核对版本声明、版本特有路径、命令、默认值和验收条件，不只替换版本号，也不另建平行主手册。
- **证据/验证限制**：本地 `git diff --check`、两个治理块唯一性与本地 Markdown 链接检查通过；脚本默认值静态核对支持 v3/v4.1 边界。独立 reviewer 首轮发现 Contract 将统一 resolver 能力错误泛化到 `review_decisions` 的 P2，修正为保留各集合解析与路径边界后复审通过、无剩余可执行问题；reviewer 另执行 2 个相关测试，结果 `2 passed`。该批未连接训练机，未运行 GPU、媒体物化或完整发布链路，不能据此宣称重新认证了手册中的全部既有命令。

### TEST-POLICY — 后续独立测试策略已确定：已关闭

- **关闭依据/用户裁决**：用户按建议执行① 新建未使用 holdout 测试集（是）；② 现有 sealed-test 不复测（否）；③ 新 holdout 阈值沿用已冻结值。策略据此确定，本任务关闭。
- **选定策略**：最终候选模型的独立验收采用新建的、未使用的 holdout 测试集；现有唯一 sealed-test `v4.1-sealed-test-5546b8bf1ec3` 仅作历史参考/回归监控，不复测、不调参。
- **决定依据**：唯一 sealed-test 已暴露且一次性（`passed: false`、`sealed_test_exposed: true`，预注册用途 `one_time_sealed_clip_evaluation`、约束 `tuning_use: forbidden`、`one_time: true`、`resume_policy: same_identity_only`）；本地 `finetune/results/v4_1_stage_d_claims/` 与训练机 `sealed_test_releases/` 均只有这一个 release，无未使用 holdout（两路独立证据印证）。
- **适用模型**：最终候选模型（FINAL-TRAIN 产出的候选）。
- **source 隔离要求**：沿用 `development_source_isolation_verified: true`、`test_split_binding_verified: true`，holdout 数据须独立于开发/调参的 source。
- **阈值冻结时点**：沿用 preparation `stage-d-preparation-5cd1b3fa343c` 已冻结的 7 项阈值（`four_state_macro_recall 0.4006`、`fracture_three_state_macro_recall 0.3`、`joint_correct_rate 0.3921`、`runtime_failure_count 0`、`strict_valid_rate 1.0`、`已断裂_recall 0.15`、`未断裂_recall 0.7`）。
- **授权条件**：`one_time`、`tuning_use: forbidden`、`pre_stage_g_outputs: aggregate_pass_fail_and_integrity_only`，沿用现有 stage_d 预注册一次性授权 + claim 流程。
- **证据/限制**：现有 sealed-test 证据位于 [公开结果](results/v4_1_stage_d_sealed_test_release/public_gate_summary.json)、[阶段记录](results/v4_1_stage_d_sealed_test_release/README.md) 及 `finetune/results/v4_1_stage_d_*`（授权/claim/run）；新 holdout 证据位置由 HOLDOUT-BUILD 任务执行时定义。本项只记录策略与依据，不执行推理或调参。
- **2026-10-17 调整**：用户 2026-10-17 裁决改用既定 21 个 test source 重建 test release，见固定标识 `TEST-SOURCE-REUSE`；本条保持已关闭，关闭依据与选定策略原文不改。

### REL-VERIFY — 训练机 release 指针实证：已解决

- **关闭依据**：前序 Agent 记录在训练机 `/home/liuyang/文档/mVllm_2` 执行 `python finetune/release_validate.py --verify-media`，退出码 0，`release_id: v4.1.0-ecb5aeb9657c`、`contract_version: tensile-vlm/v4.1`、`media_verified: true`。
- **核对值**：契约内容哈希 `47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937`；manifest 字节哈希 `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`，对应指针的两个钉扎字段。三折 train/validation 计数为 1253/425、1014/664、1186/492。
- **证据/限制**：[指针](../finetune/active_data_release.json)、[验证入口](../finetune/release_validate.py)、前序写入本文件的训练机记录及用户确认。该批未重跑；前序未附执行 HEAD 和独立日志路径，不补造这些信息。`0ffecb3a` 是校验代码历史版本，不是远端执行版本。

### CONTRACT-HASH — 历史 v3 契约哈希差异：已关闭（误报）

- **关闭依据**：前序 Agent 核对训练机历史 manifest，确认是哈希口径混淆，并非契约丢失；据其记录，本地/训练机契约文件与 Git `033d82b4` 版本逐字节一致。
- **核对值**：文件 SHA-256 为 `e963cddff086114d5501392355ee64347e616c9b383f837f7293030b664d64af`；规范化内容哈希为 `3f9f8217774cb4947fc4e19e41a5fe14b8a5ea30c8e84ed4f664abddd9de04f0`，与内嵌哈希及历史 `identity.inputs.tensile_vlm_v3_contract_sha256` 一致。
- **证据/限制**：[契约](../pipeline/contracts/tensile_vlm_v3.json)、[算法](../pipeline/v3_candidate_plan.py)；训练机历史路径 `workspace/data/derived/metadata/v3/candidate_plans/candidate-plan-ce36b9226be5/manifest.json`，前序记录 plan_id 为 `candidate-plan-ce36b9226be5`。关闭的是“契约丢失”误报，不把字段一致性扩大为该批完整重建所有历史计划成功。原记录版本 `e027e82e` 只追溯问题来源。

### PIPE-INDEX — promote 不传播快照索引：已解决

- **结果**：`pipeline/data_rebuild.py` 在锁内、状态落盘前更新 source/split 集合的 index.json 与 LATEST，校验后写入，重入幂等且缺必要输入时 fail-closed。
- **证据**：修复提交 `cdb8632c`；`_update_snapshot_collection_indexes`、`tests/test_data_rebuild.py`。前序测试记录 `uv run pytest tests/ -q`：682 passed、12 skipped，并记录 reviewer 复验；该批只核对提交和代码，未重跑。
- **残余**：脚本索引过期描述已在 DOC-INDEX 修正，不影响原代码缺陷关闭。

### PIPE-STATE — rebuild 首跑状态跳转缺失：已解决

- **结果**：允许 `source_snapshotted` 转入 `waiting_for_roi_review`，无预置 ROI 决策的 review 模式首跑可等待人工标注，复跑幂等。
- **证据**：修复提交 `cdb8632c`；`pipeline/data_rebuild.py`、`tests/test_rebuild_source_only.py`。前序全量测试和 reviewer 记录同 PIPE-INDEX，该批未复跑。

### ROI-DEFAULT — ROI 标注默认 metadata 路径失效：已解决

- **结果**：`pipeline/scripts/roi_annotation_app.py` 从 source_snapshots 的 LATEST 解析 video_meta.json，支持显式路径/ID/前缀；缺 LATEST 或前缀歧义时 fail-closed。
- **证据**：修复提交 `cdb8632c`、`tests/test_roi_annotation_app.py`；前序全量测试和 reviewer 记录同 PIPE-INDEX。`f6881883` 为历史文档版本，不再标为未提交修复。
- **残余**：Streamlit 显示原始 ValueError traceback 是此前接受的呈现层风险；该批未重新验收 UI。

## 最近维护记录

- **2026-10-18（Pi，清理与信息分层 + R2 训练待办入账）**：按用户 2026-10-18 指示，把「新一轮 R2 数据的真实训练与评测」登记为固定标识 `R2-REALTRAIN`（原 39 个标识增至 40 个，其余标识与全部既有阈值、状态、验收标准零改动，本轮无任务被关闭或升级），并在「当前状态与下一步」顺序表新增一行定位「待清理收尾后」，明确该任务排在当前清理收尾之后、后续按时间推进。条目如实区分已核事实与推算：数据与 Prompt 身份、开发评测侧对齐、门禁路径属有证据的就绪项；r2 训练 YAML 不存在、GPU 训练授权未给、训练预算仅为推算（3 epoch 三折约 5.78 h）属未就绪项；R1 与 R2 不可直接比较的限制一并写入。本轮清理与信息分层另有两路只读审计并行进行（不写文件），本条只做台账登记，未训练、未评测、未读 test、未 SSH、未改动任何产物或代码；仓库外证据路径均标注「仓库外，他机不可达」，未写作相对链接。

- **2026-10-17（Pi，store 归位口径转既成事实 + Prompt 一致性核查）**：按用户 2026-10-17 指示，把 `docs/project-status.md` 机器与资产位置表及本文件 `ARTIFACT-RETENTION` 内 store 迁移口径由「已授权／结果待核」改为已完成（2026-10-17 归位至 `<项目>/store`、逐文件 sha256 48/48 一致、旧目录改名 `/data/.store-old-20261017` 保留 7 天）；核验记录在训练机，本机 checkout 无 `store/` 现场，本次未 SSH。同时按代码核查补记 Prompt 双份（Git `records/prompts/` vs store `store/records/prompts/`）与一致性门现状：store 内部有 fail-closed 门，Git 版与 store 版无自动检测，该缺口已登记为 `ARTIFACT-RETENTION` 内对应条目的下一动作、未实施。仅修改本文件与 `docs/project-status.md`，未改代码/`.gitignore`/`docs/results/**`/README，未运行模型或测试；遗留项见仓库外 `~/pi-workspace/mVllm_2-audit/prompt-consistency-audit-20261017.md`。

- **2026-10-17（Pi，Prompt 进 Git 方案 A 落地）**：按用户裁决把活 store 目标从 `workspace/store` 改为项目根 `store`；`.gitignore` 以逐级白名单 `/store/*` → `!/store/records` → `/store/records/*` → `!/store/records/prompts` 仅放行 Prompt 记录，媒体与大权重仍忽略；同步修订 `docs/project-status.md` 机器与资产位置表与本文件 `ARTIFACT-RETENTION` 内 store 路径与红线表述，旧 `workspace/store` 口径作废。挪位本身由并行任务在训练机执行，本机无现场证据，仍标注为已授权／结果待核。

- **2026-10-17（Pi，store 迁移与备份目录口径入账）**：按用户裁决把「活 store 迁入训练机项目目录 `workspace/store`、`/data` 只放备份、备份总目录 `/data/mVllm_2-backups/` 与 `baseline-YYYYMMDD` / `round<N>-YYYYMMDD` 子目录命名」写入 `docs/project-status.md` 的机器与资产位置表及本文件固定标识 `ARTIFACT-RETENTION`；同步登记 `versioning` 各子命令 `--root` 口径、`migration` 例外、`--backup-root` 平铺写入与 `git clean -x` 红线，并登记「Prompt 记录位置与进 Git 口径冲突」待用户裁决。迁移执行结果未在本机核实，文中一律标注为已授权／结果待核。仅修改本文件与 `docs/project-status.md`，未 SSH、未运行模型或测试、未执行 git commit/push；独立 reviewer 复核与遗留项见仓库外 `~/pi-workspace/mVllm_2-audit/store-migration-docs-20261017.md`。

- **2026-10-17（用户裁决／Pi，执行口径入账）**：把用户 2026-10-17 的一整批裁决写入台账：既定 21 个 test source 重建 test release 及三条边界、`v4.1-agent-pipeline-fold0-r1` 冻结为参考基线 r0、复用 `data-v4.1-r2` 不重做 ROI 审查、产物保存与身份四元、阶段硬门、`/data` 第一级备份根与归档节奏、家目录去重、过期文件管理与清理红线。新增 2 个固定标识 `TEST-SOURCE-REUSE`、`ARTIFACT-RETENTION`，原 37 个标识不变，无任务被关闭或升级；落点为：新增总节「2026-10-17 用户裁决：执行口径与全局纪律」、两个新条目、FINAL-TRAIN / MODEL-QUALITY / TEST-POLICY 各一行、HOLDOUT-BUILD 的解除条件、下一动作、发布入口与差距及与 `TEST-SOURCE-REUSE` 相关的事实与差距/数据来源/依赖边界/验收标准（状态仍为阻塞，未改状态词）、RECOVERY-VALIDATION 解除条件、顺序表 2 行改写 + 2 行新增；HOLDOUT-BUILD 保持阻塞（未改状态词），TEST-POLICY 保持已关闭、原结论不改。仅修改本文件，未 SSH、未构建、未运行模型或 test、未删除或移动任何产物。独立 reviewer 已对照 diff 复核并在提交前给出裁决，报告留档于仓库外 `~/pi-workspace/mVllm_2-audit/`；本次提交在复核后进行并由 git log 追溯。

- **2026-10-12（Codex，正式文档整合）**：新增 DOC-INTEGRATION，承接用户的根 README 替换和覆盖旧说明清理授权；保留原 30 个任务标识、设计决策和原始验证证据，最终独立核查通过、无可执行问题，DOC-INTEGRATION已解决。Mac uv、训练机 Conda Python 与 3.11.x 约定保持；本轮无 SSH、实际数据处理、训练、推理或评测，现场刷新仍为下一步。

- **2026-10-12（Codex，README续办）**：根README改为面向首次访问者的项目介绍与快速开始，静态独立核查通过，见验证第69节。无安装、SSH、训练或评测；训练机刷新仍后置。

- **2026-10-12（Codex，本机文档整理）**：移除迁移前的合并/补接线下一动作，将已解决工程条目统一放入关闭区；MODEL-DIAG 未实现 canary/交叉 Prompt 对照退出当前步骤，单折新基线仍待确认。恢复与正式环境激活保留独立未完成条目；DOC-CONSOLIDATION 经独立核查通过，首轮模板路径问题修复并复核，证据见验证第68节。未 SSH、训练、评测或清理产物。
- **2026-09-14（历史交付）**：工程交付与模型质量分开，部署和逐折能力验收后，按用户授权先推任务分支再快进 main 并同步训练机，见验证第63–67节。正式解释器未激活、真实训练/test/服务成功路径及物理恢复未验收。
- **2026-09-13（必要决定与调查）**：test 七阶段和七门接通不改变 TEST-POLICY；21 个既定 test source 已找到，但使用资格均证据不足，其中20个存在与暴露 release 关联的媒体凭据，见验证第49–53节。缺失三折权重的已知位置调查收束，不持续搜索、不以其他单折模型替代，见第54–55节。条件清理授权持续有效，89 个 train 视频仅验签，删除为0，见第56–58节。工程范围取消真实训练默认前置、正式输入预检与环境调查见第59–62节。

更早的施工、失败、修复与测试日志见[迁移验证记录](results/version-control-migration/verification.md)，原维护顺序可查 `git log -- docs/project-todo.md`。历史结果均按原机器、代码版本和覆盖范围读取，本轮不宣称复跑。

- **2026-10-13（Codex，只读刷新）**：REMOTE-STATE-REFRESH 完成限定现场查询；两端起始版本、环境来源、数据引用与模型资产已落报告。未执行业务写入、同步或真实模型运行；普通git status潜在索引刷新偏差明确留证。ENV-ACTIVATION 和模型/test/恢复缺口保持。

- **2026-10-13（Codex，训练机Conda部署）**：按用户授权新建mvllm2，Python3.11.17、GPU锁241项一致、doctor/依赖检查通过，ENV-ACTIVATION已解决。旧环境保护摘要和代码状态保持；无业务运行或代码同步，新体系记录按流程生成。

- **2026-10-15（Codex，测评方案入库）**：EVAL-PROTOCOL 文档范围已解决；新增开发/最终语义质量与五分钟交互性能设计、现状差距及 A–E 实施计划，更新现行入口和唯一台账，保留31个原任务并新增6个固定标识。独立源码核查通过；单折登记与受控性能加载两项前置已补齐，不擅定接口。179链接/锚点、37唯一标识及Markdown范围检查通过；未改代码、SSH、训练、推理、评测、读受限测试语义或push/merge，未关闭真实模型任务。

- **2026-10-15（Codex，前置设计与多Agent续补）**：EVAL-PROTOCOL文档增量已解决；补齐base/trained来源、完成折快照诊断、受限多Agent判读/预测exposed、独立performance加载与用途分离。默认2个独立Agent、分歧第三先独立后仲裁，可预先扩员；已确认选项不再重复待决。6份Markdown经独立源码核查通过，139链接/锚点、37原ID及视觉门槛表检查通过。具体统计/供应方版本/数据发送/运行规格仍须冻结，无代码、模型调用、账户部署、远程或真实测试动作。

- **2026-10-15（Codex，执行配置收口）**：用户确认沿当前基座现场核验、本机Ollama双模型及第三独立上下文、匿名回答限定、统计口径、视频规格、超时与资源预算；同步设计/计划/状态及TODO，不再将这些配置列为待讨论。功能条目仍待处理；仅修改文档，未运行模型、训练或评测。4份Markdown的115个本地文件链接有效，原质量门槛表及固定任务标识不变，`git diff --check`通过；独立reviewer核查通过（仅文档；历史Ollama摘要未独立复盘，执行前复核）。提交版本可用`git log -- docs/model-evaluation.md`追溯。

- **2026-10-15（Codex，A/B 实施启动）**：用户授权按现有 TODO/设计实施测评基础能力与开发验证接线。起始本机 `512cc8b4`，工作区干净；本轮代码使用短期分支 `feat/evaluation-development`；已分派纯语义评分、模型来源/完成折登记和开发评测接线，尚未验收。仅本机代码及合成测试，不运行真实模型、SSH 或受限 test；逐步补记验证及独立审查证据。

- **2026-10-15（Codex，A/B 工程接线完成）**：新增语义/基线/来源及开发接线关键集102 passed，独立reviewer完成14项最终接线专项并核查流程文档，无剩余可执行问题。EVAL-SEMANTICS按纯基础能力关闭；EVAL-DEVELOPMENT工程完成但保留进行中，待现场及真实运行证据。C/D/E和真实模型父任务不关闭。最终受影响eval回归315 passed/1 skipped、退出码0；并行广回归的两项早期失败和退出清理限制亦如实入证据。整体验证见实施记录；无SSH/真实模型/test使用/push/merge。

- **2026-10-15（Codex，C/D/E实施启动）**：用户继续授权独立评分、受控性能和准入绑定工程接线及合成验证。起始 `30e96f97`、工作区干净，沿用短期实施分支；已分派C/D/E边界并统一公共CLI/导出责任。禁止真实模型评测或使用真实test；不SSH、不部署账户/真实服务、不运行Ollama，不push/merge。实际验证与剩余缺口实时补记。

- **2026-10-15（用户裁决，旧准入入口迁移边界）**：用户选择“新准入统一要求新质量＋性能证据；保留既有批准/alias的读取与幂等恢复”。授权据此停用旧strict的新finalize/alias/approve晋级，不撤销既有批准或修改历史记录；幂等仅同身份/同冻结绑定，不得借恢复重绑。该选择适用于本轮C/D/E工程，真实模型/test仍禁止。

- **2026-10-15（Codex，C/D/E工程接线完成）**：新独立质量、受控性能/可信显示接收、统一准入和私有异根恢复已接线。C先143 passed，120秒统一总deadline增量后41 passed；D最终61 passed；准入/恢复/服务/开发联合77 passed，旧源兼容/CLI6 passed。独立reviewer分别35/61/69 passed并核8文档完整链路，通过且无剩余可执行问题。相邻eval首轮368 passed/7 failed/1 skipped，7旧strict新晋级fixture按用户决策迁移后test_eval_run全文件47 passed/1 skipped；其他旧Registry/materialize/manifest/model_registry/CLI分轮419个不同用例已有通过证据。163链接/锚点、37唯一任务ID、compileall及diff-check通过。详见[接线记录](results/evaluation-independent-performance-admission-20261015.md)。执行本机Mac，提交由git log追溯；没有SSH/真实模型/Ollama/真实test/外部客户端部署/push/merge。C/D/E保持进行中：工程完成待真实证据，不关闭MODEL-QUALITY等父任务。

- **2026-10-15（Codex，真实运行前核验启动）**：用户继续授权环境/资产核验及独立准备，保持真实模型评测与test禁令。已派发本机Ollama与HF资产、tokenizer受审映射/依赖、客户端显示测点三类只读核验；主线程维护准备产物和唯一TODO。起始 `6a92ca3b`、Mac、干净工作区；不执行pull/模型加载/真实推理/跨库写入。

- **2026-10-15（Codex，真实运行前核验与独立准备完成）**：Mac本机Ollama两个冻结标签及manifest匹配，全部7个唯一引用blob在6.442秒流式SHA256复验匹配且stat稳定，无模型驻留或推理。明确缺匹配HF tokenizer、真实独立受审映射/basis/golden及项目Python3.11评审依赖；候选TensileAgent分支未实现所需upload→render单调时钟/原ID/nonce/签名链。已新增完全离线盘点工具、无证据效力的来源/审计草稿、机器可读库存和客户端既有契约交接清单；最终38项合成测试通过，静态audit结构/权限漏报已修。真实部署/运行仍缺证，不创建eval/claim，不读真实test，不下载/安装/跨库写入或push/merge。详见运行前核验（该记录已随 2026-10-18 清理移除），同次提交由git log追溯；独立reviewer38项复跑与7blob完整字节复验通过，无剩余可执行问题，限本轮核验/离线准备；174链接/锚点、37唯一ID、compileall/diff-check通过。

- **2026-10-15（Codex，tokenizer来源与评审环境补齐启动）**：用户继续授权HF固定来源/revision、独立Python3.11环境及受审材料准备，真实模型评测/test禁令持续。起始 `696ea17c`、Mac、工作区干净；分派上游来源、隔离依赖与GGUF tokenizer-only可行性核验，不更换模型、不改外部客户端或既有环境。

- **2026-10-15（Codex，固定HF来源/隔离环境/映射材料完成）**：两个官方HF来源固定完整revision，10文件全SHA/API对象匹配、各自Jinja独立；独立Python3.11.14环境29包、hash锁与官方wheel/5010安装文件验证通过。固定官方llama.cpp源码tree和CPU vocab-only counter完成16公开合成case：14完整IDs匹配，两个NFD Unicode反证已确认为HF原资产NFC与GGUF计数行为差异，不出具等价映射。provider窄加Jinja保护，76项相关回归通过；真实评审依然阻塞，HF来源/环境在场不授准入。过程见[固定来源与材料](results/evaluation-tokenizer-materials-20261015.md)，同次提交git log可追溯；独立准备审查通过，映射因实测不等继续阻塞；188链接/37唯一ID及compileall/diff-check通过。不真实模型评测/生成、不读真实test、不加载推理权重、不创建eval/claim、不改既有环境/训练机/客户端、不push/merge。

- **2026-10-15（Codex，本机实际分词核验启动）**：用户授权Ollama实际tokenizer身份/NFCNFD及原文不变对齐方案核定；起始 `52d6afbd`、Mac、工作区干净。已分派本机工件、官方来源与固定Ollama对应参考counter核验；不将前轮较新上游counter冒称installed行为，不真实模型评测/生成/test，不改provider/协议，重大方案等待用户确认。

- **2026-10-15（Codex，本机包内x86分词核验完成）**：签名/架构核验与实际installed x86三库词表专用24case完成，NFC/NFD与8K预算低估反证保留；nativearm64 server未测。新增离线auditor、完整helper/工件/输入输出证据与28项保护（tester及reviewer分别全过）；不tensor加载/context/GPU/生成、不真实test。已提出A/B原文不变方案并向用户确认，生产counter/冻结协议未改，真实评审仍拒绝。详情[本轮核验](results/ollama-tokenizer-verification-20261015.md)、[方案草案](plans/2026-10-15-review-tokenizer-alignment-design.md)，同次提交由git log追溯；独立准备审查通过、28测试和24词表case分别独立复跑；201链接/37唯一ID及compileall/diff-check通过；方案待用户确认，未push/merge。

- **2026-10-16（用户授权／Codex，兼容修复启动）**：用户要求按原方案处理兼容、继续运行前准备，不再扩展新方案讨论，真实模型评测/test仍禁。起始 `4d397f1a` 干净工作区；撤回前轮A/B待确认前置并分派本地provider最小修复，保留原文/模板/模型/样本和既有门。独立可执行准备继续，后续证据实时补记。

- **2026-10-16（Codex，兼容修复与运行前材料完成）**：按原方案修复本地计数适配，原文/HF文件/模板及既有门不变；前轮A/B讨论撤回。实现者原24＋新增566公开case完整IDs匹配，独立reviewer另582组全部匹配。tester新增29 passed、实现者既有38 passed；独立兼容/semantic共64 passed，inventory最终63 passed且独立63复跑通过；发现畸形v2可绕过GGUF禁读边界已修复。两个模型各9条golden的具名v2映射和最终来源输入已封存，实际离线build/verify及独立复验通过；独立Py3.11 inventory结构/依赖/静态绑定匹配、仍ready_for_real_review=false。独立审查通过，现行文档收敛；214链接/锚点、37唯一ID、compileall/diff-check通过。证据见修复与准备记录（该记录已随 2026-10-18 清理移除），本次Mac提交可由git log追溯。真实评审、GPU/E2E、隔离部署和客户端显示测点仍缺，C/D/E及父任务不关闭；无真实模型生成/评测、真实test、完整server、eval/claim、SSH或外部客户端写入，无push/merge。

- **2026-10-16（Codex，隔离与显示测点准备启动）**：起始 `ae4ccd15` 干净工作区，按用户授权并行只读定位评审隔离和客户端测点剩余接线；先完成无模型准备，不运行真实模型评测/生成、不使用真实test。后续实现、合成验证和实际边界实时补记。

- **2026-10-16（Codex，隔离与显示测点无模型接线完成）**：新增显式sandbox预检CLI、三actor公开合成请求构建及薄客户端receipt桥接；本机8项canary全通过、三actor各2请求、无broker。新隔离29＋既有semantic/semantics联合92项通过，独立92项复跑无warning；新client47＋既有performance61共108 passed，独立108 passed（2.75秒）且无warning；真实ASGI receiver合成闭环仍synthetic/无DOM证明。候选外仓6源码文件及Git身份只读盘点，未读tmp或修改外仓。独立审查通过、无剩余可执行问题；223链接/37唯一ID、compileall/diff-check通过。入口/输出/边界见本轮记录（该记录已随 2026-10-18 清理移除），同次Mac提交git log追溯。真实部署、独立账户、DOM测点/真实密钥及GPU/E2E仍缺，C/D/E及MODEL-QUALITY不关闭；无真实模型/真实test/正式evalclaim/SSH/外仓写入/push/merge。

- **2026-10-16（Codex，可执行TODO推进启动）**：起始 `a0f1e1ab`，工作区干净；用户要求完成所有当前可做事项。已分派剩余输入/归档/恢复、契约/指针范围定位及训练机限定只读核验。真实模型/真实test禁令持续，不以广义推进替代真实运行授权，不执行条件尚未满足的删除。

- **2026-10-16（Codex，可执行准备与契约澄清完成）**：本机实际评审元数据/完整固定资产/18golden/canary及源码前后绑定通过；用户开启训练机后，限定只读Git/基座/归档/容量核验完成。有效hash结果覆盖23个基座文件+旧Fold0 adapter共24文件17,868,457,279字节；另一次同hash会话输出/状态未回收、可能短暂重叠，总IO与单调用性不作保证。四基座分片完整SHA与官方main LFS观察匹配，完整固定revision配置/代码仍未核，不补造来源/正式模型。minimal归档原始记录副本缺失而原run只stat在场，不删文件；真实恢复缺准确备份root。CONTRACT-NAMING仅两module docstring与说明，AST去doc后完全相同并通过独立核查，按澄清目标已解决；旧指针仍有legacy消费者，待确认不恢复写入。独立审查通过，无剩余可执行问题；283链接/37唯一ID、JSON/AST/compileall/diff-check通过；未为纯说明变更跑业务测试。见本轮记录（该记录已随 2026-10-18 清理移除），本次Mac提交git log追溯；远程保持main@3f200461，未同步，本机起始a0f1e1ab多17提交。真实模型/真实test/训练/正式evalclaim/pushmerge均未执行，真实隔离/DOM/备份和模型质量仍未关闭。

- **2026-10-16（Codex，基座固定来源补齐启动）**：起始defa954b干净，按用户授权固定revision下配置/tokenizer/processor/代码来源核验；并行官方来源取证、训练机19小文件静态采集和登记预检边界定位，不重复读取大权重或执行模型/真实test。

- **2026-10-16（Codex，固定revision来源核验完成）**：复用现有Requests默认TLS，官方HF daef484c...完整23对象Gitblob及tokenizer正文/LFS核验通过；真实19小文件与先前SHA一致，4权重只stat不重复读取。HF20同/2diff/1extra，官方MS历史2626e837...树解释README/额外configuration并与23缓存revision对应，22/23身份相同，唯模型构造新增self.post_init()仍不同。安全解析.msc/.mv，5 auto_map入口传递闭合到7仓内文件，外部依赖/实际执行不冒称已核。未覆盖基座或签发原样provenance/正式记录；来源helper实际拒绝unknown，独立guarded复跑通过。3份来源报告+1份拒绝观测、官方bytes/闭包/diff/跨报告SHA和文档经独立审查通过，无剩余可执行问题；293链接/37唯一ID、JSON/摘要/diff-check通过。详见[固定来源记录](results/minicpm-fixed-source-audit-20261016.md)，本次Mac提交git log追溯。代码偏差合并回MODEL-DIAG/EVAL-DEVELOPMENT既有来源前置，不新增重复任务、不擅自回退/改写或重开原方案；真实模型/训练/test/正式model evalclaim/pushmerge均未执行。

- **2026-10-16（Codex，post_init来源与用途核验启动）**：起始3c643f25干净；用户继续授权只读来源追踪和无模型准备，明确不改基座。已分派项目历史、实际框架源码及官方目的分析，不改动任何模型资产或来源声明。

- **2026-10-16（用户取消／Codex，post_init核验收口）**：用户明确不再追查添加记录并要求删除待办；已从当前下一动作移除该子事项，保留简短取消记录，37个既有父任务标识不变。实际框架源码及用途核验结果留档，未找到本机修改者/动机的直接记录，不再为此发起搜索或方案讨论。保留原基座，不补造来源声明，不升级真实验收。独立reviewer核查通过，无可执行问题；JSON/跨报告与源码摘要、300链接/37唯一ID、diff-check通过，未运行测试。见[收口记录](results/minicpm-postinit-origin-purpose-20261016.md)；本次Mac提交由git log追溯。

- **2026-10-16（Codex，开发输入与预算准备）**：起始57670abc，限定SSH核r2开发六文件及候选metadata/Prompt；远端main@3f200461前后干净，不同步。1,678候选、85来源，validation425/664/492共1,581，97仅出现于train，无候选/source层级泄漏；不宣称试件独立。保存无标签来源关系、成功采集脚本及已知失败记录；成功调用13,365,233字节/0.161秒，不把它冒充整个阶段累计IO。Prompt/契约差异按正式重渲染行为解释，旧训练Prompt未知。现行开发/交付切片、抽帧边界和请求重试差异入既有前置；不擅改路径/选变体。样本及调用条件算术量已备，质量GPU小时未虚填，真实性能/质量未通过。JSON/22来源摘要/映射与跨报告绑定、310链接/37唯一ID、diff-check通过；独立reviewer及最终历史配置增量复核通过，无剩余可执行问题，未重新SSH复核或运行测试。详细验收及提交由[训练数据台账](results/training-data-ledger-20261017.md)（原开发输入核验材料已于 2026-10-18 并入）与git log追溯；真实模型/test/训练/基座改写/来源追查/pushmerge未执行。

- **2026-10-16（用户确认／Codex，开发试件分组材料补齐）**：用户确认“每一个式样只对应一个视频，不会出现重复的”。据此沿已核candidate→source关系，将同视频全部窗口归一组，生成显式分组材料（现为[训练数据台账](results/training-data-ledger-20261017.md) 的 `source_groups` 与 `source_map.mapping`）：1,678候选、85组，validation三折29/29/22组共80，折内及验证折间组交集为0。来源依据保留用户原话与观察材料SHA，非独立物理身份验真；未宣称所有实验批次相关性不存在。移除等待试件映射的下一动作，原观察快照不追改；正式eval输入/真实模型/test未创建或执行，其他准备缺口保留。本次Mac提交git log追溯。
