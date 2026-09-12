# 迁移证据：训练机只读调研与完整 payload hash 验证

任务：`2026-09-07-readable-version-control-migration` · M0 证据固化
本文件记录训练机只读调研与两个 legacy data release 的完整 payload hash 验证证据。
只记录已核实事实；不定义迁移行为契约，不判定真实迁移写入已完成。

## 1. 训练机只读调研

- 训练机主机名：`dell-Precision-3660`
- 远程项目路径：`/home/liuyang/文档/mVllm_2`
- 远程 HEAD：`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`
- 远程工作区状态：干净（clean）
- 命令类型：SSH 只读命令；目录检查采用有限深度 `find`/`ls`；文件大小与软链接检查不读取权重内容；Git 状态、活动指针与少量身份元数据被读取。
- 退出状态：只读调研命令均成功返回（exit 0）；初次连接超时，用户恢复 Tailscale 后调查成功。
- 限制：未读取受限测试真值与逐样本语义结果；未执行训练、推理、权重哈希或远端写入。

## 2. 两个 legacy data release 存在性与结构

| release | 路径 | 结构 |
| --- | --- | --- |
| r1 | `workspace/data/releases/v4.1.0-760050fad303` | 存在且结构完整 |
| r2 | `workspace/data/releases/v4.1.0-ecb5aeb9657c` | 存在且结构完整 |

- manifest schema 完整：`path` / `sha256` / `size_bytes` 均无缺失。
- 无 unsafe paths；无 symlink。

## 3. 完整 payload hash 验证

对两个 release 的 manifest 声明文件逐一做 SHA-256 校验，结果如下。

| release | 声明文件数 | 总字节数 | 全部 SHA-256 匹配 | manifest sha256 |
| --- | --- | --- | --- | --- |
| r1 `v4.1.0-760050fad303` | 9 | 9,819,900 | 是 | `c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036` |
| r2 `v4.1.0-ecb5aeb9657c` | 11 | 13,743,509 | 是 | `ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b` |

- 无缺失文件、无未声明文件、无 hash mismatch。
- 校验命令退出状态：成功（exit 0）。

## 4. 活动指针验证

- `finetune/active_data_release.json` 指向 r2（`v4.1.0-ecb5aeb9657c`）。
- `expected_manifest_sha256` 与实际 manifest SHA-256 完全一致（`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`）。

## 5. Q4 数据根选择与准备（用户确认）

- 用户已确认 Q4 数据根选择 A：`/data/mVllm_2`。
- 目录准备由用户手动 sudo 完成：
  - `sudo mkdir -p /data/mVllm_2`
  - `sudo chown -R liuyang:liuyang /data/mVllm_2`
- 随后以只读 SSH 验证（exit 0）：
  - `ls -ld /data/mVllm_2 && test -w /data/mVllm_2 && test -x /data/mVllm_2`
  - 输出：`drwxr-xr-x 2 liuyang liuyang 4096 9月 9 09:45 /data/mVllm_2`
- 结论：`/data/mVllm_2` 存在、属主正确、可写、可进入。
- 限制：真实迁移写入仍未执行；receipt 具体实现仍待 TDD；模型/run/训练/评测仍未验证。

## 6. 未执行项（明确保留）

- 本机与训练机均未执行真实迁移写入、训练、评测、push/merge。
- 凭证（receipt）的具体格式/存储位置仍待实现确认；未裁决凭证格式/位置。
- 模型/训练/run 的权重完整性与哈希仍未验证（本文件仅覆盖两个 data release 的 payload hash）。

## 7. coverage-first seed3407 merged 软链接来源链

2026-09-11 经用户授权，对训练机执行只读 SSH 核查（无文件写入、同步、训练、推理或权重哈希）：

