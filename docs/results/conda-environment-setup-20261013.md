# 2026-10-13 正式 Conda 环境部署与绑定

## 目标与授权

用户同意新建符合当前项目依赖要求的 Conda Python 3.11 环境，保留旧 agent/cpm45，绑定正式 checkout。执行者 Codex；实际安装及环境验收在训练机，Mac负责编排、证据整理与本地文档提交。本轮不启动数据处理、模型加载、训练、推理或评测，不同步代码、不修改用户shell默认环境或全局依赖配置。

## 安装前事实

训练机项目 `/home/liuyang/文档/mVllm_2` 为 `main@3f200461026a59676aaac7ea864f8fadb599688d`，LlamaFactory 为 `4447137e08c172d7701594b4d1695a6d4a869cbd`，均干净。Mac起始 `151693d1`；远端不含近期本地文档改动，但两端GPU锁和检查器内容一致。

- GPU锁：`requirements-linux-gpu.lock`，241个精确版本项和1个editable条目，SHA256 `caf298c41681cfabe1fdaae707b0a4890e4e077a5d98b86ae18b658d7227416d`。
- 原检查器：`scripts/source_validate_environment.py`，SHA256 `b2caaa72a6762ce9f1b2fae13d6dab9b98d421f8d213f93d282a177d6d83fde6`。
- Conda 25.11.1；历史工具uv 0.11.21用于引导，随后复制其独立可执行文件进入新环境。
- 新目标 `/home/liuyang/miniconda3/envs/mvllm2` 起始不存在；新日志及缓存根 `/home/liuyang/mvllm2-conda-setup-20261013`。
- 安装前目标文件系统约374GiB可用、内存约120GiB可用，GPU为RTX4090。仅是当次资源快照，不保证后续任务有同样资源。

## 安装与验收

实际安装脚本SHA256为 `b7a720d996dbd397249f21835e73ccac3e26b1608964286a1dc4a3db4aca90a6`，经修复和独立复验后执行；安装SSH exit0，后续审计SSH exit0。已建立并显式选定训练机正式解释器：

```bash
PYTHON=/home/liuyang/miniconda3/envs/mvllm2/bin/python
cd /home/liuyang/文档/mVllm_2
"$PYTHON" -m versioning --help
```

用户交互shell也可激活 `mvllm2`；本轮未修改默认shell环境。该解释器及editable均绑定训练机现有正式checkout `main@3f200461`，没有同步Mac近期提交。

| 检查 | 实际结果 |
| --- | --- |
| Python / prefix | 3.11.17，`/home/liuyang/miniconda3/envs/mvllm2`，Conda环境 |
| GPU锁241个精确项 | 缺失0、版本不同0；另核对LlamaFactory editable |
| 依赖兼容性 | `uv pip check`检查244包，通过；244不表示全部包都是锁中的精确条目 |
| 原doctor | `errors=[]`，`model_loaded=false`，`training_started=false` |
| CUDA / torch | CUDA可见、device_count=1，torch2.5.1+cu124；不是模型或训练执行验收 |
| 关键组件 | LlamaFactory0.9.6.dev0、DVC3.67.1、MLflow3.15.2、AV16.0.0、pandas2.3.3 |
| editable来源 | 正式 `/home/liuyang/文档/mVllm_2/LlamaFactory` |
| 代码 / 子模块 | HEAD分别保持3f200461 / 4447137e；安装前后工作区干净，锁与原doctor摘要不变 |
| 旧环境保护 | agent 163包、cpm45 109包的发行包元数据快照相同；两环境conda-meta清单与lib/python3.11下pycache元数据摘要前后相同 |
| 项目字节码保护 | 安装脚本所查范围pycache清单544项，前后摘要相同 |

新环境 `du`约6.9GiB，检查时目标文件系统仍约366GiB可用。证据中的prefix、Conda缓存、uv缓存、日志大小是一次联合du的硬链接去重结果，不能把每项理解成该目录单独测量的总占用。本轮保留缓存和日志，没有清理已有或新环境。

原doctor导入产生了Streamlit缺ScriptRunContext警告和WANDB离线提示，但返回errors为空、exit0；本轮没有调用训练函数或生成正式训练记录。

实际安装使用Conda显式新prefix与Python3.11；从完整conda-forge URL获取Python基础环境，通过新环境解释器按当前GPU锁安装，PyPI依赖使用显式无凭据HTTPS清华镜像。安装工具uv不参与日常Python入口选择。既有Linux部署脚本创建venv，本轮不以它创建Conda，也不改变该脚本的接口。

执行前独立审查发现缓存、Git配置及Python字节码隔离需要修复。修复限制在本次安装辅助脚本：缓存绑定新run；Git禁用可选锁和外部fsmonitor配置；查询禁写字节码。原检查器文件不改，实际运行包装仅给检查器的Python子进程添加禁写字节码参数，业务检查与退出码保持原样。

## 证据与限制

[执行证据快照](conda-environment-setup-20261013.json)保存冻结安装脚本、安装/审计命令与退出码、原始返回日志、doctor及安全裁剪的旧环境对比。原始旧环境JSON的前后SHA相同，URL裁剪只用于安全展示，不冒充原始文件摘要。

本轮脚本及原始日志保存在Mac `/private/tmp/mvllm2-conda-setup-20261013/`，远端安装日志保存在上述新run。安装前独立审查及修复复验已通过；实际执行结果与文档独立核查通过：冻结脚本、原始返回与持久化快照一致；241锁项、doctor、旧环境保护、Git状态及业务路径结果均核对；原31个任务标识保留，83个本地链接/锚点有效，diff格式检查通过，未检出常见凭据模式。reviewer没有再次SSH或复跑安装，结论基于已捕获证据。提交由 `git log -- docs/results/conda-environment-setup-20261013.md` 追溯。旧环境证据覆盖发行包元数据、conda-meta及指定字节码元数据，不等于整个旧环境每个文件的逐字节审计。

新体系数据release和迁移回执已在场；尚未执行新体系正式训练、评测及模型注册时，对应业务记录未产生符合阶段预期。本轮不为补目录而初始化MLflow或制造空训练/评测记录。环境验收不证明实际模型可加载、训练可完成、最终质量或独立test通过。
