# 当前项目状态与开发原则

## 工程交付与证据时间

可读版本控制工程迁移已按确认范围完成并于 2026-09-14 合并 Codeup main，训练机正式代码已同步；最终集成回执见[验证记录第67节](results/version-control-migration/verification.md)。当前任务、依赖及下一动作统一在[项目 TODO](project-todo.md)，本文件只汇总项目状态和开发原则。

本页 2026-10-12 整理依据仓库代码与已有记录，未刷新训练机。模型资产现场基线仍是[2026-09-14模型背景](MODEL_GATE_BASELINE.md)，文件存在、历史可运行与今天可加载是不同证据。

## 当前支持的链路

| 范围 | 工程状态 | 证据限制 |
| --- | --- | --- |
| 数据处理 | versioning 显式七阶段及完整审查包接管，旧公共写入 CLI 已停用 | 真实媒体与迁移验签范围见验证第24节；已迁移 release 仍依赖外部媒体 |
| 数据与 Prompt | 完整 data/prompt 身份、封存及输入冻结 | 数据对应关系见[发布说明](V4_1_DATA_RELEASES.md)；不隐式选择版本 |
| 训练与评测 | 逐折、独立 full、validation 与 holdout 执行/授权评分已接线 | 合成执行和 CPU 回归不代表真实 GPU 训练或质量通过 |
| 模型与服务 | MLflow 登记、正式评测绑定、alias、冻结 Prompt 及服务模式准入 | 尚无已证实满足新体系最终门禁的真实模型；真实加载/服务成功未验收 |
| 备份恢复 | store 级恢复与异根地址重定位有工程证据 | 大型权重、SQLite、外部媒体/基座与真实硬盘组合恢复未完整验收 |

正式入口、产物与保留业务函数边界见[入口清单](results/version-control-migration/entrypoint-map.md)。旧包仍提供共享算法，CLI 退役不代表整包无依赖。

## 模型与测试的实际起点

旧 Fold0 发布 `v4.1-agent-pipeline-fold0-r1` 曾完成旧工程服务与 Agent 调用验证，质量门未通过、production 未批准。旧 current 与 Git legacy Registry 只解释历史身份，不授予新 alias 或正式 passed。

concise 三折报告记载 1581 条 validation 中合法率 79.63%、joint correct 32.07%，并有类别坍缩；原始预测和约定三折权重的缺口仍保留。详细历史结果及来源见[模型背景](MODEL_GATE_BASELINE.md)，不把报告摘要当作本轮复算或可执行模型。

既定 21 个 test source 已定位，但旧测试发布曾暴露，独立使用资格仍待核定。最终独立测试必须走来源隔离、全量人工审查、封存、预注册和一次性 claim；不得利用已暴露测试调参。

## 开发原则

1. 输入先冻结：完整 data/prompt/train/model/eval 身份、契约、基座来源与内容、fold、seed、生成和训练参数均可追溯。
2. 开发侧三折用于方案选择；full 是独立最终训练范围。开发阈值须预先确认，不能自动套用最终 test 七门或事后回填。
3. 工程集成、训练完成、模型质量与服务成功分别验收。旧效果不补写为新体系 passed。
4. 历史 checkpoint、adapter、merged、预测和日志按诊断依赖与条件清理台账保护，不因已有 merged 自动删除。
5. 当前链路通过显式 store 和在线引用门操作；模型服务经合法 alias、精确 Registry 版本与冻结 Prompt 校验。
6. 重大方案需确认，真实训练、推理、受限测试及删除遵守各自授权。本轮整理不启动这些操作。

## 下一步入口

下一轮先按 TODO 刷新训练机只读现状；MODEL-DIAG 新基线方案、test 使用资格、环境绑定和真实恢复缺口继续分项处理。没有可用的旧权重时，不持续全盘搜寻，也不直接照旧建议构建尚未支持的 canary/交叉 Prompt 接口。

- [项目 TODO](project-todo.md)：唯一任务状态和执行顺序。
- [项目指南](project-guide.md)：双机角色与链路关系。
- [数据处理手册](DATA_PROCESSING_RUNBOOK.md)：输入准备到封存发布。
- [训练与评测](../finetune/README.md)：正式运行入口及历史实验索引。
- [服务手册](INFERENCE_SERVICE_RUNBOOK.md)：现行 alias 准入与运维。
- [模型背景](MODEL_GATE_BASELINE.md)：带核查日期的真实资产和历史效果来源。