- run：`workspace/runs/v4.1-phase2-coverage-first-v1-seed3407/fold0`
- `merged` 链接文本：`../../../models/releases/v4.1-agent-pipeline-fold0-r1/merged`
- 解析目标：`workspace/models/releases/v4.1-agent-pipeline-fold0-r1/merged`
- 目标目录存在 10 个顶层 `model-*-of-00010.safetensors` 分片；本轮只核对文件类型、名称与大小，未读取或复算权重内容哈希。
- `fold0/model_identity.json` 声明同一 `model_name`、当前 run 的 `merged_path`；`source_adapter_path` 与 `source_merged_path` 是同一 LlamaFactory 来源对（后者严格为前者加 `_merged`），共同带有实验 ID 与 seed3407。
- `pipeline/model_registry/releases/v4.1-agent-pipeline-fold0-r1.json` 与发布目录内 `release-manifest.json` 字节 SHA-256 均为 `3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`，内容完全一致。
- release manifest 的 `origin.experiment_id` 与上述来源目录名精确对应，并绑定 coverage-first、release `v4.1.0-ecb5aeb9657c`、fold 0、seed 3407；adapter/merged 的 `path_at_freeze` 分别与 identity 来源路径一致，`artifacts.merged.managed_path` 与链接解析目标一致，并声明 10 个分片。
- 对 run、fold0、identity、adapter、Registry manifest、发布目录 manifest 和 managed merged 目标从仓库根逐级执行 `lstat`；各级均为普通目录/文件，只有声明的 `fold0/merged` 是预期软链接，发布目录顶层权重分片也不是软链接。
- 结论：该 run 的 merged 链接来源链在路径、run 本地身份、Registry manifest 和发布目录 manifest 四层一致，可作为“观察到权重存在”的来源证据；这不证明权重内容哈希、可加载性、训练完成或质量通过。
- 远端核查基线仍为干净 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。

## 8. 关键 hash 汇总

- r1 manifest sha256：`c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`
- r2 manifest sha256：`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`
- coverage-first seed3407 model identity sha256：`83cc641cdb441cb3766694fe1916da3d4d3325009409df3edab565528020ef5b`
- `v4.1-agent-pipeline-fold0-r1` Registry / release manifest sha256：`3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`
- 远程 HEAD：`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`

## 9. 历史训练参数证据边界

- H9 只从 `docs/results/model_evidence/<run_id>/MANIFEST.json` 声明且经 size/SHA-256 验证的文件提取参数；归档包身份、schema、run seed 和三层 epoch 证据必须一致。
- 当前可提取字段为 seed、epochs、effective batch size、LoRA rank、LoRA alpha、LoRA target modules；每个字段分别记录实际取值文件和交叉验证文件。
- LoRA 参数取自声明 run 的 `adapter_config.json`，并以归档 MANIFEST 中记录的 size/SHA-256 验证；归档目录本身没有该文件副本。epochs/effective batch 由归档 training manifest、trainer state 和包摘要交叉核对。
- learning rate、optimizer、precision 继续保持字段级 unknown：现有证据包未提供足够稳定的历史执行配置链，当前 active 配置可能已漂移，不得据此反推。
- 训练机现有 `main@f1b7d8a3` 不含 `docs/results/model_evidence`，M2 因此在训练机临时目录组合隔离分支的真实归档与现有工作区的真实 run 文件：归档文件复制到临时根，adapter config 及代表性 adapter/merged 权重以同文件系统硬链接只读引用。四个 phase2 run 的端到端 CLI 构建均成功，临时根退出后删除；未修改现有 main 或正式对象。

## 10. M2 训练机隔离验证授权与预检

2026-09-11，用户明确授权以 M1 基线 `7eeb93a792d023c7f250f56157ae3128ac583ec2` 推进 M2 训练机隔离验证。授权范围与精确目标如下：

