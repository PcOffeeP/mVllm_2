# 测评基础能力与开发验证接线实施记录

## 范围与执行条件

2026-10-15 用户授权按现有 TODO 和设计实施测评基础能力及开发验证接线，对应实施计划 A/B、EVAL-SEMANTICS 和 EVAL-DEVELOPMENT。执行机器为当前 Mac，起始代码 `512cc8b4e549d7cac487fc2859fbf896716ad43e`，起始工作区干净，实施分支 `feat/evaluation-development`。本记录的提交通过 `git log -- docs/results/evaluation-development-implementation-20261015.md` 追溯。

本轮使用合成样本、微型文件和明确替身运行时测试工程行为，没有 SSH、训练、真实模型加载、Ollama 判读、真实数据跑分、受限 test 读取、账户部署、性能运行或 push/merge。代码通过不表示模型质量、实际权限隔离、真实恢复或显示端 E2E 通过。

## 交付与链路

| 环节 | 实现与输入 | 产物及消费者 |
| --- | --- | --- |
| 纯语义评分 | `finetune/eval_semantics.py`；固定样本、原 raw、GT、显式来源分组和预冻结判读证据 | 互斥 strict/rule/blind/unreadable、字段来源、原始严格合法率、全分母/GT 子集指标、逐折门及同组 bootstrap；供正式执行与导出重算 |
| 多数类与配对 | `finetune/eval_baselines.py`；开发训练折拟合完整标签组合众数，两个同条件完整样本集合 | 冻结多数类定义、逐字段及 joint 配对改善/退化；相对提升不作为硬门 |
| base 来源登记 | `model register --source-kind base --source-scope base`；固定来源/revision、本地一致性或现场 provenance、完整模型目录 | 同一 Registry 数值版本、独立字节快照和 `model-source.json`；无伪造 train/data/Prompt，供开发 eval |
| 成功折诊断登记 | `model register --source-kind trained --source-scope diagnostic_fold --train-version … --fold …`；FINISHED 折 receipt、真实 checkpoint step 与共享输入 | 独立不可变 adapter 快照，父 train 状态不变；只用于真实对应折开发诊断，禁止生产 alias/批准 |
| 正式开发评测 | `eval prepare/validate/run`；显式 `scorer: semantic-v4.1`、完整独立组映射、数据/Prompt/Registry 模型和规则 | `input/evaluation.yaml`、raw、逐折与 pooled 语义结果；严格历史协议继续按原定义解释 |
| 判读导入恢复 | `eval score --blind-reviews …`；预冻结 policy、原 raw 和封存 judge 答案 | 不重推理；不可变 `review_attempts/0001.json` 与 MLflow 摘要，锁定完成初判、故障最多一次 retry，最终 `blind_reviews.json` |
| 导出与报告 | `eval export`、`eval compare … --baseline-eval-version …` | 重算全部分母/来源/指标/判读与尝试链，`records/evaluations/<eval>/manifest.yaml`、`paired/<base-eval>.json`；配对还核真实基座字节一致 |
| 备份恢复 | `versioning/backup.py` 与新来源证据 | base 不要求训练 Prompt；诊断保留父共享输入和对应折凭据，异根恢复后仍验外部基座字节 |

`semantic-v4.1` 开发门按冻结方案执行：每折四状态 macro recall ≥0.65、每状态 recall ≥0.50；完整三折 pooled joint ≥0.50、机制 macro F1 ≥0.50、位置 macro F1 ≥0.60。缺折、缺必测类、未完成判读不通过。CI 为来源依赖组的 2,000 次 bootstrap、seed 3407、95% 区间，不增加 CI 或来源数量硬门。

缺失字段不补 null；失败与空输出保留。机制/位置分母只按 GT 非 null；特殊类误报使用完整相关样本。部分规则恢复后该响应不再进入 blind，剩余字段保持 missing。评审未完成时最终视觉率为 null，暂算值单列；原始严格合法率和样本支持数保留。重复 raw 复用同一封存判断只计一次成本；实际不同尝试仍分别保留，累计计算耗时不等于墙钟延迟。

## 独立复核与修复

独立 reviewer 对照实际源码和设计核查，作者没有代替独立核查。已处理的实质问题包括：

- 新协议冻结元数据残留旧六指标定义：改为显式语义指标和逐折/pooled 判定描述。
- 配对未确认同一真实预训练基座：增加实际基座文件清单一致性核验。
- 历史 strict 记录因本次源码变化失效：`versioning/eval_compatibility.py` 只允许已核实 `512cc8b4` 的旧摘要映射到准确适配代码摘要；未来代码、未知摘要及其他依赖漂移继续拒绝。测试用实际旧源模块创建冻结记录，覆盖 validation 导出/alias 与原 holdout 七门。
- 未预填 semantics 时漏传封存 blind_review：统一原文提取输入，新增回归。
- 重复 raw 重复计评审成本：按封存判断摘要去重，实际独立尝试分别计入。
- 评审故障时导入尝试未封存：每次有效导入先持久化并绑定 MLflow，已完成初判不可改、相同提交幂等、失败最多一次 retry，最终导出重验整条尝试链及采用关系，保留失败成本。

