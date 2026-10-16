# 可执行 TODO 推进与运行前核验

## 授权、机器与证据范围

2026-10-16用户要求继续推进TODO、把接下来能做的事项全部做好。沿用真实模型评测/生成/训练与真实test禁令；不把该请求解释为取消重大方案确认、恢复旧入口写入、允许push/merge或放宽准入。起始Mac `feat/evaluation-development@a0f1e1ab`、工作区干净。实现与报告落Mac；远端仅执行限定只读检查，无业务写入、同步/安装、模型导入、任务停止或删除。

训练机首次两次SSH超时，没有远端命令执行；[超时记录](remote-preparation-audit-20261016.json)保留。用户回复机器已打开后重新连接成功，现场为 `dell-Precision-3660`，正式项目 `/home/liuyang/文档/mVllm_2`，store `/data/mVllm_2`。本机谱系比对远端 `main@3f200461` 与本轮起始提交为0/17；远端Git前后内容干净、refs一致。不能将本机新实现写成已经同步到训练机。命令和完整实际脚本、原始结果均内嵌[连接核验报告](remote-preparation-audit-connected-20261016.json)，Git禁用可选锁，Python使用`-B`。

## 本机评审环境：实际无模型核验通过

[本机报告](evaluation-review-environment-audit-20261016.json)使用独立Python3.11.14和既有固定sources，直接核完整资产/依赖、兼容编码器、两模型各9条golden及既有canary/匿名worker。仅请求现有localhost `/api/tags`、固定两模型`/api/show`及前后`/api/ps`；批准digest和模板摘要匹配，驻留模型清单前后相同，来源与三个provider源码前后SHA匹配。修正后实际运行约21.2秒、退出0。

未启动服务、加载tensor或发generate/chat请求，也没有制造正式eval/claim、虚构binding或生成生产deployment receipt。报告保存完整执行脚本及摘要，重放支持新`--output`或`--stdout`，既有输出不覆盖；`admission_proof=false`、`ready_for_real_review=false`。独立reviewer另复查元数据、轻量绑定及实际canary；真实独立账户/上下文部署和原生完整服务仍未验证。

## 基座与开发输入：完整性已核，完整来源仍缺

训练机基座索引列出849个tensor引用、4个权重分片，全部存在，共17,391,890,184字节。[完整性记录](remote-base-integrity-20261016.json)中的成功调用流式核23个基座顶层白名单文件和一个旧Fold0 adapter，合计17,868,457,279字节；逐文件SHA与前后device/inode/size/mtime/ctime稳定。不反序列化safetensors、不执行模型代码或加载GPU。旧Fold0 merged的10片只做stat，未哈希或验证加载。

[官方来源比对](minicpm-base-upstream-comparison-20261016.json)记录researcher读取[OpenBMB官方模型说明](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/minicpm_v4dot5_en.md)、[HF模型卡](https://huggingface.co/openbmb/MiniCPM-V-4_5)与[官方API](https://huggingface.co/api/models/openbmb/MiniCPM-V-4_5)。API观察到完整commit `daef484c35ec93210ec93c5e901f8f3e9b78ee34`；实际取到的四个LFS pointer来自`raw/main`，其大小及SHA与远程四片逐一一致。固定commit文件、config/tokenizer/processor与远程代码未完整比对：默认TLS/固定URL读取受限，未关闭证书检查。故只证明权重与本轮官方main观察相同，不能把API commit与另一批main读取伪装成固定revision全文件证明。

基座目录缺`source-provenance.json`、所查HF缓存revision与来源材料；未补造来源声明，未登记真实模型/训练/eval，也未执行MODEL-DIAG。新体系模型/训练/评测记录与默认MLflow路径当前不存在，符合此前未开展正式业务的阶段，不是迁移失败。真实开发执行还需完整可信来源、显式data/Prompt/组映射和预算及适用执行授权。

完整性阶段有一项执行证据限制：本机初次使用不存在的`timeout`命令未发出SSH，后改Python超时包装器；其中一次包装器会话的最终输出/状态未回收，随后另一次调用取得完整成功输出，两次可能短暂重叠。因此17.868GB只表示成功记录的读取量，不能证明整阶段只执行一次或精确累计IO。报告保留全部已知尝试及不确定性；未据此产生模型或删除资格。

## 归档与恢复：已知位置核定，源文件继续保护

已知minimal试点 `workspace/evidence_archive/v4.1-prompt-minimal-v1-seed3411/` 的MANIFEST在场，摘要已核；限定路径检查表明归档的`evaluation/evaluation_records.jsonl`缺失，原run同名文件存在（432,796字节），仅stat、未读取内容。原run的指定配置及日志在场，不等于归档副本或独立备份已经完整。未继续搜索缺失concise/visual模型，不读逐样本预测、标签、真实test或媒体；删除清单仍为空，删除0。

`/data`当前可用约3.65TB，`/home`约383GB；容量足够不证明备份/恢复可用。本机`/Volumes`只观察到系统盘入口，未得到真实备份盘或完整snapshot准确根路径；本轮没有恢复目标、实际SQLite/模型/媒体/基座组合备份及恢复演练。RECOVERY-VALIDATION继续保留未完成，不创建空正式记录补齐目录。

## CONTRACT-NAMING：完成边界说明

仅修改`pipeline/v3_candidate_plan.py`和`v3_candidate_media.py`的module docstring，说明候选计划校验`tensile-vlm/v3`、后续V4.1审查/训练发布复用候选并另载V4.1契约；同步[模块索引](../../pipeline/SCRIPTS.md#候选规划与媒体物化的契约边界)和[数据指南](../data-workflow.md#候选层与发布契约)。正式入口仍为`python -m versioning data`和显式完整身份，不恢复legacy重建发布入口。

两模块移除module docstring后与起始提交AST完全一致；imports、函数、行为与身份构造未变，compileall及diff-check通过。候选/媒体派生身份不使用这两个模块整文件源码SHA，因此说明不改变产物身份。无需改名，本任务按澄清目标完成；没有为文字修改另跑业务测试。

## 旧指针与剩余任务

RELEASE-POINTER继续待确认：`finetune.release_validate`仍允许省略`--release-id`，会通过`v4_1_runtime.validate_release`读取旧活动指针；新versioning发布/训练则使用显式完整data身份。兼容读取仍存在，不能凭迁移完成把原维护目标关闭为误报；本轮不恢复旧指针写入，该待决项不阻塞新链路。

[项目TODO](../project-todo.md)保持唯一台账。EVAL-DEVELOPMENT/HOLDOUT/PERFORMANCE/INTEGRATION、MODEL-DIAG、归档/恢复与MODEL-QUALITY的真实验收仍各自未完成。后续实际需要的是完整固定来源、真实隔离/客户端DOM与签名部署、准确备份目标及相应真实运行授权；HOLDOUT-BUILD/FINAL-TRAIN不越过真实test及训练限制。

## 收尾验证

独立审查通过，无剩余可执行问题。reviewer独立复验两candidate AST（去module docstring）、本地轻量来源/provider绑定、实际localhost tags/show/ps和内核canary；逐项核报告内嵌脚本/原始结果/24file汇总、官方观察比对边界及六份受影响MD。远端事实来自executor，本轮reviewer未另SSH或复读大型权重，官方API/main观察来自researcher，未写成固定commit全文件证明。主Agent最终检查283个本地链接/锚点、37唯一任务ID、5份新JSON及引用摘要、AST/compileall/diff-check均通过；只改module说明，不为此重复业务测试。同次提交由 `git log -- pipeline/v3_candidate_plan.py docs/project-todo.md` 追溯；本轮不push/merge。