- bundle：`/home/liuyang/文档/mvllm2-migration-7eeb93a7.bundle`
- 隔离 checkout：`/home/liuyang/文档/mVllm_2-migration-7eeb93a7`
- 允许：创建并传输上述 bundle、创建上述隔离 checkout、在隔离 checkout 内创建项目级环境、执行非 GPU 测试、只读 precheck、Linux 文件锁验证，以及小规模 DVC/MLflow restore smoke。
- 不允许：正式迁移写入、修改训练机现有 `main` 工作区、停止进程、修改系统权限或系统级依赖、训练、GPU 推理、完整评测、push 或 merge。

执行前只读预检（exit 0）：

- 本机为 `refactor/2026-09-07-readable-version-control-migration@7eeb93a7`；除未跟踪交接文件外无修改。
- 训练机现有项目保持干净 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。
- 上述 bundle 与隔离 checkout 路径均不存在。
- `/home` 可用约 395 GiB，`/data` 可用约 3.4 TiB。

本节只记录授权和执行前状态；bundle 校验、隔离 checkout、环境与 smoke 结果将在实际完成后追加。

### 10.1 首次同步与 Linux RED

- 本机生成完整历史 bundle，分支引用精确指向 `7eeb93a792d023c7f250f56157ae3128ac583ec2`；本机与训练机 SHA-256 均为 `6a6ebd9944256deddf08e12a0c4f58de720f2e2eb4896e11719cd73d993396e2`，训练机仓库上下文中的 `git bundle verify` 通过。
- 隔离 checkout 已从该 bundle 创建，分支为 `refactor/2026-09-07-readable-version-control-migration`，HEAD 为 `7eeb93a7`；除项目级环境目录外无修改。原有项目继续保持干净 `main@f1b7d8a3`。
- `/data/mVllm_2` 属主为 `liuyang:liuyang` 且可读、可写、可进入；设计目标 `/data/mVllm_2/dvc-remote` 与 `/data/mVllm_2/mlflow` 尚不存在。本轮未创建二者，smoke 继续使用临时目录。
- 隔离 checkout 内创建 `.conda-m2` 项目级环境；Python 3.11.16。训练机没有可用的已跟踪 `uv.lock`（仓库 `.gitignore` 排除该文件），因此未生成或伪称冻结同步；改按本机既有锁定事实显式安装 DVC 3.67.1、MLflow 3.15.2、pandas 3.0.3、pytest 9.1.1、PyYAML 6.0.3。
- 普通 pip 解析正确拒绝 MLflow 3.15.2 声明的 `pandas<3` 与 pandas 3.0.3 冲突；随后按项目 `pyproject.toml` 的 uv override 机制安装成功。该组合仍须以真实 SQLite/artifact smoke 验证，不能只凭安装成功判定兼容。
- 首轮 Linux `test_cli.py + test_migration.py`：236 passed、1 failed。失败用例 `test_write_history_summary_detects_temporary_source_replacement` 证明 H12 在 hard-link 前关闭最后一个临时源 FD 后，Linux 可立即复用 inode，使仅比较 `(st_dev, st_ino)` 的替换检测失效。
- 本机最小修复保持原临时 inode 的复制 FD 直到发布校验结束。独立 reviewer 三轮先后发现并闭环 2 个 P2 与 1 个 P3：双故障清理可掩盖原发布异常并泄漏复制 FD 与目录 FD；回滚所有权 `stat` 失败有同类问题；回滚目录 `fsync` 失败被静默吞掉。最终所有回滚、临时清理和两个 FD 关闭均被独立尝试，原异常保持主异常，次级清理错误附注于原异常；新增四类双故障回归，相关 8 例与完整 `test_migration.py` 191 例均通过，reviewer 终审无剩余 P0–P3。该修复须以提交对象增量同步后在训练机复跑；在此之前 M2 不判定通过。

### 10.2 Linux 修复增量同步路径

- 修复提交：`c4b53d08`（完整提交值在 bundle 校验时记录）。
- 新增增量 bundle 精确路径：`/home/liuyang/文档/mvllm2-migration-c4b53d08.bundle`。
- 该 bundle 只用于把已提交修复对象安全获取到既有隔离 checkout；不覆盖首次完整 bundle，不创建第二个 checkout，不修改训练机现有 main。

