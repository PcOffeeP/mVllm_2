# 基座固定 revision 配置、tokenizer 与代码来源核验

## 范围与执行边界

2026-10-16用户要求继续补齐基座固定revision配置、tokenizer和代码来源，完成不依赖真实模型的准备并实时更新TODO；禁止真实模型评测或真实test。起始Mac `defa954b`、干净工作区。训练机只读原基座 `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`，没有改写资产、同步代码、安装依赖、加载tensor、执行模型代码或登记正式model/eval/claim。

本轮复用了项目已有 `.venv` Requests默认证书验证路径，解决系统Python/curl的信任链读取限制；没有关闭TLS验证、修改系统证书或下载大权重。官方小资产与训练机小文件副本只留在Git忽略目录，报告保留身份、实际脚本和必要静态结果，不把tokenizer词表或大权重入库。

## 固定 Hugging Face revision 已逐项核定

[官方取证报告](minicpm-fixed-revision-upstream-20261016.json)确认 `openbmb/MiniCPM-V-4_5@daef484c35ec93210ec93c5e901f8f3e9b78ee34` 的API和完整顶层树。23个官方tree对象的实际raw字节Git blob SHA-1逐一匹配；tokenizer正文另对固定LFS指针的SHA-256和大小校验，四个大权重只取LFS pointer、不下载正文。官方[固定树](https://huggingface.co/openbmb/MiniCPM-V-4_5/tree/daef484c35ec93210ec93c5e901f8f3e9b78ee34)与此前main观察明确区分。

对训练机原23项白名单：16个小文件原字节和4个权重身份与同一个固定revision相同，共20项；2项不同、1项额外。config、generation config、tokenizer及其vocab/merges、processor/image processor、权重索引与其余Python文件的核验已从“未比对”改为有实际固定版本证据。官方树还有 `.gitattributes`，不在此23项采集集合；该集合不是整个模型目录的原样快照。

| 对象 | 固定HF比对 | 后续来源核验 |
| --- | --- | --- |
| `modeling_minicpmv.py` | 训练机多出 `self.post_init()` | 两个官方固定渠道均未含该调用，来源/用途未核定 |
| `README.md` | 训练机少一条MiniCPM Wiki链接 | 与官方ModelScope历史版本相同 |
| `configuration.json` | 固定HF不存在 | 与官方ModelScope历史版本相同 |

## ModelScope 来源线索与已确认代码偏差

[下载来源报告](minicpm-base-download-origin-20261016.json)将 `.msc`/`.mv` 作为未签名来源线索，而非原始下载事件的证明。`.msc`只通过严格容器/字符串opcode静态解释读取，未使用pickle反序列化执行；`.mv`记`Revision:master,CreatedAt:1773133067`。

官方OpenBMB发布说明链接ModelScope同模型。按缓存线索读取完整固定revision `2626e837a54905aab70fae9325153ef3454387ab` 的官方树，23条每文件revision均对应，树时间与`.mv`一致；响应明确区分完整pin请求URL、短提交号和README完整revision字段，未伪称API独立回显完整root hash。训练机22/23项字节身份与这棵官方历史树相同；README和`configuration.json`另下载固定文件正文核实，因此不能把这两项归因为本地定制。

唯一保留的运行时代码偏差：训练机 `MiniCPMV.__init__` 在`self.terminators`后增加`self.post_init()`。官方固定HF及缓存声明的ModelScope `modeling_minicpmv.py@80f6f183c296da5ef84f6dc9a29bb5f4070a5896`均为18,583字节、SHA-256 `da7e53e9…`；训练机为18,609字节、SHA-256 `f385948d…`。只有该构造函数AST不同，其余16个同名函数AST相同，无函数增删。新增方法调用是确定的构造控制流差异，不能称纯文档差异或已证明等价；本轮未执行它，未判断具体权重/输出影响，也未确认修改者、时间或原因。

现有基座因此不能宣称为官方固定revision的原样代码快照。保留真实目录及差异证据，不自动回退、删除调用或更换基座，不生成可绕过核验的`source-provenance.json`。

## 训练机静态闭包与登记准备

[静态采集报告](remote-base-static-source-20261016.json)读取19个非权重白名单文件共16,136,319字节，前后及落盘后SHA/大小与前轮完整性记录一致；四片权重仅stat，对比device/inode/size/mtime/ctime及文件类型位，不重复读取17GB权重，也不把历史简化mode与当前完整权限位称为完全相同。

正确展开config/preprocessor/tokenizer的auto_map（含AutoTokenizer列表与null）后，5个唯一入口文件的AST相对import可达7个仓内Python文件，类名均存在。第三方依赖、条件flash_attn和实际运行环境未因此宣称闭合。`chat()`在未提供processor时含`AutoProcessor.from_pretrained(self.config._name_or_path, trust_remote_code=True)`；静态相对import检查不能证明真实运行不会继续解析路径或下载。

[无模型来源拒绝检查](minicpm-base-source-rejection-preflight-20261016.json)保存了实际stdin脚本、源码/配置摘要与stdout。主Agent在Mac用当前 `versioning.registry._base_provenance` 对只含实际小文件的副本和固定HF source/revision做来源检查，禁止网络及torch/transformers/safetensors/模型模块导入；实际退出0，捕获预期 `base source is unknown: require consistent local metadata or source-provenance.json`。只调用来源helper，未创建Registry、读取权重或产生eval/claim。该检查证明未附来源声明时的现有拒绝行为，不表示注册器会自动识别官方与本地代码差异；不得填一个非空verified_by替代本次差异核定。

## TODO 交接与验证

固定官方配置/tokenizer/processor/代码比对、下载缓存来源追踪及静态闭包已完成；剩余来源前置已收敛为上述构造函数差异的核定，原目录的完整身份仍不能按“未经修改的官方基座”登记。MODEL-DIAG、EVAL-DEVELOPMENT及真实模型父任务保持未完成；本轮不重开已确认的模型/质量方案或擅自处理代码差异。

[项目TODO](../project-todo.md)是唯一台账。独立审查通过，无剩余可执行问题。reviewer独立核HF固定API/tree/config及全部本地Gitblob/LFS身份，复取MS固定树的Data内容和代码正文，检查safe metadata解析、7文件闭包及实际代码diff；静态采集的比较reference/实际来源字段、SSH argv和mode比较口径已校正，跨报告SHA逐项一致。来源helper原样guarded脚本另经reviewer复跑0.73秒、退出0、stdout一致。主Agent最终293个本地链接/锚点、37唯一任务ID、4份新JSON/引用摘要与diff-check通过；同次提交用 `git log -- docs/results/minicpm-fixed-source-audit-20261016.md docs/project-todo.md` 追溯，不push/merge。
