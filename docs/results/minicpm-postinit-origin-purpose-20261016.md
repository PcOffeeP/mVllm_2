# MiniCPM 构造收尾调用核验与取消追查记录

日期：2026-10-16。执行者：Codex。Mac 起始提交 `3c643f25`。

用户最新决定：不记得添加记录，不再追查，并删除该项待办。已从 EVAL-DEVELOPMENT / MODEL-DIAG 当前下一动作移除历史来源、修改者及动机追查；父任务仍保留其他输入准备和真实验收目标。本文及既有结果仅保留事实记录，不构成继续追查要求。

## 已完成的无模型核验

训练机正式环境为 Transformers 4.56.1。通过既有 SSH 密钥只读采集包元数据及五份已安装源码，未导入 torch、Transformers 或模型代码；对应 `modeling_utils.py`、Qwen3 modeling 文件与官方 v4.56.1 标签字节一致。训练机另一次只读核验确认 `main@3f200461026a59676aaac7ea864f8fadb599688d` 干净，基座代码仍为18,609字节，SHA256 `f385948d8321fc9e30b178f7bb39020c845c7b367eeb0b762a50746368b25d10`。采集命令、失败后纠正解释器的记录、文件摘要及真实平台分离记录见[实际环境来源报告](minicpm-postinit-runtime-source-20261016.json)。本机未复跑训练机采集。

`MiniCPMV` 继承的 `post_init()` 是框架构造收尾钩子，涉及权重初始化入口、旧梯度检查点配置处理、fp32模块名单校验及并行计划整理。在4.56.1原生 `from_pretrained()` 的构造上下文中，`no_init_weights()` 抑制该入口的随机权重初始化及由 `init_weights()` 触发的绑定；其他收尾逻辑仍执行，加载流程后续另有权重绑定。这是静态调用关系，不能据此宣称模型加载成功或实际行为等价。见[官方实现](https://github.com/huggingface/transformers/blob/v4.56.1/src/transformers/modeling_utils.py#L2224-L2271)及[构造上下文](https://github.com/huggingface/transformers/blob/v4.56.1/src/transformers/modeling_utils.py#L5099-L5106)。

OpenBMB 官方 **int4** 仓库有同位置添加调用的[公开PR #3](https://huggingface.co/openbmb/MiniCPM-V-4_5-int4/discussions/3)，用途是兼容加载修复。构造函数AST相同而整文件不同；其中提到的 `all_tied_weights_keys` 不存在于本次实际4.56.1源码。该记录只能解释一种公开用途，不能证明本机补丁来源、修改者、历史动机或在当前环境中的必要性。详见[用途分析与官方来源摘要](minicpm-postinit-purpose-analysis-20261016.json)，该报告绑定上述实际环境报告的最终SHA256。

项目现存Git与已归档材料未找到添加动作的直接记录；此调查已随用户决定终止，不扩展到个人shell历史或其他会话。

## 保留边界及下一步

原基座及新增调用均保持原样。取消历史追查不等于确认目录为未修改官方快照，不签发原样来源声明，不创建正式model/eval/claim。真实运行影响、实际加载与质量效果均未验证。其余开发data/Prompt、同源映射、交付参数及预算准备沿[项目TODO](../project-todo.md)继续，不再以寻找该调用作者或动机作为下一动作。

本轮无模型加载、生成、训练、真实评测、test使用、系统安装、远程同步、push或merge；不重复读取大权重。仅保存已完成的静态证据与取消决定。JSON解析、跨报告SHA256、八份静态输入源码摘要、300个本地Markdown链接、37个唯一任务标识及 `git diff --check` 均通过。独立 reviewer 对指定五份增量及直接引用缓存核查通过，无可执行问题；其核对了调用链、官方PR差异、5份实际环境源码及7份官方小文本摘要，未重新SSH或重新联网，远端观测仍以采集记录为限。本次Mac原子提交可由 `git log -- docs/results/minicpm-postinit-origin-purpose-20261016.md` 追溯。
