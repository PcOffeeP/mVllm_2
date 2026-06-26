# Agent Streamlit 工作台 UI 重构实施方案

> 状态：已批准
> 版本：1
> 项目计划：docs/PROJECT_PLAN.md
> 项目计划版本：8.1

## 步骤目标与范围

本步骤完成项目计划第 5 步中“网页交互”的 UI 重构：在继续复用 `agent/runner.py` 作为唯一执行内核的前提下，把现有 `ui/agent_app.py` 从基础 Streamlit 表单工作台，改造成参考 `/Users/pcoffeep/Downloads/Kimi_Agent_Deployment_v4` 的深色工程化控制台界面。

参考界面的可借鉴部分包括左侧导航与近期任务、主工作区上传和分析队列、右侧实时分析状态与终端式日志、结果摘要、历史记录筛选、模型配置摘要和紧凑的深色视觉系统。实现时只吸收交互结构和视觉语言，不直接复制压缩后的构建产物，也不引入 React 前端作为本步骤的强制路线。

本步骤包含单视频与批量视频入口、任务队列展示、运行事件流展示、公共结果展示和结果导出体验优化。本步骤不修改 `IterativeAgent` 决策规则、Native Function Calling 契约、模型 HTTP 服务、训练 pipeline 或最终评估逻辑；不建设多人在线服务、后端任务数据库、在线标注、真值读取或工业部署能力。

## 实施方案

采用“Streamlit 原地重构”的路线：保留当前启动方式 `python3 -m streamlit run ui/agent_app.py`，继续调用 `runner.run_one` 与 `runner.run_batch`，通过 Streamlit session state 管理本地任务、当前视图、事件、结果和导出状态。这样可以满足项目计划中“CLI 与 Streamlit 复用共享 Runner”的约束，同时用最小技术栈变化取得接近参考界面的操作体验。

UI 采用三栏工作台结构：左侧为产品标识、视图切换和近期任务；中间为当前视图内容，默认显示视频上传、路径输入、Mock/配置/工作目录控制和待分析队列；右侧为选中任务的实时状态、Agent 事件日志和最终公共结果。历史视图提供任务搜索、状态筛选和结果回看；配置视图只展示当前运行配置与服务状态提示，不直接持久化密钥或覆盖 `agent/config.yaml`。

事件与结果映射以现有 runner 回调为准。`video_started`、`round_started`、`llm_tool_call`、`sample_and_infer_finished`、`state_updated`、`video_finished` 和 `video_failed` 映射为可读日志、轮次摘要、状态徽标和进度阶段；最终结果只展示公共结论字段，内部诊断可以通过折叠 JSON 查看但不能被当作最终结论。普通分析界面不得读取标注或真值。

视觉系统用 Streamlit 内嵌 CSS 实现，保持低圆角、深色面板、细边框、小字号、状态色徽标、终端式日志和紧凑信息密度。图标优先使用 Streamlit 可用的轻量文本符号或内置组件，不为视觉效果引入重型前端构建链。上传控件、按钮、进度条、状态徽标、任务列表和日志面板需要在桌面宽屏下形成稳定布局，在较窄窗口下退化为上下堆叠或可滚动面板。

## 执行清单

- [ ] 梳理当前 `ui/agent_app.py` 的状态数据结构，建立统一的本地任务模型，覆盖 `pending`、`running`、`completed`、`failed` 和批量子任务状态。
- [ ] 重构 Streamlit 页面骨架，形成左侧导航、中间主工作区和右侧详情区，并保留单视频、批量视频、Mock 模式、配置路径和工作目录输入。
- [ ] 实现参考式上传与队列体验：支持视频文件上传、路径输入、目录批量输入、待分析队列展示、任务选中、任务移除和运行按钮禁用状态。
- [ ] 将 runner 事件回调映射为实时分析面板，展示当前视频、轮次、候选区间、工具调用、模型输出摘要、状态更新、失败阶段和终端式日志流。
- [ ] 重构结果面板，按 `fracture`、`no_fracture`、`unrecognized` 和运行失败分别展示状态徽标、时间区间、断裂模式、位置、置信度、轮数、错误信息和折叠 JSON。
- [ ] 增加历史记录视图，支持按文件名搜索、按状态筛选、选择历史任务回看结果与事件，并复用已有 JSONL、CSV 和 JSON 导出能力。
- [ ] 增加配置摘要视图，展示模型/服务配置来源、Mock 状态、工作目录、推理端点提示和当前运行限制，但不在 UI 中保存密钥。
- [ ] 提取小型渲染辅助函数和样式常量，避免把复杂 HTML/CSS 与 runner 调用逻辑混在同一大段代码中。
- [ ] 补充或调整测试，至少覆盖文件发现、结果行归一化、事件摘要、导出序列化、任务状态转换和 Streamlit 缺失时模块可导入。
- [ ] 更新 README 中 Streamlit 工作台说明，记录启动命令、Mock 模式、单视频/批量入口、导出格式和普通 UI 不读取真值的限制。

## 预期结果

执行完成后，`ui/agent_app.py` 仍可用原命令启动，但首屏呈现接近参考包的控制台式 Agent 工作台：用户可以上传或选择视频、查看分析队列、启动单视频或批量分析、在右侧实时观察 Agent 轮次和日志，并在同一界面查看公共结果与导出文件。

UI 与 CLI 继续共享 `agent/runner.py`；运行结果仍遵循 `{ok, result, error}` 信封与三种 Agent 最终状态；Mock 模式可在无模型服务时演示完整 UI 流程。普通分析界面不会读取标注文件或冻结测试真值。

## 验收标准

- 从仓库根目录运行 `python3 -m streamlit run ui/agent_app.py` 可以打开工作台，页面包含导航、上传/队列、实时日志、结果、历史和配置摘要视图。
- 单视频 Mock 运行可以从上传文件或本地路径启动，任务状态从待分析进入运行并最终展示公共结果或失败错误。
- 批量 Mock 运行可以处理目录中的多个视频，批量进度、每个视频事件和汇总结果可在历史或结果区回看。
- `video_finished` 的公共结果在 UI 中不混入内部帧区间、临时路径、Base64、API key 或 token；运行失败展示 `stage`、`code` 和 `message`。
- 导出的 JSONL、CSV 和 JSON 与现有 runner 结果字段兼容，CSV 行仍包含 video_id、状态、断裂类型、位置、置信度、轮数和错误信息。
- 窄窗口下主要内容不发生文字重叠；任务列表、日志和 JSON 区域可滚动，按钮文字不溢出。
- 运行 `python3 -m pytest tests/test_runner.py tests/test_run_cli.py tests/test_parser.py tests/test_inference.py -q` 通过；若只修改 UI 辅助函数，还需运行新增或调整的 UI 相关单测。
- 运行 `python3 -m pytest tests -q`、`python3 scripts/validate_no_oob.py` 和 `git diff --check` 时，除真实本地生成产物缺失导致的既有 skip 外不得出现新增失败。

## 风险与待确认事项

- [非阻塞] Streamlit 对精细三栏控制台布局的控制能力有限；若后续需要像参考包一样的高保真交互、复杂动画或长期任务后台轮询，应另立实施方案评估 React/Vite 前端加本地 API 的路线。
- [非阻塞] 当前 runner 调用是同步执行，Streamlit 页面刷新和长任务体验受限；本步骤先通过事件占位区和 session state 改善展示，不引入后台任务队列。
- [非阻塞] 参考包中的模型名称、阶段文案和示例数据不完全匹配当前项目；实现时必须替换为 TensileAgent、MiniCPM-V 4.5、三种最终状态和现有 runner 事件。
