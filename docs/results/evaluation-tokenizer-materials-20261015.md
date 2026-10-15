# 固定tokenizer来源、独立评审环境与映射材料

## 本轮范围

2026-10-15用户授权继续核定两批准评审模型的HF tokenizer来源与固定revision，补独立Python3.11环境及受审映射材料。起始Mac `696ea17c`、干净工作区、`feat/evaluation-development`。本轮允许固定tokenizer小文件下载、隔离依赖安装和公开合成字符串的CPU tokenizer-only核验；不下载模型权重、不进行真实模型评测/生成、不读真实test或项目预测，不创建eval/claim/exposed/部署receipt，不改训练机、现有开发/GPU环境或TensileAgent，不push/merge。前轮[库存核验](evaluation-readiness-20261015.md)的“未安装/未下载”只描述前轮，本轮授权已扩展。

## HF来源与固定revision

| 本机冻结标签 | 官方HF tokenizer来源 | 本轮固定revision |
| --- | --- | --- |
| qwen3.5:9b | [Qwen/Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B/tree/c202236235762e1c871ad0ccb60c8ee5ba337b9a) | `c202236235762e1c871ad0ccb60c8ee5ba337b9a` |
| ornith-1.5:9b | [ornith-ai/Ornith-1.5-9B](https://huggingface.co/ornith-ai/Ornith-1.5-9B/tree/489cb97981b8654bcfcf30ce1f94ed1b62e07b53) | `489cb97981b8654bcfcf30ce1f94ed1b62e07b53` |

从官方HF API取得完整commit，再按该commit读取tree/config/README/tokenizer文件，不以main作为冻结身份。Qwen选post-trained Qwen3.5-9B而非Base；Ornith选其官方checkpoint自己的文件，不因同族而整目录复用Qwen。

**来源核定与本机GGUF转制历史分开**：以上核定可追溯的官方HF候选与精确文件；并未证明本机冻结GGUF的转换链。官方[Ornith GGUF固定tree](https://huggingface.co/ornith-ai/Ornith-1.5-9B-GGUF/tree/abdd624b12ebf020b767fff532ff44fe552b28c3)的Q4_K_M为SHA256 `70c112196e0b7023803c9762752e46d29e612a92c83f995bc3ba1ceb07e8fab6`、5,780,090,816字节，与本机blob不同。当前Ollama Qwen页面标签也已变动，不能拿当前网页替本机冻结旧digest追认来源。后续审计应针对已冻结本机GGUF词表/算法及真实来源材料，不换模型来凑匹配。

Qwen固定仓有实际Apache-2.0 LICENSE。Ornith固定模型卡声明MIT，但该revision无LICENSE文件、卡中链接返回404；当前只保存声明事实，不声称完整许可文本在场，也不用Qwen的LICENSE替它。

## 本地tokenizer资产与模板

下载清单与完整字节摘要见[HF资产清单](evaluation-tokenizer-hf-assets-20261015.json)。每模型分别保存5文件：`tokenizer.json`、`tokenizer_config.json`、`merges.txt`、`vocab.json`、`chat_template.jinja`。共10文件45,816,769字节，存于忽略目录 `workspace/review-environment/tokenizers/` 下两个独立目录；逐文件核固定API tree的Git blob SHA1/LFS SHA256、大小和本地SHA256，没有下载权重或remote Python代码。

两模型的前四文件相同；独立Jinja文件不同：

- Qwen：`a4aee8afcf2e0711942cf848899be66016f8d14a889ff9ede07bca099c28f715`。
- Ornith：`9dd2fbd270feaa1fbef2d4f634d7887c9c506e3bde140f8e7351c8944e8fd235`。

各自tokenizer_config内嵌模板相同，独立Jinja改变历史assistant reasoning保留规则；实际本地AutoTokenizer优先独立Jinja已核验。公开多turn样例分别47/51个token，不能因单轮相同就声称模板相同。

当前provider允许文件集合原先遗漏独立Jinja，本轮仅增加 `chat_template.jinja` 白名单；仍逐字节冻结完整目录、拒额外代码/symlink、local_files_only=True/trust_remote_code=False。provider新SHA为 `c3e3914fd7448b34f446995bc21e7a3474e3ca61ecae49cd1a0529ca2063ef29`。已有冻结对象若绑定旧provider字节不能追认升级，须遵循原不可变规则准备新对象；没有放宽历史兼容表或重写记录。

## 独立Python3.11环境

环境：`workspace/review-environment/python311/bin/python`，CPython3.11.14，`include-system-site-packages=false`。复用现有uv管理的基解释器创建新环境，不修改现有`.venv`依赖。固定Transformers5.19.0、Tokenizers0.23.3、PyYAML6.0.3和Jinja2 3.1.6，共29包；Ornith卡要求Transformers≥5.8.1，保存配置的5.12.1不当作最低版。未装torch/CUDA。

可复现输入和hash锁：[requirements-review.in](../../requirements-review.in)、[requirements-review.lock](../../requirements-review.lock)，仅针对本机macOS arm64/Python3.11，不替代Linux GPU锁。实际29个官方PyPI wheel共29,644,920字节，对照官方SHA及锁验证；5,010个已安装wheel文件逐字节匹配。持久证据为[环境验证](evaluation-tokenizer-materials/environment-verification.json)、[wheel清单](evaluation-tokenizer-materials/official-wheel-inventory.json)和[freeze](evaluation-tokenizer-materials/installed-freeze.txt)，完整安装文件库存和wheel缓存留在忽略目录。

```sh
uv --no-config pip compile requirements-review.in --python-version 3.11 --python-platform aarch64-apple-darwin --default-index https://pypi.org/simple --only-binary :all: --generate-hashes --emit-index-url --output-file requirements-review.lock
uv --no-config venv --python 3.11 workspace/review-environment/python311
uv --no-config pip sync --python workspace/review-environment/python311/bin/python --require-hashes --only-binary :all: --default-index https://pypi.org/simple requirements-review.lock
uv --no-config pip check --python workspace/review-environment/python311/bin/python
```

这些是未来空目录重建命令，不覆盖现有环境。本轮实际创建前确认目标不存在，使用完整uv管理解释器路径。官方HTTPS请求保持证书验证；系统Python/curl信任链失败时使用项目Requests默认证书验证成功的路径，没有关闭TLS验证或新增系统信任。

## tokenizer-only映射材料

[HF侧渲染材料](evaluation-tokenizer-materials/hf-only-render-cases-20261015.json)保存每模型8个公开合成case，覆盖ASCII、中文/Unicode、special token字面量、多turn、空白及接近8K预算；冻结messages、raw prompt、完整token IDs、special行为、库与实际模板身份。最大样例7432 input＋512 output，在8192上下文内；没有使用模型回答、视频、真实test或真值。

材料只涉及编码已知文本，不是运行模型回答评测。[独立GGUF counter材料](evaluation-tokenizer-counter-20261015.json)已完成：官方llama.cpp固定commit `620d2225cc436ab0b001e3200e590e3b286ef9ab`，解压源码按Git对象重建tree `6868e0a538a05e9a253a0b86ccb71b4e06a64684` 与官方commit一致，另冻结archive/源码清单/关键源码/二进制摘要。CPU-only只构建llama-tokenize，Metal/CUDA/Vulkan/BLAS等关闭；源码 `vocab_only=true` 在载入tensor权重前返回，未加载推理权重或执行生成。固定 `--no-bos --ids --no-escape`，special解析采用已核源码默认true，逐条传同一HF raw-rendered文本。二进制和源码/log保存在忽略的 `workspace/review-environment/llama-counter/`，命令与结果在JSON可追溯。运行中control-token override及n_ctx_train告警如实保留，不把告警当作已验证Ollama语义。

**实际反证：16次有限比对中14次完整IDs匹配，2次不匹配，不能批准等价映射。** 两模型Unicode case均HF31 token／GGUF32 token，分歧来自分解形式 `cafe\u0301`：官方原始tokenizer.json已声明NFC，HF直接Tokenizers.from_file与Transformers AutoTokenizer均正规化；GGUF counter保留分解序列。单独NFC `café` 两侧为 `[895, 56868]`；NFD形式HF仍为 `[895, 56868]`，GGUF为 `[895, 1795, 52033]`。这不是凭换依赖版本即可消除的AutoTokenizer加载偏差。逐ID材料、原始文本、6项诊断和库/源码身份均保留，没有归一化评审raw、修改模板、替换模型或删去失败case。

该独立counter是固定llama.cpp词表实现，不自动代表已安装Ollama0.33.1的所有tokenization行为；有限匹配也不是所有输入证明。当前反证已足以阻止将这套HF/GGUF材料记为等价，不能只等签字就放行。除转换来源仍未闭合外，必须先明确原文不变条件下的计数/归一化差异如何处理；若需改变counter provider或原冻结协议，由用户确认，Agent不自行取舍。没有伪造独立审计者、已审映射或准入凭据。

## 已安装版本的官方源码旁证

本机Ollama二进制 `/Applications/Ollama.app/Contents/Resources/ollama` 为68,667,472字节，SHA256 `bd835b935229256fc8c5fcd983bef69f5b6142d4fa4f5d8baa05e5e77fd13fbf`；版本元数据为0.33.1。官方 [v0.33.1固定commit](https://github.com/ollama/ollama/tree/13f2fb8c99278469b954429d5541019f4d83a4d0) 的GGUF路径使用llama-server，固定的llama.cpp版本b10630对应上游commit `d222767c7a6516559a3f49e7721b6c6b1acc87b4`，与本轮独立counter的较新commit不是同一份源码。

只读核查：[raw路由](https://github.com/ollama/ollama/blob/13f2fb8c99278469b954429d5541019f4d83a4d0/server/routes.go)将req.Prompt原样交下游并跳过模板；[Tokenize路径](https://github.com/ollama/ollama/blob/13f2fb8c99278469b954429d5541019f4d83a4d0/llm/llama_server.go)将原content JSON发送至子进程/tokenize，没有NFC调用；固定上游的[llama-vocab.cpp](https://github.com/ggml-org/llama.cpp/blob/d222767c7a6516559a3f49e7721b6c6b1acc87b4/src/llama-vocab.cpp)与[unicode.cpp](https://github.com/ggml-org/llama.cpp/blob/d222767c7a6516559a3f49e7721b6c6b1acc87b4/src/unicode.cpp)的qwen35路径对原文本做Unicode/正则分割，并未执行HF所声明的NFC。这些源码证据支持保留归一化差异阻塞，不能因另有Go/HF tokenizer代码就推定GGUF路径已NFC。

本段官方源码由researcher取证；reviewer只静读复核版本/引用与证据边界，其独立复取GitHub页面和固定raw URL因网络/TLS握手超时未成功，没有放宽TLS验证，不记为该补充源码已被reviewer线上复取。未运行已安装Ollama的生成/分词执行路径，也未证明本机二进制由该源码可复现构建。因此32-token独立counter结果不能标成“本机Ollama实测”；源码旁证不授准入。后续真实实现身份及不改原文的计数对齐仍须核定，必要方案变更另确认。

## 验证与交接

production窄修新增3项保护：独立模板字节漂移、symlink替换、允许Jinja不允许任意Python代码，连已有38项readiness共41 passed（0.12秒，退出0）。最终相关回归 `.venv/bin/python -m pytest -q tests/test_eval_review_tokenizer_assets.py tests/test_eval_audit_readiness.py tests/test_eval_holdout_semantic.py --basetemp=/private/tmp/mvllm-review-tokenizer-materials-regression-20261015`：**76 passed，17.93秒，退出0**，日志 `/tmp/mvllm-review-tokenizer-materials-regression-20261015.log`。没有变更eval_run/holdout适配字节或旧strict兼容表。compileall、diff-check、188个相对链接/锚点与37个唯一任务标识核查通过。

独立reviewer已复核官方固定tree/10资产、29wheel及5010安装文件、HF16组raw/IDs、独立counter16组及NFC反证。独立核查结论：**候选来源、环境及映射材料准备交付通过，无剩余可执行问题；正式等价映射不通过，继续阻塞。** 独立41项保护/readiness（1.06秒，退出0；伴历史pytest临时目录清理warning），并重算HF16、GGUF16和6归一化诊断，结果完全复现。76项整组为主线程回归，不冒称独立整组复跑。未执行模型回答或真实test。

下一步先以当前模型digest/固定HF文件/库/provider/模板和GGUF counter材料接受独立审计；有限cases相同不能当整个算法或所有输入的数学等价证明。没有真实受审映射与适用授权时，保持real review gate拒绝，不为了准备创建空eval或执行review_run。客户端测点仍按前轮TODO留待跨库授权，本轮不推进真实E2E或关闭MODEL-QUALITY。