### 10.3 M2 隔离验证结果

- 增量 bundle 完整提交为 `c4b53d08c14de6859a5143062fcc526ab214eb7f`，前置提交为 `7eeb93a792d023c7f250f56157ae3128ac583ec2`；本机与训练机 SHA-256 均为 `f68533c6720aec04f299dc637f7d32d0d5329998b8c91f65fcf9542c2c12a95b`，训练机 `git bundle verify` 通过。既有隔离 checkout 已 fast-forward 到该提交。
- Linux 复验 `tests/versioning/test_cli.py + tests/versioning/test_migration.py` 为 **241 passed**，正常退出；首次暴露的临时 inode 复用失败及新增四类双故障清理回归均通过。
- 跨进程 `fcntl.flock` smoke 验证：父进程持有排他锁时子进程非阻塞获取被拒绝，释放后同一子进程逻辑可获取。只读权限 smoke 验证：`0444` 文件的独立子进程写入得到 `PermissionError`，原字节保持不变。
- DVC 小对象恢复用例 `TestDvcRemoteRecovery::test_push_delete_pull_restores_outputs` 为 **1 passed**：临时本地 remote push 后删除本地 cache/output，再 pull 可恢复输出及哈希，release manifest 未被改写。
- MLflow/SQLite 与 artifact 联合灾备用例 `TestRestoreBackup::test_restore_disaster_recovery_reopens_everything` 为 **1 passed**：删除临时原对象后联合恢复，registry/train/eval、SQLite 和 artifact 均可重新打开与读取。该结果证明锁定依赖组合可运行小规模恢复，不等同于真实移动硬盘恢复。
- H9 真实成功路径：四个 phase2 run（source-aware seed 3407/3411、coverage-first seed 3411、coverage-fallback seed 3413）均从 size/SHA-256 保护的真实归档与声明 run 的真实 adapter config 提取 seed、epochs、effective batch size、LoRA rank/alpha/targets；learning rate、optimizer、precision 继续保持 unknown。临时组合根只使用复制的小型归档与真实文件硬链接，未复制大权重、未写入正式对象。
- H11 真实成功路径：隔离 checkout 中 1 个 model manifest 与 5 个 eval 归档经 CLI 构建成功，全部保持 `history_only: true`、`formal_identity: none`，无 `passed`；构建前后工作区状态一致。
- 最终边界核对：隔离 checkout 为任务分支 `c4b53d08`，仅有未跟踪项目环境 `.conda-m2/`；现有训练机项目仍为干净 `main@f1b7d8a3`。`/data/mVllm_2/dvc-remote` 与 `/data/mVllm_2/mlflow` 仍不存在，本轮未创建；未执行正式迁移写入、训练、GPU 推理、完整评测、push 或 merge。

据此，M2 的隔离环境、Linux 行为、依赖兼容、小对象恢复与 H9/H11 真实只读成功路径已完成。正式 store 建立、真实移动硬盘恢复和迁移对象写入属于后续阶段，不能由本节结果替代。

## 11. 本机、Codeup 与训练机隔离分支同步

2026-09-11，用户要求暂停 M3，只把同名任务分支安全同步为一条线性历史，并明确授权本机向 Codeup 推送及训练机隔离 checkout 从 Codeup 仅快进。本次不涉及 `main`、正式迁移对象或 M3 实现。

同步前只读核对：

