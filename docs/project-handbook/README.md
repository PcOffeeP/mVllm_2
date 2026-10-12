# mVllm_2

**把材料拉伸试验视频转化为可审查的视觉样本与结构化判断。** 本项目基于 MiniCPM-V-4.5，围绕试样是否断裂、断裂机制、断裂位置及特殊情况，提供数据准备、人工审查、LoRA 微调、严格评测和视觉服务流程。

这里是供审阅的新文档入口。原文档仍保留，当前工程能力与历史效果的证据时间见[项目现状](project-status.md)；本套文档通过后再决定替换位置。

## 项目介绍

### 判断一个时间窗口里的画面

模型观察一个有限视频窗口中的采样帧，每个窗口最多 8 帧。它依据窗口内实际可见的证据回答问题，不用片段外事件补全标签，也不直接把整段长视频当作一个训练样本。

当前使用 `tensile-vlm/v4.1` 四字段契约：

| 字段 | 含义 |
| --- | --- |
| `clip_state` | 未断裂、临界未断裂、发生断裂、已断裂或无法判断 |
| `fracture_mechanism` | 可见证据支持的断裂机制，不能判断或不适用时为 `null` |
| `fracture_site` | 标距内、标距外非夹具根部、夹具根部，或 `null` |
| `special_case` | 未夹紧、视频异常，或 `null` |

格式示例，不代表实际推理结果：

```json
{
  "clip_state": "发生断裂",
  "fracture_mechanism": "韧性断裂",
  "fracture_site": "inside_gauge",
  "special_case": null
}
```

“发生断裂”表示窗口内可见连续到分离的变化；“已断裂”表示可靠画面从窗口开始就已分离。普通“未断裂”窗口的其余三个字段均为 `null`。完整枚举与约束见[业务契约](../../pipeline/contracts/tensile_vlm_v4_1.json)。

### 从视频到模型

先保留视频来源和源视频级划分，以 ROI（需要观察的试样区域）裁剪或保留画面，生成候选窗口及采样帧。人工审查结果与媒体一起冻结成数据发布，再用 LoRA 更新少量附加参数，使基座适配拉伸试验画面。

开发阶段沿用三折 train/validation 划分，分别训练和验证以比较方案；最终 full 模型使用合格开发数据全集训练，另用独立 test 验收。上层自然语言任务编排、视频搜索和展示由独立的 TensileAgent 项目负责，本仓库提供视觉判断与相关数据、模型流程。

### 初步成果

数据处理、审查交接、版本管理及训练/评测/服务入口已有工程实现与验收记录。历史 Fold0 中间模型曾完成权重合并、真实视频服务和 Agent 调用；其 425 条开发侧 validation 的严格输出合法率为 **100%**，四字段联合正确率为 **41.18%**。这是单折开发结果，尚未证明最终独立 test 通过或生产可用。

当前重点仍是提升任务效果并完成真实模型验收。代码不附带原始视频、基座、adapter 或完整实验目录，也没有可据现有证据提供的一键最终模型演示。历史效果、资产缺口和当前工程边界统一见[项目现状](project-status.md)。

## 快速开始

### 1. 不安装也能了解项目

先阅读上面的输出示例，然后按目标选一份说明：

| 目标 | 阅读入口 |
| --- | --- |
| 把自己的试验视频整理成可训练数据 | [数据处理](data-workflow.md) |
| 准备实验、评测模型并部署服务 | [模型流程](model-workflow.md) |
| 了解现有成果、未完成项和证据日期 | [项目现状](project-status.md) |

### 2. 创建代码运行环境

取得代码后，在仓库根目录运行。先安装 Python 3.11、uv、Git、ffmpeg 和 ffprobe，确保后四项在 PATH 中可用。安装脚本使用锁定依赖创建新环境，不安装系统工具。

| 配置 | 用途与额外前置 |
| --- | --- |
| `mac` | macOS 代码检查、ROI/审查 UI 和同步结果复核，无需初始化 LlamaFactory 子模块 |
| `linux-gpu` | Linux x86_64 NVIDIA GPU 训练机的数据处理、训练和推理；需要驱动及可用 `nvidia-smi`，并初始化固定子模块 |

示例中的 `/absolute/python3.11` 是已有解释器绝对路径；`/absolute/new/environment` 是准备创建且尚不存在的环境目录，不能经过符号链接或包含 `..`。两种配置使用不同目录。

macOS：

```bash
python3 scripts/source_prepare_environment.py --profile mac \
  --env /absolute/new/environment --python /absolute/python3.11
```

Linux GPU：先确认具备[子模块](../../.gitmodules)对应 Gitee SSH 仓库的访问资格，初始化固定版本并保持干净：

```bash
git submodule update --init --recursive
python3 scripts/source_prepare_environment.py --profile linux-gpu \
  --env /absolute/new/environment --python /absolute/python3.11
```

安装退出码为 0 且输出 `Deployment verified` 表示环境检查通过。安装失败会保留部分环境；重试选择新的目标目录。Linux 可显式选择无凭据 HTTPS 包镜像，参数与维护规则见[部署接口索引](../../scripts/SCRIPTS.md)。

### 3. 查看入口并准备实际输入

使用新环境的解释器，不依赖当前 shell 激活状态：

```bash
/absolute/new/environment/bin/python -m versioning --help
/absolute/new/environment/bin/python scripts/source_validate_environment.py --profile mac
```

Linux 手动检查将 profile 改为 `linux-gpu`。检查覆盖依赖、公共入口和媒体工具；Linux 另核对 CUDA 与训练模块来源。它不会下载或加载模型、训练或推理。Linux editable 依赖绑定代码工作区，后续使用时须保留或重新核定该来源。

正式版本只有 data、prompt、train、model、eval 五类，名称为 `<kind>-v<协议>-r<N>`，例如 `data-v4.1-r2`。示例身份不表示你本地已有资产；版本和输入必须显式提供，不自动猜测“最新”。

接下来按[数据处理](data-workflow.md)准备视频、注释、split 和人工决定；按[模型流程](model-workflow.md)准备基座、正式数据、Prompt 和配置。GPU 训练、推理、完整评测及长时间媒体处理在训练机执行。环境安装通过与实际模型效果达标分别验收。

## 文档与代码导航

这套面向使用者的说明只有四份：本页负责介绍与初次安装，数据说明负责视频到发布，模型说明负责训练到服务，现状说明负责成果及限制。

实现入口为 [versioning](../../versioning/)、[pipeline](../../pipeline/)、[finetune](../../finetune/) 和[脚本接口索引](../../versioning/SCRIPTS.md)。设计决定与历史验证作为证据保留，不需要首次访问者先读完。

候选替换范围与独立核查记录见[整理说明](review.md)。本目录不改变项目授权、实际版本或当前唯一任务台账。