独立 reviewer 最终结论：本轮 A/B 代码及对应操作文档在本机合成范围通过，无剩余可执行问题。最终14项接线专项先13项通过，最后篡改测试修复只读 fixture 的 chmod 后1项通过，两次间生产代码相同；覆盖完整三折通过、折坍缩拒绝、来源/配对、旧协议及故障尝试链。真实环境限制见下文。

## 验证证据

实施初期 executor 执行相关既有测试：574 passed、1 skipped，284.71 秒，退出码 0；这是起始回归，不能代替最终变更验证。初期 pytest 的临时目录清理警告未造成测试失败，后续使用独立 basetemp。

实现者分项验证记录：语义 28 项、baseline 30 项、来源 30 项合成测试分别通过；来源与 CLI 合集 87 项、旧 backup 78 项通过。独立 reviewer 在故障尝试审计修复前执行关键集 101 项通过，随后要求修复该审计缺口并专项回验。上述均为来源注明的分阶段验证，不冒充主 Agent 最终复跑。

主 Agent 在生产与测试最终定稿后执行 `.venv/bin/python -m pytest -q --basetemp /tmp/mvllm-eval-ab-key-final-20261015 tests/test_eval_semantics.py tests/test_eval_baselines.py tests/test_model_sources.py tests/test_eval_development_wiring.py`：**102 passed，64.23s，退出码0**。包含语义28、baseline30、来源30、开发接线14项。变更生产模块 compileall 与 `git diff --check` 通过；最终文档检查144个本地文件链接全部存在，TODO 37个固定任务标识唯一且完整；两个准确兼容 adapter 摘要均与源码实际字节相等。相邻回归及解释器收尾结果如下。

最终冻结源码的受影响 eval 回归由 executor 执行：

```sh
.venv/bin/python -m pytest -q --basetemp /tmp/mvllm-eval-final-runtime-20261015 \
  tests/test_eval_run.py tests/test_eval_holdout.py \
  tests/versioning/test_mlflow_eval.py tests/test_model_registry.py \
  tests/versioning/test_cli_holdout.py
```

结果：**315 passed、1 skipped、0 failed，pytest 375.39s，命令 wall 486.46s，正常退出码0**。解释器最终 GC 额外耗时后自然退出。日志 `/tmp/mvllm-eval-final-runtime-20261015.log` 为本机临时追溯位置，不是长期必需产物。

另一次在并行修订期间启动的相邻广回归覆盖上述四个新增文件，以及 `test_eval_run.py`、`tests/versioning/test_registry.py`、`test_mlflow_train.py`、`test_mlflow_eval.py`、`test_model_registry.py`、`tests/versioning/test_backup.py`、`test_manifest.py`、`test_cli.py`、`test_cli_holdout.py`、`test_eval_holdout.py`，使用 `/tmp/mvllm-eval-ab-final-20261015` 独立 basetemp。摘要为 **1028 passed、1 skipped、2 failed，1024.31s**。失败是 `test_registered_base_paired_formal_cli_revalidates_both_runs`（冻结输入/上游漂移）和 `test_complete_semantic_formal_pass_and_collapsed_fold_gate[False]`（早期正例期望 passed 实得 failed）。该轮导入的测试/生产模块与后续磁盘修订不同，不把两项都推定为摘要漂移；最终定稿的102项关键集及独立14项均实际重跑覆盖两项且通过，最终315项旧 eval 回归也通过。

广回归输出完整摘要后在解释器 `Py_FinalizeEx → finalize_modules → gc_collect_main` 持续占用CPU，经本机 `sample` 确认后，主 Agent 仅终止本轮 PID20349 的退出清理（SIGTERM）；不能把它写为正常退出或整套全通过。日志 `/tmp/mvllm-eval-ab-final-20261015.log`、采样 `/tmp/mvllm-eval-broad-cleanup-sample.txt` 留本机临时目录。新增102项及最终315项命令均已正常退出码0；不因广回归中止退出清理重跑所有未受影响模块。

## 后续边界

当前来源与分组检查验证声明和字节一致性，不证明上游真实性或现实统计独立性；操作者仍需现场核定来源、试件依赖及预算。内容 seal、访问范围声明和单账号测试不证明低权限进程隔离。

新最终 holdout 协议及真实隔离、性能会话、显示端计时、生产完整准入属于 C/D/E；MODEL-DIAG、HOLDOUT-BUILD、FINAL-TRAIN 和 MODEL-QUALITY 的真实证据条件不因本轮合成验证而关闭。下一步先完成现场输入核验与适用运行授权，再按 baseline → 对应完整单折 → 完整三折取得真实开发结果。