- 本机位于 `refactor/2026-09-07-readable-version-control-migration@93847d9fc713925daa5df65c900e5efb5a7c3e36`，只有未跟踪的 `docs/tasks/2026-09-07-readable-version-control-migration/agent-handoff.md`。
- Codeup `main` 为 `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，尚无同名任务分支。
- 训练机正式工作区为干净 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`；隔离 checkout 为任务分支 `c4b53d08c14de6859a5143062fcc526ab214eb7f`，只有未跟踪 `.conda-m2/`。
- `c4b53d08` 是本机 `93847d9f` 的祖先，双方独有提交计数为 `0/2`；训练机没有本机不具备的提交，Codeup 也没有意外任务分支提交。

执行记录：

- 本机使用显式 remote `codeup` 与完整同名 refspec 首次推送，Codeup 回查任务分支为 `93847d9fc713925daa5df65c900e5efb5a7c3e36`，`main` 未变；未向 GitHub 推送。
- 训练机隔离 checkout 保留 bundle `origin`，新增 `codeup` remote 指向 `git@codeup.aliyun.com:61fa7f5774c3f3b55074132e/mVllm_2.git`；显式 fetch 后再次确认 ahead/behind 为 `0/2`，随后通过 `pull --ff-only --no-tags` 快进到 `93847d9f`，并把 upstream 设置为 Codeup 同名任务分支。
- 首次 fetch 按 Git 默认 tag-following 行为额外取得已有标签 `tensile-vlm-v2-final`；未修改该标签，也不影响任务分支、`main` 或工作树。后续 pull 显式使用 `--no-tags`。
- 本节与项目台账作为唯一同步记录提交后，再按相同显式 refspec 推送该文档提交，并在训练机隔离 checkout 中再次 fetch 与仅快进；最终三端完整 SHA 以提交后的只读 refs 核对为准。

全程未执行 force push、rebase、reset、cherry-pick、clean、分支删除或 `main` merge；两端既有未跟踪文件不暂存、不删除、不修改。

## 12. M3a：显式输入契约的只读加载门

