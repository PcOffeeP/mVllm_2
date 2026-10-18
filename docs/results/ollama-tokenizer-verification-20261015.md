# Ollama安装包分词核验与NFC/NFD差异

后续状态（2026-10-16）：用户要求按原方案修复兼容，原A/B选择已撤回；本文保留当时观测，现行执行见兼容修复记录（该记录已随 2026-10-18 清理移除，结论见 `docs/project-todo.md` 对应条目）和TODO。

## 授权与观察范围

2026-10-15用户授权继续按TODO核定本机Ollama分词、查清NFC/NFD差异、提出不改原文方案；重大取舍须先确认，真实模型评测和真实test继续禁止。起始Mac `52d6afbd`、工作区干净、分支 `feat/evaluation-development`。本轮仅已安装工件只读身份检查及公开合成字符串的词表专用编码；不启动完整Ollama runner/server、不加载推理tensor、不创建context或decode、不生成模型回答、不读真实test/项目预测，不创建eval/claim/部署receipt、不改生产计数provider/冻结规则或既有环境，不push/merge。

**本轮取得的是已安装包内x86_64动态库的实际执行结果；原生arm64 server仍未执行测量。** 不能缩写成“Ollama原生服务已经实测”，也不能将独立重编源码counter替代本机工件证据。

## 本机工件与架构

| 工件 | 当前观察 |
| --- | --- |
| Ollama CLI | `/Applications/Ollama.app/Contents/Resources/ollama`；SHA256 `bd835b935229256fc8c5fcd983bef69f5b6142d4fa4f5d8baa05e5e77fd13fbf`；版本0.33.1 |
| 随包llama-server | SHA256 `785c676fcddac7252260ab5b056b64493243ca8e1e0a1a914efcaa67f6878b42`；universal x86_64+arm64；版本输出commit d222767c7 |
| 动态词表库 | 本机libllama.0.3.0、libggml.0.22.0、libggml-base.0.22.0为x86_64-only；完整路径/摘要及实际装载身份在[机器记录](ollama-tokenizer-reference-20261015.json) |
| 签名 | App/相关工件codesign验证通过；Team ID `3MU9H2V9Y9`，Infra Technologies, Inc；签名完整性不等同源码可复现构建证明 |
| 原生arm64路径 | 分词符号静态嵌入llama-server，无普通可链接arm64 libllama；CLI/server帮助无vocab-only入口，不尝试将可执行文件特殊加载为动态库 |

