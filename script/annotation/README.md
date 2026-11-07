# 源视频人工标注工具

本工具从原项目 `mVllm_2` 的 `2c272ce（原项目 main；工具四个文件与 5113c14 一致）` 迁入，包含启动器、本地服务和页面；为适应新位置调整了项目根目录定位。标签含义以项目的 `docs/label.md` 为准。

在 macOS 双击 `review_run_annotation.command`，或运行 `python3 script/annotation/review_run_annotation.py`。需要 Python 3.10 及以上，以及 PATH 中支持 `fd` 输入协议的 ffmpeg、ffprobe。

默认仍读取项目根目录下的 `data/annotation/annotation-table-full.csv` 和 `data/source/videos`。本轮成果在 `data/v2/`，如需查看或标注，请在页面中自行选择对应表格和视频目录；保存会写入所选标注表，操作前请确认路径并保留备份。此次迁移未使用或修改真实标注数据。

测试使用临时合成数据，运行 `python3 -m pytest -q script/annotation/tests/test_review_run_annotation.py`。通过测试不代表真实长视频、所有页面控件或模型数据链路已经验收。

**失效条件：**工具入口、依赖、默认路径或本说明所述迁移范围发生变化时，应更新本说明。
