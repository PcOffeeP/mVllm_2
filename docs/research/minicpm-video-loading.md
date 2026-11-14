# MiniCPM 视频加载与模型输入核查

**核查日期：**2026-11-10。本文供主会话审阅，结论只适用于下述代码和证据版本；不是新的训练、测评或数据处理方案。

**核查对象：**TensileAgent-Finetune 方案基准 `61f29eb546aa89d844a238e9d3e59cb3f664c1e5`；原项目 `mVllm_2` 工作树检查时为 `2c272ce3548c917bbfa96fe474858f9bf1998893`；两个提交所指向的 LlamaFactory 子模块均为 `4447137e08c172d7701594b4d1695a6d4a869cbd`。涉及的旧视频加载器、旧推理运行时、旧采样辅助器及子模块指针在这两个提交之间没有差异。本工作区为稀疏检出，旧代码没有显示在工作树中，不等于不存在于 Git。

文中仓内路径以相应项目根目录为起点；LlamaFactory 路径以子模块根目录为起点。路径和行号用于定位上述固定提交的源码，不保证之后的工作树文件保持相同。

## 结论

1. **本轮还不能确定实际会加载的模型版本、具体权重、处理器或训练／推理入口。** `docs/design-test.md:9,142` 要求另行核实输入链路，`docs/TODO.md` 的 EVAL-DESIGN 等待确认具体模型名单，迁移大纲第 5 节仍把训练、合并和测评列为后续审查。本轮五类标签和测评入口尚未接到旧链路。仓内存在 MiniCPM 4.5 的历史配置和代码，但它们不是对本轮的选型确认或实际运行证据。
2. **历史训练和历史评测有不同的读帧入口。** 前者经 LlamaFactory 的 `MiniCPMVPlugin` 用 PyAV 采样；后者经项目自己的 `load_video_frames` 解码抽帧，再把帧列表送入 processor。两者都能保持输入列表的先后顺序，但默认路径没有向 4.5 processor 提供真实时间戳；默认 `None` 在核查的 4.5 image processor 中会被转换为逐图／逐切片的 `[-1]`。顺序位置仍然存在，不能据此判断模型是否理解时序。
3. **4.5 官方模型卡示例也先由外部代码抽帧，但时间分组与旧默认流程不同。** 它用 Decord 读取视频，计算按 0.1 秒网格量化的时间编号，并把连续帧分组后显式传给 `model.chat`。作者还有一个每秒约 1 帧、最多 64 帧且不传 `temporal_ids` 的 4.5 示例；不存在本报告可以笼统称为“唯一官方默认”的流程。
4. **可以在实际调用边界留存模型输入，但现有记录尚不等于完整复原。** 旧评测运行时支持可选保存传给 processor 的 RGB 帧，并返回 PTS；目前调用者是否启用、processor 后的切片与张量、帧序及时间组是否随同结果绑定，不能从这一接口本身保证。训练侧没有看到本轮已接入的逐请求输入留证。
5. **已实跑合成视频解码、旧加载器和固定版本官方 4.5 processor；范围见第 5 节。** 没有处理真实拉伸视频或固定测试集，没有运行训练、真实模型测评或模型前向。合成样例及 processor 级结果均不能证明模型理解画面或时序。

## 1. 本轮身份能确定到哪里