官方[Ollama v0.33.1固定源码](https://github.com/ollama/ollama/tree/13f2fb8c99278469b954429d5541019f4d83a4d0)绑定llama.cpp b10630，即 `d222767c7a6516559a3f49e7721b6c6b1acc87b4`。官方release小型checksum只列归档，不列内部单文件摘要；未下载大安装归档，未取得本机CLI单文件的公开attestation，所以不能以版本字符串追认完整转换/构建链。前轮[固定来源材料](evaluation-tokenizer-materials-20261015.md)的两个HF候选与本机GGUF转换历史边界仍保持。

## 已执行的安装包x86词表核验

现有Rosetta可用，没有安装或变更系统组件。辅助程序用固定d222头文件按x86_64 ABI编译，链接本机已签名x86库；未重编词表实现冒充安装库。核心路径只调用model默认参数、词表专用加载、get_vocab、tokenize和free：

- `vocab_only=true`；固定源码在tensor loader前返回。
- `devices={nullptr}`、`split_mode=NONE`、`n_gpu_layers=0`，不用默认GPU枚举；不调用backend_init、load_all、创建context或decode。
- 原始UTF-8输入文件不做NFC/NFD转换；`add_special=false`、`parse_special=true`。
- helper运行在禁止网络的sandbox；明确冻结实际libllama/ggml/base三库角色、路径和摘要，并核helper日志的实际loaded images，不能只相信caller列的无关文件摘要。
- 所有HF文件、封存合成输入、批准manifest及其GGUF、headers、helper和库先验摘要，漂移拒绝；输出永远不是部署或独立等价批准。

[可复跑离线auditor](../../finetune/eval_audit_tokenizer_parity.py)要求显式spec和新输出路径；缺参只显示参数错误，不执行任何模型路径。完整spec、helper源码、编译命令、实际调用、完整IDs、资源观察及限制保存在[机器记录](ollama-tokenizer-reference-20261015.json)。可使用独立Python3.11环境以 `python -m finetune.eval_audit_tokenizer_parity --spec /absolute/spec.json --output /absolute/new-report.json` 执行；不自动创建spec、下载组件或运行完整server。

## 分词差异与根因

前轮16个HF公开合成prompt加6个归一化诊断，另加2个固定预算反例，本轮安装包x86库共24次：与HF完整IDs相同16次；前轮counter有对应结果的22次全部同ID。每模型结果如下：

| 输入类别 | HF | 安装包x86库 | 判断 |
| --- | --- | --- | --- |
| 8个原始公开prompt中的Unicode case | 31 tokens | 32 tokens | 不等 |
| NFC `café` | `[895,56868]` | `[895,56868]` | 相同 |
| NFD（`cafe` 后接U+0301） | `[895,56868]` | `[895,1795,52033]` | 不等 |
| NFC与NFD组合诊断 | 3 tokens | 4 tokens | 不等 |
| 固定4000次NFD预算文本，原HF模板渲染 | 4013 input tokens | 8013 input tokens | +512输出后4525／8525；8192预算判断相反 |

已冻结的官方HF tokenizer.json原本声明NFC；原生Tokenizers.from_file与AutoTokenizer均遵循该配置，不是仅某个加载分支的新错误。所观察的x86 GGUF实现保留分解码点再BPE，因此HF可能低估发送原文的实际token数；不是固定“加1”就能解决。原始输入/失败case完整保留，不做Unicode正规化或删除样本。

官方[GGUF Tokenize路径](https://github.com/ollama/ollama/blob/13f2fb8c99278469b954429d5541019f4d83a4d0/llm/llama_server.go)转发原content，固定上游qwen35 splitter及compat patch未增加NFC。源码与本轮x86结果相符，但实际原生arm64 server行为仍需单独身份与校准证据。不能只因同包或同commit字符串，就把x86观测推广为arm64或所有Unicode输入证明。

## 验证与独立核查

最终实际执行记录为24个词表case，其中16个完整HF IDs相同，原有22个与前轮独立counter完全相同。新增预算反例的源UTF-8、生成规则、SHA、完整IDs和两侧预算结论均封存；不发送给模型，也未用正规化消除反证。机器记录SHA256 `b6caca37313facc938592d7a8575dee38b64cad708a53ee27e523fab52dd4389`。

- tester：`.venv/bin/python -m pytest -q tests/test_eval_audit_tokenizer_parity.py --basetemp /tmp/mvllm-tokenizer-parity-synthetic-20261015-final3`，28 passed／0.11秒／退出0，全为临时微型资产与stub，不调用真实库。
- 独立reviewer：28项保护复跑，28 passed／0.10秒／退出0；独立codesign、架构、实际loaded-image复核及最终24词表case完整IDs/原字节SHA/预算逐一重现，退出0。中间22项测试和22词表case是早期轮次，不并作额外最终数量。
- 独立检查发现并修复audit工具证据缺口：曾只验caller列的实现文件摘要，现强制三个安装库角色/路径/架构并核实际dyld images、执行后摘要和原批准model manifest；错误库、路径注入或执行期间漂移均拒绝。

独立核查结论：**本轮核验材料及A/B草案交付通过，无剩余可执行问题；不批准生产计数资格或正式等价映射**。独立reviewer线上复取了固定llama.cpp早退路径及Ollama compat patch，未把它扩大成全部源码或可复现构建核验。最终28项保护命令使用新basetemp `/private/tmp/mvllm-ollama-parity-review-final-tests-20261015`，28 passed／0.10秒／退出0；独立最终24词表观察为 `/private/tmp/mvllm-ollama-parity-independent-final24-20261015.json`。

本轮实际词表诊断与pytest单元测试分别记录，不写成真实模型评测成绩。compileall、diff-check及201个相对链接/锚点、37个唯一任务标识检查通过。用户方案选择仍待答复，核验工具不是生产counter。

## 方案交接

[对齐方案草案](../plans/2026-10-15-review-tokenizer-alignment-design.md)比较运行时词表计数权威与HF严格一致两条路线，均保持raw和已有冻结模板不变；选择仍待用户确认，未改生产provider。原生架构/实现身份与预算安全证据不足时继续拒绝，不用x86旁证提前放行。真实评测/test授权与HOLDOUT-BUILD等父任务仍未解除。