2026-09-12 按用户已确认的 M3 方案继续本地实施。本机恢复基线为
`2027c4dc14753971bf499d9b65ede6bbf650222f`；只读 `git ls-remote` 核对 Codeup
同名任务分支一致，Codeup main 仍为 `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。
Intent/Spec/Plan 最新确认提交分别为 `3dae30a0` / `6996d35d` / `11e54b31`。
本轮没有连接训练机；训练机状态沿用第 11 节前序证据，未冒充本轮复查。

首个切片仅新增 `versioning.data_pipeline.load_data_inputs(path, batch=...)`
及不可变输入记录，供后续 `--inputs` 接线使用。它是只读加载门，不是第八个公共阶段；
现有七阶段 CLI、DVC、legacy 公共入口尚未切换。

输入 envelope 使用 `schema: tensile-data/inputs/v1`，字段为：

- `batch`：必须与调用批次一致；`project_root`：显式存在的绝对项目目录。
- `source.videos`：非空列表，每项含唯一 `video_id` 和文件 pin；ID 与
  `video_NNNN.mp4` 文件名绑定，沿用现有 source 输入规范。
- `source.annotations.tags` / `mapping`：两份源注释表的显式文件 pin，
  分别供后续 source 适配读取标签与视频来源映射。
- `split` / `roi_decisions` / `contract`：显式划分、ROI 决定与业务契约文件 pin。
- `media.config` 与 `media.preprocessor.{kind,config}`：显式媒体配置、
  请求使用的预处理器名称及其配置文件 pin；实际支持性与运行时 fingerprint 由媒体适配层复核。

每个 pin 精确包含 `path` / `size_bytes` / `sha256`，路径相对上述项目目录，
拒绝绝对路径、穿越、符号链接、非普通文件及缺失文件；size 为非负整数（拒绝布尔值），
SHA-256 为完整小写摘要。所有字段完整且无额外项，YAML 全层级重复键、alias/merge、
非字符串键均拒绝。文件流式计算 size/SHA，加载结果保存输入 YAML 自身摘要及显式依赖清单。
摘要仅作内容校验，不生成任何版本身份或活动指针。

验证分层与限制：加载门只验证 envelope、路径与字节完整性；文件内部的业务 schema、
视频/注释/split/ROI 全集与交叉引用、预处理器实际行为均留给对应业务适配切片。
加载成功不表示已冻结可发布数据，也不提供并发锁；实际消费前仍须复核 pins。
返回的 `dependencies` 只列输入，后续 DVC 接线仍须加入实际实现代码。
所有测试使用本机临时非正式 fixture，没有媒体探测、GPU 操作或正式迁移写入。

TDD 的有效 RED：先提供可导入的空加载入口，运行
`.venv/bin/python -m pytest -q tests/versioning/test_data_pipeline.py -k 'TestPinnedDataInputs and required_fields'`，
8 个缺字段断言均以 `DID NOT RAISE StageInputError` 失败，exit 1；不是导入或 fixture 错误。
最小实现后，
`.venv/bin/python -m pytest -q tests/versioning/test_data_pipeline.py -k TestPinnedDataInputs --disable-warnings`
为 **61 passed**，exit 0。测试覆盖所有输入角色的内容漂移、同长度摘要漂移、
错误批次/路径/字段类型、重复视频、预处理器无显式名称，以及成功加载时禁止创建目录、写文件或启动子进程。
权威完整回归 `.venv/bin/python -m pytest -q tests/versioning --disable-warnings`
为 **1690 passed，287 warnings，317.12 秒，exit 0**，已等待进程正常退出。
本机临时原始日志为 `/tmp/mvllm2-m3-inputs-pytest.log`（非持久证据；本节保存命令和结果）。
已知 pytest 临时只读目录清理 warning 仍出现，未导致失败。

独立 reviewer 对本切片代码、测试、TODO 与本节记录审查通过，无可执行 finding。
reviewer 独立复跑输入专项 **61 passed，exit 0**，并用临时 fixture 验证父目录链接逃逸、
含 `..` 的路径、视频额外字段与深层重复键均被拒绝；未复跑完整套件或历史 RED。
代码版本可从本节与 `versioning/data_pipeline.py` 的同次提交追溯（`git log --` 对应文件），
恢复基线 `2027c4dc` 不是本切片修复版本。

M3a 本地加载门切片已完成；M3 仍进行中。下一步接真实 source snapshot+split 与
`--inputs` CLI，禁止将有效 inputs 交给现有简化产物路径后宣称真实业务已接入。

## 13. M3b：真实 source 与显式 split 快照

2026-09-12 继续 M3。新增 `run_input_source`：逐项读取 inputs 指定的视频、tags 与
mapping 表，核对 ID 全集/重复/来源字段；复用 `pipeline.source_bootstrap._governed_record`
生成实际标签治理记录和冲突说明。视频属性由实际 `probe_video` 获取，测试使用显式替身。
不调用 legacy source builder、split 重新生成器或发布器。

`split` pin 指向 `tensile-data/split-inputs/v1` 描述文件，精确字段为 `schema`、`batch`、
`source_sha256`（全部视频 ID 到摘要）和 `splits`。后者含 `test` 以及三个 fold 的
`train`/`val` 视频 ID 列表；逐 fold 拒绝 train/val/test 交叉、未知/重复/遗漏 source，
保持显式给定的成员列表，不重新计算划分。该描述文件是输入配置，不是新版本身份。

source 阶段输出在显式 store 下 `data/working/<batch>/source/`，包含字节验签后的视频、
原始两份注释表、输入 split 描述、七份 split 成员文件、带真实媒体属性/治理记录的
`source_manifest.json`，以及完整阶段文件清单 `stage_manifest.json`。
阶段发布采用同阶段文件锁、临时目录完整构建、输入再次验签和最终目录发布；现存结果
先核对输入/阶段身份、全文件 size/SHA 与本次 source 内容，冲突时停止，不覆盖现存快照。
失败的临时副本不会成为下游可用快照。

本切片尚未接公共 CLI，后续真实 ROI/子视频/审查/发布接完后统一切换入口，避免有效
inputs 继续落入旧最小数据链。没有正式对象迁移或训练机操作。

TDD：先提供可导入的空 source 入口，七个非法 split 测试均以
`DID NOT RAISE StageInputError` 失败（exit 1）。实现后
`.venv/bin/python -m pytest -q tests/versioning/test_data_pipeline.py -k TestInputSource --disable-warnings`
首轮为 **16 passed，exit 0**。独立 reviewer 以真实 flock 争用发现 1 个 P2：
等待锁期间输入漂移时仍可复用既有快照。补入锁内再次验签，先以同场景测试取得有效 RED，
修复后专项 **17 passed**，reviewer 独立重现确认抛出 StageInputError 且旧快照字节不变，终审通过。

最终权威命令 `.venv/bin/python -m pytest -q tests/versioning --disable-warnings`
为 **1707 passed，291 warnings，690.57 秒，exit 0**，已等到进程正常退出。
临时原始日志 `/tmp/mvllm2-m3-source-final-pytest.log`；本节保留持久摘要。
先前未包含锁等待修复的回归为 1706 passed，不能冒充最终代码验证。
该回归进程在后续 ROI/子视频增量开始前已经完成 collection/模块加载；source 代码和测试
按已审查暂存快照独立提交，后续增量不混入本切片，也不由本结果宣称通过。
M3b 已完成本地 source 适配；真实媒体、CLI 和其余阶段仍待完成。

## 14. M3c：冻结 ROI 与真实裁剪适配

2026-09-12 本机新增 `run_input_roi`，完整绑定 source 快照、冻结人工决定、原视频路径/摘要/分辨率、几何和审查时间。复用 legacy 的决定校验、几何 filter、ffmpeg 命令与时间轴门禁，不调用旧发布器。输出 ROI 媒体、保留标签治理的记录、冻结决定和完整阶段清单；阶段锁内及发布前递归复验上游，失败不发布半成品。

非法决定测试先取得行为 RED；锁等待期间上游漂移测试取得 RED 后修复。独立 reviewer 发现非有限 duration 可绕过旧时间轴比较，补入正有限时长、正整数帧数/分辨率及帧率校验，并禁止 JSON NaN；NaN 回归 RED 后通过。ROI 定向18 passed，source+ROI35 passed；reviewer 独立复验131 passed（不含子视频），最终无可执行 finding。

完整权威测试在 `6403400e` 的独立本机 detached worktree 上，仅叠加本 ROI 代码与测试，未包含后续子视频/审查/发布增量：`.venv/bin/python -m pytest -q tests/versioning --basetemp /tmp/mvllm2-roi-proof-20260912`，使用主工作区的同一虚拟环境解释器；**1725 passed，484.94 秒，exit 0**。临时日志 `/tmp/mvllm2-m3-roi-full-pytest.log`。本次提交的两个代码文件与被测快照逐字相同。

媒体执行、探测均为本机显式替身；没有训练机真实 ffmpeg/采样对照、正式对象迁移或 CLI 切换证据。M3 仍进行中。

## 15. M3d：真实候选规划、子视频与实际采样

2026-09-12 接入显式候选契约、development/test 历史参考、MiniCPM 配置和逐文件预处理器 pins；只调用既有纯候选规划、裁剪命令、媒体门禁和真实采样映射。两个 scope 都生成媒体与模型采样帧，并逐项保留成功或排除原因。实际 AutoProcessor 仅从显式文件快照加载，拒绝外部 auto_map、缺失动态模块及相对依赖。内部临时包名按执行唯一，避免同进程缓存复用不同批次代码，不进入版本身份。

初始8项定向通过；独立 reviewer 发现 test_audit 未物化、外部 auto_map 绕过 pins 两个P2，3项新增断言先RED后修复。复审再发现固定临时包名导致旧helper缓存复用，新增双执行隔离测试先RED后修复。最终专项12 passed；reviewer用Transformers4.56.1官方加载函数最小复现验证两份helper独立生效，终审无可执行finding。本机没有Transformers，未宣称实际AutoProcessor加载通过。

独立本机 detached worktree 基于 `3d396988`，仅叠加本子视频切片；权威命令使用同一`.venv`解释器执行 `-m pytest -q tests/versioning --basetemp /tmp/mvllm2-subvideo-proof-20260912`，**1737 passed，323.83秒，exit0**。暂存代码与该快照逐字一致。临时日志`/tmp/mvllm2-m3-subvideo-full-pytest.log`，不含后续审查/发布/界面/CLI增量。

所有媒体和预处理器测试仍为本机替身；真实训练机小样本/完整MiniCPM加载/双机审查和两个正式release迁移尚待执行，M3未完成。

## 16. M3e：可携媒体的完整人工审查回收

2026-09-12 新增 review_export/import 真实适配。开发候选按既有 v4.1 提案选择进入人工队列（包括韧性临界未断裂），普通稳定负例保留自动路径；test_audit不进入开发集审查包。导出包包含相对路径视频/模型采样帧、冻结契约、历史建议和完整候选清单。回收逐项绑定 batch、inputs、导出包SHA、源视频、媒体SHA、实际时间戳、系统建议、历史参考及规范化标签；必须完整终态且有审查者/含时区时间，丢弃/重生成必须有说明。旧包、缺项、追加及不同有效结果均拒绝，原冻结文件不覆盖。

空输出stub取得有效RED，定向12 passed。独立 reviewer 对12项及非空历史参考、额外身份/时间/状态边界、同结果重复和不同有效结果冲突进行复验，无可执行finding；另验证incipient纯提案语义。后续UI不属于本切片证据。

本机独立 detached worktree 基于 `e11b9379`，仅叠加本切片，完整`tests/versioning` **1749 passed，335.81秒，exit0**；同一虚拟环境解释器，`--basetemp /tmp/mvllm2-human-proof-20260912`。提交代码与被测快照逐字一致。临时日志`/tmp/mvllm2-m3-human-full-pytest.log`。媒体与审查记录为明确fixture，尚无真实媒体播放、真实人工决定或跨机传输证据，M3仍进行中。

## 17. M3f：真实开发集发布与封存校验

2026-09-12 新增真实 release/validate 适配。只取 development 候选，人工决定保留有效标签及丢弃原因，未审自动准入严格限定普通稳定未断裂。使用既有数据行生成规则形成六份fold数据集和dataset_info，保留冻结source划分，复制视频与实际帧，输出契约/审查/质量计数及完整payload文件清单。完整版本必须与业务协议一致，经逐文件复制校验后封存；版本已存在立即冲突，中断staging保留并拒绝不明恢复。validate只读检查完整内容、元数据、封存权限和训练准入。

初始3项取得有效RED后实现；reviewer发现协议字段、正式目录链接和payload根额外stage_manifest漏检，补入3项RED并修复。另增加同名版本冲突RED/修复。复审发现等待版本锁期间集合路径变化可在错误位置写入，新增RED后在锁内、阶段转换前重查路径，DVC前先完整校验。最终8项定向通过；reviewer独立复验错误目录保持为空且DVC不调用，原问题全部关闭。

本机独立detached worktree基于`c66b5228`，仅叠加发布切片，完整`tests/versioning` **1757 passed，359.36秒，exit0**，`--basetemp /tmp/mvllm2-release-proof-20260912`，同一项目虚拟环境解释器。代码与被测快照逐字一致；临时日志`/tmp/mvllm2-m3-release-full-pytest.log`。不含后续UI/CLI/DVC接线增量。本切片媒体与人工记录为fixture，没有正式数据迁移；DVC调用顺序由reviewer替身核查，真实DVC集成另随入口接线验收。