| 对象 | 本轮状态 | 可以追溯的历史线索，不能自动当成本轮选择 |
| --- | --- | --- |
| 模型和权重 | 具体模型名单、基础权重、adapter 或合并模型身份待确认；没有本轮权重路径、摘要及实际加载记录。 | 历史 `finetune/MiniCPM/config/active/v4_1_visual/train_v4_1_visual_fold0.yaml:1-3,23-27` 写有 `../base-models/minicpmv4_5`、`template: minicpm_v` 和 `video_maxlen: 8`；这是旧 v4.1 fold 0 配置。 |
| processor、tokenizer、模型代码 | 本轮尚无经核验的实际加载目录、源码与配置摘要或版本绑定。 | 旧评测 `finetune/validation/model_runtime.py:38-96` 根据 `model_dir` 加载模型；有 `adapter_dir` 时，从 adapter 路径加载 tokenizer 和 processor，否则从模型目录加载。它使用 `trust_remote_code=True`、`local_files_only=True` 加载处理器相关文件，模型加载则见对应代码参数。 |
| 训练入口 | 新的五类标签数据、训练样本和训练配置尚未接入，不能说本轮已选择具体入口。 | 旧训练准备和契约链路进入 LlamaFactory；本次对照其 Git 子模块固定提交的 `src/llamafactory/model/loader.py:71-120`、`src/llamafactory/data/mm_plugin.py` 与历史训练配置。 |
| 推理／评测入口 | 新整体测评的运行接口、问题及记录协议尚待衔接。 | 旧 `finetune/validation/model_runtime.py:110-184` 是可追溯的旧评测入口；现有接口和旧四字段不构成本轮已完成的五类测评。 |

历史 `docs/results/minicpm-fixed-source-audit-20261016.md` 记录曾将训练机基座小文件及权重身份与官方 `openbmb/MiniCPM-V-4_5@daef484c35ec93210ec93c5e901f8f3e9b78ee34` 比对：对应 processor、tokenizer 和配置小文件以及四片权重身份有匹配证据，但训练机 `modeling_minicpmv.py` 多了 `self.post_init()`，整个目录不能称作官方原样快照。该记载不是本次训练机现场核验，也不能证明这个基座就是本轮选择或差异没有行为影响。

## 2. 可核实的历史链路

### 2.1 旧训练侧：LlamaFactory 读取视频

按固定子模块的 `src/llamafactory/data/mm_plugin.py:218-247,278-307,1211-1253,1285-1355,1375-1415` 静态追踪：

1. 训练数据提供视频文件时，`BasePlugin._regularize_videos` 用 PyAV 打开视频流。帧数已知时，根据流时长和 `video_fps` 计算 `max(1, floor(duration × video_fps))`，再受容器总帧数与 `video_maxlen` 限制；通过 `np.linspace(0, total_frames - 1, n).astype(np.int32)` 选取帧索引。视频流报告帧数为零时有单独的回退分支，不能假设所有输入的元数据可靠。
2. 按解码顺序枚举视频帧，把选中帧转为 PIL 图像；`_regularize_images` 按最大／最小像素面积等比例缩放并转换 RGB。`MiniCPMVPlugin` 将结果交给 `processor.image_processor(videos, max_slice_nums=2, ...)`，再构造视频对应的图像占位符和 `image_bound`。像素限制默认最大 `256×256`、最小 `16×16`，`video_fps` 默认 `2.0`；配置可覆盖。历史 fold 0 示例显式设 `video_maxlen=8`。默认值见子模块 `src/llamafactory/hparams/model_args.py:321-335` 和 `src/llamafactory/model/patcher.py:350-364`。
3. 该插件的视频 image processor 调用未传真实 PTS 或 `temporal_ids`。在所核查的固定 4.5 processor 实现中，未提供 `temporal_ids` 时，按图像／切片分别产生 `[-1]`；这不等于实际训练中已抓取和确认过这些张量。输入是有先后顺序的图像序列，不是显式的真实时间信息。

以上是旧代码路径和旧配置的静态结论；具体历史训练是否使用完全相同的代码、参数和 processor 仍需对应运行记录证明。帧数、采样率、大小和切片不能只从默认值推断每一次运行。

### 2.2 旧评测侧：项目自己的加载器读取视频

固定代码 `finetune/validation/video_loader.py:20-116` 和 `finetune/validation/model_runtime.py:110-184` 显示：

