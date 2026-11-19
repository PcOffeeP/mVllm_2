# 源视频人工标注工具

本工具从原项目 `mVllm_2` 的 `2c272ce（原项目 main；工具四个文件与 5113c14 一致）` 迁入，包含启动器、本地服务和页面；为适应新位置调整了项目根目录定位。标签含义以项目的 `docs/label.md` 为准。

在 macOS 双击 `review_run_annotation.command`，或运行 `python3 script/annotation/review_run_annotation.py`。需要 Python 3.10 及以上，以及 PATH 中支持 `fd` 输入协议的 ffmpeg、ffprobe。

默认标注表为 `data/annotation-table-full.csv`，默认视频目录为 `data/videos`；均相对项目根目录解析，与当前工作目录无关。缺失时终端与页面会给出中文提示，请在页面填写实际路径。保存会写入所选标注表。

**重标注前必须先备份 CSV**，例如从项目根目录执行以下命令，备份目录不得建在仓库内：

```bash
mkdir -p ~/pi-workspace/annotation-backup && cp -p data/annotation-table-full.csv ~/pi-workspace/annotation-backup/annotation-table-full-$(date +%Y%m%d-%H%M%S).csv
```

测试使用临时合成数据，运行 `python3 -m pytest -q script/annotation/tests/test_review_run_annotation.py`。通过测试不代表真实长视频、所有页面控件或模型数据链路已经验收。

**失效条件：**工具入口、依赖、默认路径或本说明所述迁移范围发生变化时，应更新本说明。
