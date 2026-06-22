# 项目规划与实施设计 Skills 设计

## 调研结论

| 参考 | 可复用设计 | 需要改造之处 |
|---|---|---|
| [Agent Skills 规范](https://agentskills.io/specification) | `SKILL.md` 标准、渐进式加载、脚本与资源目录 | 只定义容器，不定义项目规划流程 |
| [Anthropic Skills](https://github.com/anthropics/skills) 与 [Doc Co-authoring](https://github.com/anthropics/skills/blob/main/skills/doc-coauthoring/SKILL.md) | 先访谈、分阶段收敛、读者测试、Skill 评估 | 通用文档协作流程没有项目级与步骤级边界 |
| [Superpowers Brainstorming](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md) 与 [Writing Plans](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md) | 单问题访谈、方案比较、审批门、精确验收 | 默认计划过细，且绑定固定提交与执行方式 |
| [Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md) 与 [OpenAI Agents SDK PLANS.md](https://github.com/openai/openai-agents-python/blob/main/PLANS.md) | 持久仓库规则、自包含计划、可观察验收和恢复原则 | ExecPlan 混合了设计与执行状态，不适合作为轻量步骤设计文档 |
| [GitHub Spec Kit](https://github.github.com/spec-kit/) | Spec → Plan → Tasks → Implement 分阶段产物和审批门 | 工件体系偏重，容易产生重复的全局任务文档 |
| [GSD](https://github.com/gsd-build/get-shit-done) | 项目级路线与阶段级计划分离、逐阶段讨论和验证 | 编排、状态和产物数量超出本次轻量 Skill 范围 |
| [BMAD Method](https://github.com/bmad-code-org/BMAD-METHOD) | MVP 收敛、规模自适应规划、产品与架构分层 | 角色和流程过多，Agile 假设较强 |
| [pi-mono Skills](https://pi.dev/docs/latest/skills) | 原生支持 Agent Skills 和项目级 `.agents/skills/` | 需使用公共 frontmatter 子集，避免产品专属指令 |

最终采用 Superpowers 的访谈与审批骨架、GSD 的两级文档边界、Codex ExecPlan 的验收原则，以及 Agent Skills 的跨工具目录规范。

## 能力边界

### project-architect

- 支持新项目和已有项目。
- 通过逐轮澄清确定目标、MVP、范围、非目标、技术方案和核心实施步骤。
- 只生成或修订 `docs/PROJECT_PLAN.md`。
- 不生成实施文档，不修改代码，不创建或修改 `AGENTS.md`、`PLANS.md`、`TASKS.md`。

### implementation-designer

- 只读取状态为 `已批准` 的 `docs/PROJECT_PLAN.md`。
- 为用户指定的一个或多个核心步骤逐个澄清和设计。
- 每个步骤生成独立的 `docs/IMPLEMENTATIONS/<kebab-case-topic>.md`。
- 不修改项目计划，不实施代码，不生成覆盖整个项目的总实施方案。

## 文档契约

文档只使用 `待审批`、`已批准`、`已过期` 三种状态。状态放在顶部元数据，不创建独立章节。

项目计划记录正整数版本。实施文档同时记录自身版本、项目计划路径和项目计划版本。只有满足以下条件时，实施文档才允许执行：

1. 实施文档状态为 `已批准`。
2. 项目计划状态为 `已批准`。
3. 实施文档引用的项目计划版本与当前版本一致。
4. 校验脚本返回退出码 `0`。

实质性修改必须递增版本并回到 `待审批`。Agent 无权自行批准文档。待确认事项使用 `[阻塞]` 或 `[非阻塞]` 标记；已批准文档不得包含 `[阻塞]`。

## 目录结构

```text
.agents/skills/
├── project-architect/
│   ├── SKILL.md
│   └── scripts/validate_project_plan.py
└── implementation-designer/
    ├── SKILL.md
    └── scripts/validate_implementation_doc.py

docs/
├── PROJECT_PLAN.md
└── IMPLEMENTATIONS/
    ├── authentication.md
    ├── database-schema.md
    └── payment-integration.md
```

## 推荐使用流程

1. 调用 `project-architect`，完成项目访谈和方案比较。
2. 生成状态为 `待审批` 的 `docs/PROJECT_PLAN.md`，运行结构校验。
3. 用户明确批准后将状态改为 `已批准`，校验必须返回 `0`。
4. 调用 `implementation-designer` 并指定一个或多个核心步骤。
5. 逐步骤生成独立实施文档、审批并校验。
6. 实现 Agent 只执行状态和版本校验均通过的实施文档。

## 校验脚本

两个脚本检查文档存在性、状态、版本、必需章节、占位符、阻塞项及执行资格。实施文档脚本额外检查执行清单、预期结果、验收标准和项目计划版本绑定。

退出码：

- `0`：结构完整且允许作为下游依据或执行。
- `1`：文档不完整或当前状态不允许作为依据或执行。
- `2`：参数、文件格式、编码或脚本运行错误。

## 后续扩展

可增加 `execution-governor` Skill，在执行前调用同一组校验脚本，按实施清单记录进度、发现和执行证据，并在项目计划版本变化时阻止继续执行。该 Skill 不应重新设计方案，也不应自行批准、修订或恢复已过期文档。