1. `load_video_frames` 用 PyAV 打开视频，按 PTS 读取 `[start_time, end_time)` 的帧，跳过无 PTS 的帧，转换为 RGB。默认整个视频；候选帧按解码顺序保留。随后按 `n=max(1,min(int(duration×2.0), max_frames, total))` 和 `linspace(0,total-1,n)` 选择并去重，默认 `max_frames=8`。这里的 `duration` 是整段源视频时长，即使调用者限定了较短区间，不能把它误写为所选区间时长。
2. 每帧按默认 65,536 最大像素、256 最小像素规整。调用者按同一列表顺序生成图像占位符，调用 `processor(text=..., images=frames, temporal_ids=..., max_slice_nums=2, use_image_id=False)`，去掉 processor 辅助字段 `image_sizes` 后，其余输入交给 `model.generate`。
3. 默认 `TEMPORAL_FUSION_LEGACY=False`，加载器返回 `temporal_ids=None`。若主动开启旧回退开关则返回 `[[0]*n]`，是把全部帧分成同一组且全部编号为 0，不是各帧真实 PTS。默认情况下 4.5 image processor 回填 `[-1]`；processor 在图像占位符及 `image_bound` 中仍保留图像排列。模型源码将视觉特征按这些位置放入序列；这只能说明输入组织方式，不是时序能力结论。
4. 加载器返回的 PTS 被保存在 `ModelRunResult.sampled_timestamps`，正常处理器调用并未将这些 PTS 写入问题文字或作为时间编号传入。`frame_dir` 非空时才在 processor 之前保存各张 RGB PNG 和 contact sheet；默认是 `None`。旧运行时保存的 PTS、图片与实际处理器后张量是不同层次的证据。

旧训练侧与旧评测侧都使用均匀抽样思路，也都有限制像素面积和切片数，但一个先按容器索引选帧，另一个先按 PTS 解码区间并对结果选帧。仅凭代码不能证明它们对所有视频、可变帧率、异常 PTS、短区间和不同参数抽到同一组帧。旧加载器对正时长但没有解码帧的边界也可能在索引采样时报错；这不是本轮新链路已经发生的故障。

### 2.3 旧数据采样辅助器不是模型调用证据

`pipeline/preprocessing/minicpm_preprocessor.py:336-477` 中 `MiniCPMVideoPreprocessor.sample` 用来建立候选视频的帧映射：按区间解码、计算采样位置，调用 image processor 后返回原帧号和时间戳。该辅助器选出的原始 RGB 帧直接进入 image processor，没有经过上述训练插件的像素面积规整；而且它是独立的一次采样，不天然绑定到之后某次模型调用。它不能独立证明最终模型接收了同样的像素、切片或张量。当前子视频生成代码 `script/subvideo_generation/pilot/aligned.py:402,428` 记录 `model_sampling_gate=not_run`；片段重放通过不等于已完成模型采样检查。

## 3. 为什么旧项目增加自己的抽帧

提交 `d1893ae5df9de6f61eca5f05550a6696b723c6e3`（2026-06-27）新增 `finetune/validation/video_loader.py`。提交说明明确记载：从原有预处理代码提取轻量均匀抽帧；让单样本推理返回预测及实际帧时间戳；结果与元数据分开保存；用实际采样帧时间戳计算预测时间区间。代码 diff 显示，新路径明确把 `video_path` 交给加载器，再把 `frames` 作为 `images` 送入 processor。这支持“为留存实际采样时间、衔接当时的时间区间预测而重构”的结论，不能进一步还原作者是否还出于性能、兼容性或其他原因选择独立维护加载器。

尤其要注意：该提交的父提交 `fa4f754b5c1fcde52322d79a5c144bdf800a073b` 中，同一验证函数虽然有 `video_path` 形参，并在问题中放入 `(<video>./</video>)`，函数体却没有读取这个参数，也没有向 `apply_chat_template` 传视频路径、帧或字节。调用方检查路径存在和读取旧帧映射不等于把画面交给 processor。独立核查对该函数做 AST 检查并用 spy/stub 传入两个不同路径，观察到 processor 参数相同；它不证明当时的真实 processor 或模型执行结果，也不能外推到当时其他训练／服务入口。

