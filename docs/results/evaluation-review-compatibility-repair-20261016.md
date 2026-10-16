# 评审兼容修复与运行前准备

## 本轮目标与边界

2026-10-16用户要求按原方案处理兼容问题，不再扩展方案讨论，继续TODO运行前准备并实时更新；仍禁止真实模型评测或使用真实test。起始Mac `4d397f1a`、干净工作区、`feat/evaluation-development`。前轮A/B待确认项已撤回，历史讨论从Git查询，当前入口统一回到TODO和本记录。

本轮只修本地编码适配并核验准备材料：不改原始回答或HF文件、冻结模板、模型、判读/仲裁、质量阈值、样本分母、8K上下文/512输出和超长不截断规则；不创建真实eval/claim、不启动完整Ollama服务或加载推理tensor，不调用模型生成、不读真实test/预测，不改外部客户端/训练机，不push/merge。

## 兼容问题与修复范围

前轮已经发现HF编码规则与GGUF不一致，会导致预算检查低估输入。该问题按provider内部软件兼容处理，不要求用户选择另一套测评方案。修复保留原HF模板渲染，单独构造符合冻结GGUF内容和规则的内存计数实例；不对发送文本做NFC/NFD处理，也不修改上游资产。

实现须从本机已冻结manifest及其模型层只读核验GGUF身份和完整词表元数据，检查完整token/ID、merges、special类型/ID、pretokenizer及实现规则；不只删除一个NFC设置，也不通过少数样例相同就补造等价证明。provider在内存中保留原HF渲染器，构建无NFC改写、与冻结GGUF预分词及special规则一致的编码器；分别校验两个模型的不同追加token规则，GGUF解析有64MiB元数据界限，不加载推理tensor。实现仍集中于原provider，现有实现摘要冻结覆盖全部兼容逻辑。

旧source/audit/receipt绑定原实现字节，不因本次代码修复自动更新；缺兼容材料或内容漂移仍在真实模型调用前拒绝。已有NFC/NFD及预算反证作为修复回归保留，不删样本、不补偿“加1”、不把基础设施失败当模型视觉错误。当前Ollama版本无公开tokenize接口，本轮不虚构HTTP路由或为计数启动完整server。

## 验证与准备产物

- 实现者公开词表回归：[兼容观察JSON](evaluation-tokenizer-compatibility-20261016.json)，原24组全部完整IDs匹配；新增566组包含两个模型的全部追加字面量、Unicode和控制组合，全部匹配安装包x86库。原HF资产字节未变。NFD预算反例仍为输入8013、加512后8525，超过8192，预检正确拒绝。
- tester执行 `PYTHONPATH=workspace/review-environment/python311/lib/python3.11/site-packages .venv/bin/python -m pytest -q tests/test_eval_review_tokenizer_compatibility.py --basetemp=/private/tmp/mvllm-compat-synthetic-final-20261016`：29 passed，24.10秒，退出0。保护原文/模板/资产不变、请求前预算拒绝、两模型规则、完整资产漂移、有界元数据读取及v2受审绑定；仅临时合成资产与stub网络。
- 独立reviewer另行读取冻结GGUF和实际安装包x86 helper，[582组公开合成case](evaluation-tokenizer-compatibility-independent-20261016.json)全部完整IDs匹配，两个模型预算反例均重现；helper与实际装载三库执行前后摘要一致，日志确认vocab-only跳过tensor。独立保护复跑为新增29＋既有semantic35，共64 passed，45.91秒，退出0；执行命令为上述PYTHONPATH加两个测试文件，basetemp为 `/private/tmp/mvllm-compat-review-tests-20261016`。实现者另跑原assets3＋semantic35，共38 passed。最终材料与inventory见下条。

- 离线inventory已同步v2兼容材料静态结构，v1仅保留历史声明读取并明确不能授权当前计数器；草稿仍不可充当证据。实现者合成保护 `tests/test_eval_audit_readiness.py` 初轮61 passed；独立审查发现畸形v2声明下basis可能绕过GGUF禁读保护，已使别名检查不再依赖其余schema合法性并补两项反例，最终63 passed，0.20秒，退出0，基于临时微型文件；工具不实例化tokenizer，不读取GGUF内容，不连接服务。[新版实际库存](evaluation-review-readiness-20261016.json)由独立Python3.11环境执行，两模型来源、v2静态结构/绑定及依赖摘要均匹配；唯一剩余blocker说明inventory本身不能证明等价、隔离或真实运行授权。`ready_for_real_review=false`保持不变，GGUF正文不由该盘点工具读取；真正完整资产与golden验证由上项独立离线校验承担。

- 新版[来源输入](evaluation-tokenizer-compatibility-materials-20261016/tokenizer-sources.json)与两个模型v2审计已封存，绑定本次provider字节、固定HF文件、manifest/GGUF及兼容规则；每模型9条实际golden含NFD预算例。[离线验证记录](evaluation-tokenizer-compatibility-materials-20261016/offline-validation.json)执行资产检查、原HF本地加载、内存兼容构建和审计校验，18条完整IDs全部通过。具名审查者为本次独立reviewer `/root/compat_repair_review`，审查结论限静态兼容和公开词表行为；未调用元数据路由、部署verifier或生成部署receipt。

软件兼容验证和公开词表检查不等于真实模型评测。原生arm64完整服务未执行，不据x86观察宣称真实部署、质量或性能已通过；实际运行仍须原有授权与部署/隔离等证据。

## 收尾验证

独立审查通过，无剩余可执行问题；独立inventory63 passed（0.17秒），畸形v2原反例在任何GGUF正文读取前拒绝。最终sources的完整资产、默认构建/审计及每模型9条golden亦由reviewer独立复验通过。214个本地链接/锚点、37个唯一任务标识、compileall及 `git diff --check` 通过。提交内版本用 `git log -- finetune/eval_review_deployment.py` 追溯。独立验证覆盖兼容实现、合成保护、真实公开词表观察、v2输入材料与当前文档；不扩展为真实业务运行。

## TODO交接

[项目TODO](../project-todo.md)是唯一台账。兼容工程完成后仍须分别记录实际本地环境、隔离、模型部署与客户端显示测点的证据；本轮不恢复前轮A/B讨论，不把源码或x86观察写成原生arm64服务效果，也不代替真实运行授权。
