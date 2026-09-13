<!-- DOCUMENT-CONTRACT
Purpose: 索引项目环境部署与模型管理脚本的入口及安全边界。
Scope: scripts目录中的直接入口、安装前提和部署检查。
Must Preserve:
- 安装只写显式新环境；环境检查不启动模型训练或推理。
- 旧模型管理入口仍受项目授权与新旧体系边界约束。
Non-goals:
- 不代替模型训练、晋级或删除授权。
-->

# 脚本入口

| 脚本 | 用途 |
| --- | --- |
| source_prepare_environment.py | 按mac/linux-gpu锁定依赖安装到新环境，随后调用doctor |
| source_validate_environment.py | 检查依赖、公共CLI、媒体工具；Linux检查CUDA及训练模块来源，不加载模型 |
| serve_manage_checkpoints.py | checkpoint管理，删除须按项目授权 |
| serve_manage_model_registry.py | 模型库历史管理；活动入口以versioning为准 |
| serve_validate_no_oob.py | 模型交付边界检查 |
| serve_validate_delivery.py | 交付文件检查 |

## 新环境部署

在项目根目录执行。预先安装Python 3.11、uv、Git、ffmpeg和ffprobe；Linux GPU还需可用NVIDIA驱动，初始化并保持LlamaFactory子模块与Git记录一致。脚本不安装系统工具或改动现有Conda环境。

```sh
python3 scripts/source_prepare_environment.py --profile mac \
  --env /absolute/new/environment --python /absolute/python3.11
# 训练机执行，目标仍须不存在：
python3 scripts/source_prepare_environment.py --profile linux-gpu \
  --env /absolute/new/environment --python /absolute/python3.11
```

Mac使用pyproject.toml/uv.lock（包含dev组）；Linux x86_64 GPU使用requirements-linux-gpu.lock及当前固定LlamaFactory子模块。requirements.txt是Linux锁文件输入；不把Mac和GPU配置叠加安装。安装失败返回非零并保留部分环境以便调查；重试须选择新目标，不自动清空已有目录。成功后用目标环境bin/python运行项目，不依赖当前shell激活的环境。

```sh
/absolute/new/environment/bin/python scripts/source_validate_environment.py --profile mac
# Linux环境选择 --profile linux-gpu
```

doctor输出JSON到stdout，不创建版本、Run或模型。缺工具、包冲突、入口导入失败或GPU训练模块来源不符返回非零。环境检查通过不表示基座模型已下载、实际训练可完成、模型质量passed或备份恢复完成。

维护者更新依赖时分别运行`uv lock`和`uv pip compile requirements.txt --python-version 3.11 --python-platform x86_64-manylinux_2_28 --output-file requirements-linux-gpu.lock`，再在对应机器的新环境验证。