随后提交 `32bd5138c08a886f1d3a77fb9d4f5542134fe451`（2026-10-18）明确以对齐旧训练侧为目标，将评测默认时间组从 `[[0]*n]` 改为 `None`，增加像素规整，并将切片上限从 1 改为 2，同时保留旧融合回退。这是当时记录的目标和代码变化，不代表已对所有视频证明训练与评测完全等价。

## 4. 官方 MiniCPM-V 4.5 对照

本节以模型作者发布的 **`openbmb/MiniCPM-V-4_5@daef484c35ec93210ec93c5e901f8f3e9b78ee34`** 为固定样本，并以作者 Cookbook 的固定提交补充对照；这些版本用于取证，不代表本轮已经选用。

### 4.1 模型卡：外部 Decord 取帧并按时间组打包

[4.5 模型卡的视频示例](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/daef484c35ec93210ec93c5e901f8f3e9b78ee34/README.md#L325) 中，`encode_video` 使用 Decord `VideoReader`，以 `len(video)/average_fps` 估算时长；按时长及目标 fps 确定采样数和每组帧数，再在全体帧索引上按均匀分桶的中点取样，`get_batch` 解码为 RGB PIL 列表。函数默认 `choose_fps=3`，实际示例调用 `fps=5`；示例设置 `MAX_NUM_FRAMES=180`、`MAX_NUM_PACKING=3`，该调用的有效采样帧上限为 540，具体数量及每组帧数随时长变化。`180` 不能当作严格的组数上限：短视频分支判断时将时长取整，而计算采样数时使用未取整时长，可能略多于 180 个单帧组。即便模型卡另介绍架构可把最多 6 帧一起压缩，该示例的打包上限仍是 3。

示例以 `frame_index / average_fps` 估计每帧时间，用 `cKDTree` 对 `np.arange(0,duration,0.1)` 求最近网格并转换为整数编号，按连续帧打包；该值是从平均帧率估算并量化的位置，不应称作逐帧实际 PTS。`force_packing` 在选帧后调整分组而不重新选帧。示例将 `frames + [question]` 和 `temporal_ids` 送给 `model.chat`，并设置 `max_slice_nums=1`、`use_image_id=False`。实际 `chat` 按消息内容顺序收集图片并调用 processor；这个入口本身没有读取视频路径或解码视频。[来源：固定版本模型代码](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/daef484c35ec93210ec93c5e901f8f3e9b78ee34/modeling_minicpmv.py#L393)。

[4.5 image processor](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/daef484c35ec93210ec93c5e901f8f3e9b78ee34/image_processing_minicpmv.py#L192) 根据尺寸和 `max_slice_nums` 调整画面；目标面积约为 `448²`，宽高对齐 14 的倍数，使用双三次缩放，并非一律拉伸为 448×448。它将画面转 RGB、归一化并形成 patch。显式提供时间组时，同一组的后续帧在文本侧跳过额外图片占位符；多切片时内部输出顺序是“时间组 → 同一切片位置 → 组内帧”，并非始终“每帧的全部切片依次排列”。[processor 返回值](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/daef484c35ec93210ec93c5e901f8f3e9b78ee34/processing_minicpmv.py#L149)包括 `pixel_values`、`image_bound`、`tgt_sizes` 和 `temporal_ids`；[resampler](https://huggingface.co/openbmb/MiniCPM-V-4_5/blob/daef484c35ec93210ec93c5e901f8f3e9b78ee34/resampler.py#L172) 使用时间编号及分组组织位置编码和多帧压缩。`-1` 对应零时间位置嵌入，并不删除文本序列中已有的帧位置。

### 4.2 另一官方示例与训练指南

模型卡链接的作者 Cookbook 在固定提交 `73b3ef502209d058cc65f785d96eed23db6c8d74` 的 [4.5 视频示例](https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/73b3ef502209d058cc65f785d96eed23db6c8d74/inference/minicpm-v4_5_video_understanding.md#L25) 中，先按近 1 fps 抽候选，超过 64 帧再均匀压到 64；调用使用 `max_slice_nums=2`、`use_image_id=False`，未传 `temporal_ids`。这是另一示例，不能与上节的 5 fps／180×3／显式时间组混作同一配置。

同一 Cookbook 的 [4.5 LLaMA-Factory 指南](https://github.com/OpenSQZ/MiniCPM-V-CookBook/blob/73b3ef502209d058cc65f785d96eed23db6c8d74/finetune/llamafactory/llamafactory_minicpmv4_5.md) 给出 `<video>` 与 `videos` 路径格式及 4.5 模型名，但示例训练配置选择的是图片数据集，安装未固定 LlamaFactory 提交，文档没有确定视频抽帧及时间组算法。它不能独立证明 4.5 视频训练会采用模型卡的 Decord 打包方法。

| 比较项 | 历史训练插件 | 历史评测加载器 | 官方模型卡示例 |
| --- | --- | --- | --- |
| 读帧 | PyAV，容器索引和时长 | PyAV，先按 PTS 解码，再选帧 | Decord，先计算索引再批量解码 |
| 本次可核参数 | 默认 2 fps；旧 fold 0 上限 8 | 默认 2 fps 口径、上限 8 | 示例调用目标 5 fps；常量 `MAX_NUM_FRAMES=180`、`MAX_NUM_PACKING=3`，组数有前述取整边界 |
| 位置与时间 | 插件不传真实 PTS／时间组 | PTS 用于返回记录；默认不传 processor | 平均帧率估算时间，量化至 0.1 秒编号并分组传入 |
| 像素及切片 | 先按 65,536／256 像素面积规整，最多 2 切片 | 默认同样的像素面积规整和切片上限 | 无旧项目这一步面积规整，示例切片上限 1 |

表中仅比较各自列出的路径和配置，不保证其他调用、不同 processor 或实际训练时相同。固定模型 `config.json` 的 `version=4.5` 与 `preprocessor_config.json` 中的 `version=2.6` 是不同对象的字段，不能由后者把模型认成 2.6。模型配置中的 `transformers_version=4.51.0` 是元数据，不是兼容版本范围保证；官方示例也没有固定 Decord／SciPy 的完整依赖版本。

## 5. 已运行的受控验证

### 5.1 样例、环境和解码

在 `/private/tmp/tensile-synthetic-validation-20261110/` 生成 8 帧合成视频：160×96，4 fps、2 秒；画面只有颜色和帧编号，依次为红、绿、蓝、黄、青、品红、白、黑。使用 Pillow 生成 RGB 画面并将原始帧送入 ffmpeg 8.1.1，以 `-f rawvideo -pix_fmt rgb24 -s 160x96 -r 4 -frames:v 8 -c:v libx264 -pix_fmt yuv420p` 编码为 H.264 MP4；生成时没有记录 Python 和 Pillow 的具体版本。文件 SHA-256 `bac4e4292066e15a9181ce6c7eadaafdf05e23a0cc2135237dd0d261e9796791`。PyAV 18.0.0 实际解码 8 帧，PTS 为 0 至 1.75 秒、间隔 0.25 秒，中心颜色顺序与合成输入一致。该样例是恒定帧率的简单视频，不覆盖真实视频的压缩、色彩、PTS 或异常情况。

### 5.2 旧项目加载器实跑

使用 `/opt/miniconda3/bin/python -B`（Python 3.13.13、PyAV 18.0.0、NumPy 2.5.1、Pillow 12.3.0），只读导入原项目的 `finetune.validation.video_loader.load_video_frames`，传入上述合成视频、`max_frames=8`、`max_pixels=160*96`、`min_pixels=1`。实际返回 4 张 160×96 RGB 图片，PTS 为 `[0.0, 0.5, 1.0, 1.75]` 秒，中心颜色依次为红、蓝、青、黑；`temporal_ids=None`。这些像素阈值是为该小样例显式给出的测试参数，并非宣称历史调用使用了不同默认值。

可在保留上述临时样例和环境时复现：

```python
import sys
sys.path.insert(0, '/Users/pcoffeep/AgentPlayground/active-projects/mVllm_2')
from finetune.validation.video_loader import load_video_frames

frames, temporal_ids, timestamps = load_video_frames(
    '/private/tmp/tensile-synthetic-validation-20261110/synthetic.mp4',
    max_frames=8, max_pixels=160*96, min_pixels=1,
)
print(timestamps, temporal_ids)
print([frame.getpixel((80, 48)) for frame in frames])
```

### 5.3 官方 processor

在独立临时环境 `/private/tmp/tensile-minicpm-processor-validation-20261110/venv` 中安装依赖，未修改系统或其他项目环境。使用 Python 3.12.10、PyAV 18.0.0、NumPy 2.4.6、Pillow 11.3.0、PyTorch 2.5.1、Torchvision 0.20.1、Transformers 4.56.1；这是本次受控环境，不是已核验的训练机环境。将历史取证保存的固定官方小文件复制至临时目录并离线加载 `AutoProcessor`，没有下载或加载权重。将临时副本的 10 个非 LFS 小文件与历史取证保存的固定树 Git blob 身份比对、tokenizer 内容与该树 LFS 指针的 SHA-256 比对，11 个均匹配；这是相对于本机历史取证副本的复核。实际加载类为 `MiniCPMVProcessor`、`MiniCPMVImageProcessor` 和 `MiniCPMVTokenizerFast`；两个源码文件 SHA-256 分别为：

```text
processing_minicpmv.py       aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd
image_processing_minicpmv.py 52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7
```

同一程序再次调用旧加载器取得上节四帧，随后直接将四个图像占位符、问题文字和帧列表送入该 processor；没有调用 `model.chat`、旧完整推理入口或模型。主要实际结果如下：

| processor 调用 | 实际输出 |
| --- | --- |
| 按红、蓝、青、黑顺序；`temporal_ids=None`、`max_slice_nums=2` | 返回四个图像输入张量，每个形状 `[3,14,14350]`；`tgt_sizes` 均为 `[25,41]`；`temporal_ids=[[[-1],[-1],[-1],[-1]]]`；`image_bound` 有四组，`input_ids` 形状 `[1,269]`。 |
| 同样画面和切片设置；手工传 `[[0,5],[10,17]]` | 四个图像张量的逐项 SHA-256 与上一行相同；输出时间组为 `[[[0,5],[10,17]]]`，`image_bound` 有两组，`input_ids` 形状 `[1,137]`。这些整数是测试手工输入，不是此次视频经官方 `encode_video` 自动算出的时间编号。 |
| 同样设置、倒序输入黑、青、蓝、红；`temporal_ids=None` | 四个输出图像张量的 SHA-256 顺序与第一行完全相反；输出仍是四组 `[-1]`。这验证了这个样例在 processor 输出处的帧顺序，未测试模型对顺序的回答。 |
| 手工分组且 `max_slice_nums=1` | 对这个小尺寸样例，输出与手工分组的 `max_slice_nums=2` 相同；不能据此推断较大图像或多切片情况下两种设置等价。 |

`tgt_sizes=[25,41]` 对应该 processor 的 14 像素 patch 网格；原始 RGB 帧与这些规整后的张量不是同一层画面。运行脚本保留在临时目录 `validate.py`，SHA-256 为 `e21a5bd1fea0160707b083fee6c0c085a2b07b8fc4a98299515b606560fe4983`；同目录 `run.log` 记录依赖、输入及各输出。临时路径不构成长期归档。本试验只说明该固定 processor、这些参数和一个合成视频的实际结果。

### 5.4 仅静态可确认或未执行

没有现场检查训练机、加载模型权重、执行模型前向或生成回答；没有实跑旧训练插件、正式推理／测评入口或 Decord 官方 `encode_video`。上节直接调用了 processor，而没有验证完整推理入口的 chat template 与参数装配。视频容器元数据异常、无 PTS、可变帧率、多切片以及不同机器依赖的行为均不由这一个样例覆盖。独立审查中用假容器／假图像对旧加载器做的边界检查，仅证明该 stub 输入下的代码行为，不是对真实视频的测试。

## 6. 如何为视觉与时序测评留证

可行的证据应在**真正将数据送入目标 processor 和模型的同一次调用**处采集，而不是仅提前用另一个采样器重跑。后续协议可考虑记录：

1. 模型／adapter、processor、tokenizer、远程代码和依赖版本及摘要；视频及来源／片段身份、解码器、采样参数。
2. 输入到 processor 的每一帧：展示顺序、可追溯的原始帧索引与实际 PTS、可供人工复核的 RGB 帧或可复现的无损引用，以及进入 processor 前的缩放、裁剪和颜色处理。来源时间和展示顺序要分开记；若帧号或 PTS 无法可靠取得，应标记未知，而不是用平均 fps 冒充实测 PTS。
3. processor 调用参数、实际输出的 `temporal_ids`、图像占位符及 `image_bound`、切片／patch 对应关系、`tgt_sizes`、必要的张量形状和摘要；确认这些字段确实进入对应模型调用。切片图或解码帧截图便于人工看证据，但不能单靠一张联系表宣称完整还原视觉编码。
4. 把上述输入与问题、人工答案、模型原始回答和失败记录绑定。完整片段标签的端到端结果，与“模型实际输入是否含有足够可见证据、回答是否受其支持”并列报告；抽帧漏掉事件不是已证明模型识别失败，输入不足的样本也不能悄悄从端到端结果中移除。
5. 正序／倒序对照要核对实际图片位置确实变化，并检查时间编号、图片编号、问题文字及其他元数据是否向模型泄露原顺序；如何处理时间编号须在实验设计中明确并记录。即使记录了顺序和时间组，是否利用顺序仍需要按方案做受控对照，不能从 `temporal_ids` 的存在或缺失直接得出。

以上是核查得到的留证需求，不改变现有配置，也不确定新的记录接口或正式实验流程。`docs/design-test.md:130-146,184-198` 已要求将实际输入和人工可见证据分开记录，并保留正反顺序配对的设计边界。

## 7. 尚需核查的问题

- 明确本轮拟用的具体基础模型／版本、权重与 adapter，核对处理器、tokenizer、模型代码、实际加载路径、revision 和摘要；历史训练机代码差异应按实际目标目录重新检查。
- 在训练和推理方案确定后，分别核对真正生效的入口、框架版本、数据格式、采样参数、像素规整、截断、切片和 `temporal_ids`；对同一合成视频沿实际入口抓取 processor 前后内容，检查两侧是否真的一致。
- 如需采用 4.5 的时间打包，明确分组、时间来源、单位、可变帧率和时间戳缺失处理，以及它与顺序扰动测评的关系；这是后续待确认的方案问题，本报告不替用户选择。
- 建立本轮输入留证与人工证据审核的具体接口，明确哪些记录可以无损还原、哪些仅为摘要或估计；完成开发侧校准后再按授权开展真实材料测评。

## 8. 来源、验证和失效条件

主要本地证据为 `docs/design-test.md`、`docs/TODO.md`、`docs/migration-review-outline.md`、`docs/facts.yaml` 的 DF-016／DF-018／DF-019、历史取证 `docs/results/minicpm-fixed-source-audit-20261016.md`，以及上文标明的固定 Git 提交和源码位置。官方一手来源均已在对应论述处给出固定 revision 链接。独立 reviewer 核查了当前设计与旧调用链、历史断点和留证边界；其 stub 检查不替代真实 processor 或模型运行。

**失效条件：**本轮模型、权重、processor、加载入口、LlamaFactory 子模块、依赖版本、抽帧／画面处理或时间分组配置发生变化，或者获得新的实际运行记录时，应重新核查受影响部分。本文只记录本次静态和受控验证证据，不作为未来训练或模型效果验收证明。
