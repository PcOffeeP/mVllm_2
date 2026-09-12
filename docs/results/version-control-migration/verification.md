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

## 18. M3g：可携审查包的现有界面接入

2026-09-12 现有 review_candidates_app 新增显式 `--versioning-package` 模式，必须指定真实reviewer-id、包外draft和output-root，不接受局部候选选择；legacy `--queue` 分支保持原样。新模式打开/保存/冻结时验签整包，沿用模型采样帧优先的呈现与标签确认。草稿持久化为独立review-draft envelope，完整结果为review-return；冻结文件不能被草稿接口覆写，规范化后的输出路径不能落在包内。

包加载/媒体漂移先取得2项RED；局部limit=0绕过另取得RED后修复。reviewer发现草稿覆盖冻结文件及含`..`路径可写入包内两个P2，均补RED/修复；5项专项通过，reviewer以新进程验证角色持久化、冻结字节保留和包inventory不变，终审通过。既有UI媒体helper独立1项通过。

主Agent另用Streamlit AppTest完成完整fixture界面操作：打开包、逐条批准、草稿保存、完整冻结及统一import，**1 passed**。该用例帧为2×2测试图片、视频为媒体替身，仅证明交互/数据绑定，不证明真实画面或播放。没有代替实际审查者作真人决定。

独立本机detached worktree基于`aea0e1e2`，仅叠加本UI切片及相关测试，完整`tests/versioning` **1763 passed，397.23秒，exit0**，同一虚拟环境解释器，`--basetemp /tmp/mvllm2-ui-proof-20260912`。暂存的三个代码文件与快照逐字一致；临时日志`/tmp/mvllm2-m3-ui-full-pytest.log`。后续CLI/DVC接线另验，真实跨机审查仍待执行。

## 19. M3h：七阶段公共入口与真实 DVC 依赖接线

2026-09-12 公共 run_stage/CLI 全部切换至真实输入适配，七阶段强制显式 root/inputs/batch；回收强制 results，发布与校验强制完整版本。新增 dvc-config 配置动作，仓库模板无默认输入/版本；生成的七阶段依赖覆盖原视频、注释、split、ROI、业务契约、嵌套参考、全部处理器 pins 和实际实现代码。工作输出 persist，漂移时停止；正式 payload 独立跟踪，validate 不产生旧指针。

CLI 两项测试先取得缺失输入仍成功、显式 inputs 未接线的行为 RED；DVC 配置以返回空配置取得行为 RED。针对性联合命令 `.venv/bin/python -m pytest -q tests/versioning/test_data_pipeline.py tests/versioning/test_cli.py tests/versioning/test_dvc_pipeline.py tests/versioning/test_e2e.py --disable-warnings --tb=short` 为 **245 passed，293 warnings，29.15秒，exit0**。DVC 22项覆盖真实配置、状态变化、受控 repro 与本地缓存 push/pull；旧合成管线测试替换为真实适配测试，整体计数不宜与此前机械比较。

独立 reviewer 对代码及 versioning/SCRIPTS.md 操作链核对通过，独立25项通过，并验证嵌套处理器/参考/候选契约修改会使真实 DVC 状态过期。DVC 测试中的媒体/处理器和人工决定仍为 fixture；实际 DVC 全部七阶段跨进程媒体执行尚无证据。E2E 已经过全部真实适配阶段，但不代表真实媒体或人工验收。

训练机验收执行单经独立审查修复一项 P2：小样本仅有 development，准备时只读开发参考并构造明确空 test 参考，不读取原测试审查标签。复审通过。本轮前期只读结构调查曾打开测试参考结构；未用于模型、选样、调参或质量结论，后续执行单不再要求访问。远程执行及两份正式对象复制仍待明确授权。

最终权威命令 `.venv/bin/python -m pytest -q tests/versioning --basetemp /tmp/mvllm2-m3-entry-proof-final-20260912` 在本机当前完整工作树执行：**1768 passed，341.64秒，exit0**，已等待进程正常退出。临时日志 `/tmp/mvllm2-m3-entry-full-final-pytest.log`。没有新增真实训练机运行或正式迁移证据。M3 本地接入完成，整体 M3 保持进行中。

本轮 M3a–M3h 均已本机提交；最终代码提交 `18d3da0e2a1ab086d4f5c2eb466ef0a68d3ca216`。为待授权同步准备增量 bundle `/tmp/mvllm2-m3-18d3da0e.bundle`，基线 `2027c4dc14753971bf499d9b65ede6bbf650222f`，89,047字节，SHA-256 `0547ba5d5408dcebaf2c72f091882faadeea9389e03b12592a1b14cff0edd896`；本机 `git bundle verify` exit0。尚未传输；bundle 包含上述代码及执行单，不含本条后续证据记录提交。执行前再次检查训练机祖先与状态。

## 20. M3 训练机真实媒体与两份正式复制（2026-09-12）

用户对已审执行单明确回复“确认”，授权隔离分支同步、新 CPU 环境、两段 development 视频真实对照、Mac 审查回传及两份声明 release 复制迁移。未授权 push/merge main、模型训练/GPU/完整评测或改写旧产物。

本节由训练机实际执行后记录，执行代码 `18d3da0e2a1ab086d4f5c2eb466ef0a68d3ca216`。增量包SHA `0547ba5d5408dcebaf2c72f091882faadeea9389e03b12592a1b14cff0edd896` 在两端一致，训练机 bundle verify通过，隔离分支从2027c4dc仅快进8提交。正式main仍为f1b7d8a3且干净。既有.conda-m2保持不变，新.venv-m3安装CPU Torch2.5.1+cpu/torchvision0.20.1+cpu、Transformers4.56.1、PyAV18.1.0、Streamlit1.63.0/cropper0.3.1；继承DVC3.67.1等项目依赖。处理器只加载17个冻结代码/配置/tokenizer文件，不加载模型权重；CUDA_VISIBLE_DEVICES为空，离线模型加载，OMP线程4。

原视频video_0003/video_0011的SHA、全部注释字段、七份split交集与冻结ROI保留；只在输入副本映射旧source路径。仅裁剪development参考，新建显式空test参考，不打开原测试参考。输入SHA `a01fc52ad3e02f00a0fddb77e11af763f924dee9e6a1f5a7a1f0097d16ea6af9`。通过真实DVC repro review_export执行source→ROI→subvideo→review_export，得到34候选、0排除、11自动、23待审；首轮ROI因缺Streamlit停止，向新环境补齐项目依赖后成功续跑，旧阶段验签复用。

独立执行未变的legacy业务计算，逐项比较source治理、ROI几何/时间轴、候选窗口/标签/计划、实际采样映射/门禁：2份ROI、34份子视频、211张抽帧字节全部一致。运行没有调用legacy集合发布器。独立reviewer只读复算输入/四阶段全部文件摘要、重新执行纯候选规划，并比较对照产物，确认该证据成立。

两份源的全部20个声明payload本轮重新验签。来源镜像复制至/data/mVllm_2/workspace/data/releases/<旧ID>及finetune/active_data_release.json（23文件、23,572,633字节），再次验签后，统一CLI data-precheck两对象ready、data-migrate成功。逐文件目标与原源SHA相等，receipt有效且payload只读：

| 正式身份 | 声明文件 | 样本数 | 状态 | 新训练引用门 |
| --- | --- | --- | --- | --- |
| data-v4.1-r1 | 9 | 1275 | superseded，replacement=data-v4.1-r2 | 拒绝 |
| data-v4.1-r2 | 11 | 1678 | active | 元数据允许 |

metadata的protocol、purpose、training_allowed、sample_count、splits、source_batches均与已确认转换规则及原manifest一致。原指针字节和正式Git工作树未变。引用门调用需传领域根/data/mVllm_2/data；首次检查脚本误传store根导致两者均报不存在，修正脚本参数后按预期通过，非迁移产物错误。独立reviewer重新验签20文件、两个receipt及准入/拒绝结果均通过。

原JSON外部媒体引用保持不变；仅按已声明路径stat检查，r1共9421、r2共11986个唯一视频/帧引用，经既有PROJECT_LOCAL_LEGACY_PATHS映射在原workspace/data全部可达，未读取这些媒体字节。新来源镜像未复制外部视频/帧；M4必须显式保留正确的媒体根，不能据此宣称新store自包含或训练已成功。

Mac已接收完整review_export包，验签并以现有Streamlit AppTest加载真实帧，零异常/错误、显示23待审，没有点击审批或创建任何决定。这是跨机包加载证据，尚非完整人工回传。按用户提出的“未断裂无需人工”规则调查：11普通未断裂在新旧两边均走automatic_validation；23待审为15发生断裂、4已断裂、4临界未断裂，旧发布全部标为human_review/approved。其媒体SHA、采样帧、时间戳及标签与本次完全相等，但原reviewer_id全部为空；旧界面该参数可选，空作者不能改解释为自动准入。当前真实审查者来源未确认，不推测填名，不创建回传结果。独立reviewer确认此缺口，M3整体保持未完成。

原始证据目录：训练机隔离项目m3-verification-20260912/comparison/；脚本prepare-inputs.py、compare-media.py、mirror-sources.py、verify-migration.py及日志保留。以下SHA固定本节所引用的轻量报告：

| 报告 | SHA-256 |
| --- | --- |
| environment.json | `d6883ec7a372b75cf170821949ee92d7aea1c4b48a4086a2230f4300edafcfa0` |
| input-preparation.json | `3c1d6e95e92b1c38f3d56c70be6610aeca41ac57ad6db68c5835cc48506665e5` |
| real-media-comparison.json | `4700f40bbb29696c4903db34f3d36809187654b25d1b58a0c42a6e69abebac2c` |
| source-mirror.json | `d087b33e303d19db27120681bd63959156207d36a72917fc1df6f22bd22aecd2` |
| formal-data-precheck.json | `9d8644939481f05f2ffd80c74e3ac965ad4b8024b521426bba758d9dd9ca5644` |
| formal-data-migrate.json | `76872c640233fdb6cc4116f578f76d1c219940cd097fd20f14747571ea44fcb3` |
| formal-migration-verification.json | `6fedad7c140ec11d5e20d9a6eee1ba9cab54553089c6d668894d56533d111d3e` |
| external-media-reachability.json | `44792677f06ef6983dc01cd7300b83e6d8b1bfad2f18832c898ef867024d932b` |
| review-routing-investigation.json | `b72cbe5348c44cae42be8a5d9062ab60cf095338e885220416702b6055a8ff69` |
| mac-package-inspection.json | `f3613ba197ca81fa0f8bae623563d8303126abb11b639048a9b97ef36887b10c` |

## 21. M3 Linux 恢复测试路径可移植性修复

训练机新环境执行 `.venv-m3/bin/python -m pytest -q tests/versioning/test_data_pipeline.py tests/versioning/test_cli.py tests/versioning/test_dvc_pipeline.py tests/versioning/test_e2e.py --basetemp <隔离项目>/m3-verification-20260912/pytest-tmp`，**244 passed、1 failed，23.66秒**。唯一失败为真实DVC remote add写入含中文的绝对地址时ASCII编码错误，尚未执行push/pull，不当作产品媒体或正式迁移失败。

仅将test_dvc_pipeline.py中的临时remote URL改为`os.path.relpath(remote, root)`，仍定位原fixture缓存目录，全部push→删除临时payload/cache→pull→文件清单/元数据/封存校验断言保留。训练机同一代码修复后DVC专项 **22 passed，8.34秒，exit0**；独立reviewer确认本机/训练机diff一致、旧失败与新通过日志对应，审查通过。这不证明DVC支持非ASCII绝对remote地址，后续缓存配置应保留此环境限制。

本机完整权威命令 `.venv/bin/python -m pytest -q tests/versioning --basetemp /private/tmp/mvllm2-m3-portable-final-20260912` 为 **1768 passed，273.39秒，exit0**，已等待正常退出，日志`/tmp/mvllm2-m3-portable-full.log`。无production代码改变。训练机原始两份日志位于comparison/linux-m3-targeted-pytest.log和linux-m3-dvc-fixed.log。本节修复按同次提交追溯。

训练机实机证据原子提交bf3d4ca已通过SHA与bundle verify取回本机，双方暂未push。两份真实release复制与原媒体对照完成不代表M3整体完成：23条人工审查的可信作者来源及回传→非正式真实发布/校验仍待补齐。

## 22. 人工审查者必填与匿名草稿冻结门（2026-09-12）

用户本轮回忆23条历史审查“应该就是我审核的”，并明确要求分析原因、修复未来人工审查必须补全该字段。代码层面已证实：legacy UI 的reviewer-id可选且默认None，唯一保存入口原样传入new_decision；记录规范化保留None，v4→v4.1迁移继续保留旧值。RUNBOOK原本已写必填，而入口未落实。没有当时启动命令/操作日志，不能把缺参这一可复现机制写成具体历史运行的确定原因，也不能由此确定历史作者。

在用户追加授权范围内，两种UI模式统一在加载输入前拒绝缺失、空串和纯空白reviewer-id，去掉首尾空白，并在界面显示本次审查者。实际人工保存继续同时记录该身份与真实当前reviewed_at。完整汇总前新增逐条作者检查，匿名旧草稿禁止冻结；操作者须切到全部候选重新核对保存，不把历史匿名决定批量归给当前操作人。共享历史读取/迁移schema、普通未断裂自动规则和旧封存对象未改。重建流程输出的继续审查命令追加显式REVIEWER变量要求，未设/空值不启动UI。操作说明同步。

12项行为测试先取得有效RED（缺参未拒绝、未strip、匿名旧决定可进入冻结），修复后身份专项加现有完整UI AppTest **13 passed，4.40秒，exit0**。独立reviewer另外执行身份/UI/workflow/helpers **22 passed，10.04秒，exit0**，并独立临时目录验证：匿名完整草稿冻结零写入且草稿字节不变；仅重新保存匿名条目后冻结成功，该条新作者/新时间，其余条目原作者/原时间逐字段保持。重建及legacy相关回归 **47 passed，3.24秒，exit0**。相关293 warnings为已知pytest历史临时目录清理噪音。

独立补审在Bash/Zsh验证继续审查命令的未设、空值、中文/空格标识及纯空白传参边界，审查通过。未由Agent模拟真实人工批准；原23条仍保留来源缺口，用户自述作为本轮背景记录，未改写原始审查者字段。

本机完整权威命令 `.venv/bin/python -m pytest -q tests/versioning --basetemp /private/tmp/mvllm2-m3-reviewer-required-20260912` 为 **1780 passed，398.37秒，exit0**，已等待进程正常退出。UI与身份测试快照在该运行期间未改变；期间补充的重建命令提示由上述47项legacy回归和独立Bash/Zsh核查覆盖。日志`/tmp/mvllm2-reviewer-required-full.log`。

训练机隔离分支已验签增量包并快进至修复提交`5495090ece813608294a596b79f67dbdf8485803`，原正式main未修改。该机器以`.venv-m3/bin/python -m pytest -q tests/versioning/test_data_pipeline.py -k "TestHumanReviewerIdentity or TestInputReviewApp"`（独立basetemp、CUDA_VISIBLE_DEVICES为空）复验为**13 passed，4.37秒，exit0**，日志`m3-verification-20260912/comparison/linux-reviewer-required.log`，SHA-256 `d500702125a94a59966908107b8d37a1fa66ea791c738e7ecb8f1d9dc84e7fe9`。此追加记录在实际执行机器原子提交；不包含新的真人审查或M3回传。

## 23. 单维护者默认归属与 Mac 历史审批复用（2026-09-12）

用户进一步明确：除普通未断裂自动候选外，历史人工审批全部由本人完成；项目唯一维护，不需要反复确认个人姓名。用户批准默认记录“项目维护者”，取代第22节的手填必需和旧匿名记录重新审批要求。新人工决定自动保存该角色及实际审查时间，可显式覆盖非空标识；legacy 原始匿名字段保留，不因姓名缺失新增门禁。versioning 回收的完整决定、标签和媒体证据绑定校验保持有效，11条普通未断裂继续自动准入。

测试先取得3 failed/1 passed的有效RED（两模式缺省角色、旧匿名冻结），修复后专项及完整UI交互5 passed/exit0；legacy重建/工作流/helpers 47 passed/1.22秒/exit0。独立reviewer定向28 passed/9.94秒/exit0，另实测默认角色落盘、portable空作者拒绝且零输出；操作说明对照实现通过。

Mac真实包 `/private/tmp/mvllm2-m3-mac-20260912/review_export` 的23条历史批准按用户确认复用。原视频、按序采样帧、时间戳与标签逐条一致；使用原reviewed_at、状态、修正、有效标签与备注。原source文件SHA为`28677745f6bc0b475d1824250a6fae67e0c680593e22a3c989c4f038252200d6`。原记录（含缺失作者及19条旧迁移来源）完整保存在本目录 `historical-review-attestation.json`，本次记录时间独立于原审查时间；没有改写旧源或模拟新的视觉审批。

真实UI加载授权复用草稿并自动冻结成功：23完成、0待审、0异常/错误，0次新视觉审批。回收文件SHA `d662905beda62bd75c6623b7f8e86877de2e904ebe231bb1bec92bb2f8a9637c`；确认记录SHA `9027145f6e229c9a3b09489b238a2151f122d680afeb2ea294388e0341c6b591`，轻量报告 `mac-review-return-verification.json`。脚本 `/tmp/mvllm2-m3-reuse.py` 及真实包/草稿/输出保留本机，副本保留训练机comparison。独立reviewer逐条核验原值保留、原始记录全等及实际回收校验通过。

本机完整回归 `.venv/bin/python -m pytest -q tests/versioning --basetemp /private/tmp/mvllm2-maintainer-full-20260912` 为 **1772 passed，481.05秒，exit0**，已等待清理后正常退出；日志 `/tmp/mvllm2-maintainer-full.log`。本切片代码在运行期间未更改。测试总数从1780变为1772，是以4项单维护者行为测试替换上一方案12项身份门测试；不是跳过失败用例。

## 24. 训练机真实回传、开发发布与 M3 闭环（2026-09-12）

在用户已授权的训练机隔离 checkout `/home/liuyang/文档/mVllm_2-migration-7eeb93a7` 执行，运行目录仍为 `m3-verification-20260912`。实际媒体/回收/发布执行代码为 `15414d3d2a265ac70a36c9be9c0f25f2ec93b80b`；最新单维护者 UI 在 Mac 产生回收，训练机本次接收没有依赖新 UI 改动。原有 CPU/offline 环境中，于 `RUN/store` 使用 `.venv-m3/bin/python -m dvc repro release_validate` 正常退出0；CUDA_VISIBLE_DEVICES为空，OMP_NUM_THREADS=4，HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE=1。前四个已封存阶段复验复用，随后真实执行 review_import → release → release_validate。

训练机 `RUN/review_return.json`、review_import 冻结副本及发布 payload 内回收文件SHA均与Mac的 `d662905beda62bd75c6623b7f8e86877de2e904ebe231bb1bec92bb2f8a9637c` 相同。开发发布位于 `RUN/store/data/releases/data-v4.1-r1`，与 `/data/mVllm_2` 正式复制 store 的同名版本严格分开。发布校验passed：34样本、257个payload文件；全部逐文件摘要/大小/完整集合与构建清单一致且去写位。实际来源23 human_review + 11 automatic_validation，排除0；标签分布15发生断裂、4已断裂、4临界未断裂、11未断裂。六份数据集按原显式split保持：fold0 train34/validation0、fold1 train0/validation34、fold2 train34/validation0。两个source的小样本固有空侧不是全量数据遗漏。

独立reviewer通过只读SSH再次调用实际run_input_release_validate，并独立复算257文件、回收三处SHA、34候选来源、六fold逐条标签/成员/媒体引用；无finding。原历史审查源SHA仍为 `28677745f6bc0b475d1824250a6fae67e0c680593e22a3c989c4f038252200d6`，原活动指针摘要不变，正式main仍为 `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52` 且clean。

实机证据 `RUN/comparison/dvc-real-return.log` SHA `1a9a53ed74d00f7452963d673247b0a6eb03b91f71ddd03ac3d74bcaf489881d`；`real-roundtrip-verification.json` 记录发布、来源及保护检查；`historical-review-attestation.json`、`mac-review-return-verification.json` 和复用脚本副本同目录保留。证据在实际训练机原子提交，再用验签增量bundle取回Mac。

结合第20节真实媒体旧算法对照及两份正式release复制、第23节用户确认与Mac回传，M3真实验收链路已经闭环。审批复用不等于新的视觉审查；没有训练/GPU/完整评测，不推导模型效果。M4–M8尚未实施，尤其正式迁移payload的外部媒体仍需M4显式绑定原workspace/data根。

最终代码7a122323经SHA一致且bundle verify通过的增量包快进到本隔离分支（同步前独有提交0/1，tracked clean）。Linux默认身份与完整UI专项 **5 passed，4.39秒，exit0**，日志comparison/linux-maintainer-default.log；同代码再次执行公共release_validate仍passed（34样本、257文件）。结合Mac完整1772项正常退出和两轮独立审查，M3验收完成。该结论不关闭整体迁移任务，也不进入M4。

## 25. M4a 实际训练适配器（2026-09-12）

本机 Mac，基线 e428f1c9；本切片提交用 `git log -- finetune/train_with_contract.py` 追溯。已有 Intent/Spec/Plan 祖先关系有效，本机 main 为当前任务祖先（独有提交0/89），交接文件始终未跟踪。

Test List：已加载配置传到真实 tuner；不修改冻结输入；执行异常传播；来源漂移拒绝；非法 mapping 在处理器前拒绝；CLI重复YAML键拒绝。先新增测试，`.venv/bin/python -m pytest -q tests/test_train_with_contract.py` 得到6 failed/1 passed、exit1：5项缺少适配API，1项旧CLI静默接受重复键。旧pytest临时封存目录清理另报293条warning，没有把它们当行为RED。

最小实现提取 `run_training(config)`，参数深拷贝；LLaMA-Factory来源检查先于处理器安装，处理器契约先于tuner；CLI用拒绝重复键的SafeLoader并调用相同适配器。GREEN：`.venv/bin/python -m pytest -q tests/test_train_with_contract.py --basetemp=/private/tmp/mvllm2-m4a-green-20260912`，7 passed/0.11秒、exit0。

独立reviewer读取两文件diff及实际tuner/处理器依赖，运行相同测试（basetemp为 `/private/tmp/mvllm2-m4a-review-20260912`）7 passed/0.17秒、exit0，补测嵌套重复键、非字符串键、处理器异常及contract→tuner顺序，无finding。此处引用reviewer结果，并非主Agent重复运行。

验证限制：动态使用受控tuner/处理器替身，真实依赖链仅静态检查；没有模型加载、GPU、训练机操作或完整评测。这个切片不表示M4身份冻结、MLflow生命周期或三折准备完成。用户本轮澄清：同一train包含三折，各折绑定既有训练/验证划分；版本迁移不新增采样要求，不擅自把历史fold0的3k实验扩展到三折。

## 26. M4b fold 执行事件（2026-09-12）

Mac，承接4c88cd95；仅低层执行事件适配，正式输入门与公共入口继续在后续切片接通。Test List：实际参数、指标和子Run顺序；异常/中断；缺失、空、非数值、非有限指标；invalid父Run；既有fold冲突。新增9项先RED（缺API，exit1，日志 `/private/tmp/mvllm2-m4b-red.log`），实现后完整模块146 passed/40.72秒、exit0。

独立reviewer在临时SQLite复现两个P2：MLflow默认截断超过6000字符的参数；create_fold_run中的log_param失败遗留父子RUNNING。追加两项回归得到有效RED（2 failed/exit1，`/private/tmp/mvllm2-m4b-review-red.log`），随后按实际MLflow上限在创建前拒绝超限，先取得子Run所有权再在try内写入并逐字读回复验参数，失败终结本次子Run/父Run且原样传播异常。

修复后 `.venv/bin/python -m pytest -q tests/versioning/test_mlflow_train.py --basetemp=/private/tmp/mvllm2-m4b-fixed-20260912`，148 passed/52.28秒、exit0；日志 `/private/tmp/mvllm2-m4b-fixed.log`。独立reviewer复审11项9.00秒、exit0，并验证中文恰好6000字符、6512字符拒绝、参数写入RuntimeError/KeyboardInterrupt、读回截断，各项通过，两个P2关闭。

没有真实训练/GPU、远程或正式store操作。这里是非GPU注入执行器加真实临时MLflow数据库证据，不证明实际模型训练成功。并发执行、输入冻结与导出恢复由后续编排切片补齐，后端持续不可用或进程被强制终止的恢复未由本切片穷举。代码提交以本节同次提交及 `git log -- versioning/mlflow_train.py` 追溯。

## 27. 已确认 Prompt 的实际登记（2026-09-12）

承接458e2004。Mac与训练机隔离checkout中的 `v4.1-concise-evidence-json-v2` 源Prompt/manifest逐文件SHA相同：分别 `8870c537bea1fb86b0c2419555c279e934227e4602d1c2f724438b9cc6e460af`、`de737c67149b58e1f5ae2f9ce493287237eabc83aa88f8d4935011eff0402e5d`。本机执行 `.venv/bin/python -m versioning migration prompt-precheck --root /Users/pcoffeep/AgentPlayground/active-projects/mVllm_2 --mapping docs/results/version-control-migration/object-mapping.yaml` 返回ready/exit0，随后同参数prompt-migrate返回prompt-v4.1-r1/exit0。此动作使用M0已user_confirmed的唯一Prompt映射及持续有效实施授权。

Git正式记录 `records/prompts/prompt-v4.1-r1.yaml` 的SHA为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`。独立reviewer用标准load_prompt读取，逐字段核对system_prompt/user_prompt完全相等、output_fields内容和顺序一致；legacy六字段内容hash复算为 `0040c7d73cc417ac81fca196fec3c4a30b011ca15549eb324a3a37cde0aff6db`，匹配源manifest。标准加载拒绝旧身份、LATEST及不完整ID。对已存在目标再次只读预检仅报告冲突，未重跑写入。

独立审查通过，无finding；旧Prompt与活动指针相对HEAD未修改。训练机正式store当时尚无该Prompt文件，本节只记录Mac产物与两端源一致性，不冒充训练机已部署；后续随已提交Git对象同步。无模型权重加载或GPU工作。

## 28. M4c/d 三折输入冻结与真实调用编排（2026-09-12）

本机Mac，承接458e2004的训练事件及d92a0a19的正式Prompt。Test List：六份fold数据的成员/顺序/标签保留，显式媒体根与receipt漂移拒绝；prepared无Run，冻结三折完整配置；调用真实训练适配器、三fold父子Run/指标/产物/汇总/导出；冻结文件漂移在Run创建前拒绝；公共prepare/validate/run路由。数据构建3项和准备/执行3项分别因缺API得到有效RED；CLI路由2项得到有效RED。早期联合65项通过，不作为最终证明。

独立reviewer发现tokenized缓存绕过与媒体字节未冻结两个P1、导出失败后缺恢复入口一个P2。三项回归先RED（`/private/tmp/mvllm2-m4cd-review-red.log`，3 failed/exit1），随后prepare/verify拒绝tokenized_path，冻结实际视频SHA/大小并执行前重算，增加公共train export从相同completed Run补导出。模型产物上传父Run foldN/adapter，子Run引用同一路径；异常记录保留原异常。修复后联合68 passed/exit0，日志 `/private/tmp/mvllm2-m4cd-fixed.log` 与按真实布局修正后的 `/private/tmp/mvllm2-m4cd-layout.log`。

训练机只读核实了正式迁移对象实际结构：文件直接平铺版本目录、protocol为tensile-vlm/v4.1、split键为fold_0/1/2。新七阶段使用payload/与fold0/1/2。读取器按receipt或显式data-inputs区分，不修改发布内容。独立复审68 passed/2.56秒、exit0，另验证同长度媒体换字节拒绝、公共补导出幂等且执行次数仍3、Run身份漂移拒绝及父子产物引用；3个finding关闭。

广回归 `.venv/bin/python -m pytest -q tests/test_train_build_dataset.py tests/test_train_build_source_aware_dataset.py tests/test_v4_1_runtime_pointers.py tests/test_train_with_contract.py tests/versioning/test_cli.py tests/versioning/test_mlflow_train.py --basetemp=/private/tmp/mvllm2-m4-training-regression-20260912 --tb=short`：233 passed/105.57秒、exit0，日志 `/private/tmp/mvllm2-m4-training-regression.log`。运行代码期间未变。新增七阶段→三折数据构建测试使用原reviewed_inputs fixture，主Agent与独立reviewer分别1 passed/1.06秒及1.00秒、exit0；媒体生成仍为替身，六fold有序视频/标签和无Run均验证。

已同步versioning/SCRIPTS.md操作段与finetune README入口引用。主Agent按doc-contract沿用现有Contract扩充索引Scope；独立reviewer逐条核对CLI与链路完整性，通过。完整参数、环境版本和git_commit由调用者核实声明，代码不自动证明它们等于真实环境。

本机验证使用隔离媒体/模型替身与真实临时MLflow，未加载模型、未执行GPU或完整评测；正式eval入口尚未接线，M4整体保持进行中。已有失败训练与checkpoint不自动覆盖或续跑；此切片明确提供completed事实的补导出恢复。迁移源和旧活动指针保持原样。

## 29. M4训练机输入准备执行范围（执行前记录，2026-09-12）

只读核对：训练机隔离分支仍e428f1c9、tracked clean，仅原.conda-m2/.venv-m3/m3-verification目录未跟踪；正式main仍f1b7d8a3且clean。Mac main是本任务祖先；后续先对增量bundle验SHA/verify及祖先关系，再快进该隔离分支，不push/merge main。

拟在 `/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m4-verification-20260912`（RUN，已核实不存在）执行已授权的CPU准备dry-run。只复制正式r2的13,743,985字节轻量发布及receipt到RUN/store，并使用本次Git正式Prompt；不复制视频、不覆盖正式对象。实际媒体根为 `/home/liuyang/文档/mVllm_2/workspace/data`，只读核实1678个唯一视频、165,485,727字节。准备与验证各流式读取该范围的内容摘要，顺序CPU/I/O，不加载权重、不运行训练或评测。

输入配置从现有active/v4_1_visual三fold YAML读取，显式绑定真实普通模型目录 `/home/liuyang/文档/mVllm_2/models/minicpmv4_5`；只用来验证参数传递和输入准备，不构成新实验或超参数选择。在RUN/store中用隔离train-v4.1-r1调用公共prepare和validate；该身份与任何正式store下同名对象分离。依赖版本使用既有.venv-m3的实际版本，CUDA_VISIBLE_DEVICES为空、OMP_NUM_THREADS=4、HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE=1。输出限RUN下输入配置、冻结input、验证JSON/日志和轻量摘要；预期不产生MLflow数据库。结果完成后在本节追加实际命令、退出与限制，执行前文字不能视为已经通过。

### 29.1 实际执行与独立验收

已提交代码6c43479e通过增量bundle同步到训练机隔离分支：bundle SHA `9c0149a9920e06809588261b16a769dcc89b7781ac214a43a8a7270b4caa8a09`，两端校验一致，bundle verify通过；同步前独有提交0/4、tracked clean，通过 `git cherry-pick --ff e428f1c9..6c43479e` 保持相同提交对象严格快进。正式main未参与同步。

按本节执行范围在RUN/store真实调用公共train prepare（2.568秒、exit0）与train validate（1.372秒、exit0），完整实参见RUN/preparation-report.json。引用正式r2原划分：fold0 train1253/validation425，fold1 train1014/validation664，fold2 train1186/validation492。冻结1678个唯一视频的SHA/大小，共165,485,727字节；没有复制视频、加载权重、创建MLflow或训练输出。输入清单SHA为 `7c27968d748e538072c3874371a1f78626d38cc3af047c228edee877e91901b3`，Prompt在Git仓库、隔离store和input副本中的SHA均为 `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`。

Linux `.venv-m3/bin/python -m pytest -q tests/test_train_with_contract.py tests/versioning/test_cli.py -k 'versioned or train_prepare_routes or train_run_and_validate or completed_training' --basetemp=RUN/pytest-inputs --tb=short`：11 passed、57 deselected、3.31秒、exit0。仅选择本次新输入/执行替身专项，未称作全套复跑。日志RUN/linux-training-tests.log。报告SHA `0e3650fda068667dbf1031c7053d4a1fd1d2825abb8ff815cf364fd888187730`，日志SHA `033f936c6cbb6e832b0fd591312b4b26ee9ccbac920195c97e573d4b09f71328`；两份轻量副本已回取Mac `/private/tmp/mvllm2-m4-evidence-20260912/`。

独立reviewer随后仅通过只读SSH遍历实际产物，未重新执行prepare/validate：六份数据共5034行的成员、顺序、assistant标签和Prompt逐项一致，train/validation无交集；1678视频全部流式SHA/大小一致；12个冻结输入文件的清单、摘要、大小、只读位和无symlink通过。正式r2的12个文件与隔离副本相等，receipt字节一致且release digest `a80199ee464b45250fd6a1f0369f3c23415e5c0d161cfd3591e65b9f8638ac8b`匹配；原工作区核验前后为clean main@f1b7d8a3。独立验收通过，无finding。配置相对调用者fold-configs只改变dataset_dir/media_dir/output_dir，dataset/eval_dataset原本即逐折对应，其余参数保留。

环境实际为Python3.11.16、torch2.5.1+cpu、transformers4.56.1、MLflow3.15.2、DVC3.67.1；peft与accelerate未安装。基座仅验证普通目录存在，未加载/验签权重。本次是既有CPU环境的真实输入准备证据，不是GPU训练成功、可训练环境就绪或模型效果证据。Prompt现已随Git同步到隔离仓库，并用于隔离store/input；/data正式store的运行镜像未在此次复制，不能声称它已具备Prompt运行目录。没有push、merge main、停止任务、重训或完整评测。

M4训练侧本地实现、独立复核和训练机输入准备已完成；正式eval入口接线、相应受控执行/失败/导出验收仍未实施，M4整体保持进行中。下一步按Plan M4正式评测要求验证完整model身份、数值Model Version、data与评价配置后再解析权重，保留受限评测授权门，不把历史summary转换为passed。既有完成训练的补导出可恢复；失败训练/checkpoint的真实受控续跑未由本次dry-run验证。

## 30. M4e 测评执行事件适配（2026-09-12）

本机Mac，基线123b4ab2；沿用已确认M4及三折对应既有划分的决定。本切片在versioning/mlflow_eval.py新增execute_eval_fold_run，由编排层传入真实执行回调和完整fold绑定。它先创建RUNNING子Run，再调用执行器；非空有限数值指标才允许FINISHED。成功不自动完成父Run、不产生passed/failed质量结论。普通异常记录FAILED，中断记录KILLED，父Run记录failed/FAILED；子Run写失败时仍尝试记录父Run失败，原异常不被tracking异常遮蔽。非法父记录及fold冲突在执行前拒绝，保留其他调用的状态。

Test List覆盖实际调用顺序、成功不等于质量通过、异常/中断、空值/bool/NaN/Inf指标、冲突、invalid父记录及tracking失败。新增12项先因缺API得到有效RED：12 failed/5.76秒/exit1，日志/private/tmp/mvllm2-m4-eval-events-red.log；最小实现后12 passed/6.01秒/exit0，日志/private/tmp/mvllm2-m4-eval-events-green.log。随后补强tracking失败场景的父Run失败断言，最终回归及独立审查结果追加于下文。

该API是低层事件适配器，不是正式eval运行入口。冻结配置、权重解析前的完整model/数值Model Version/data校验、受限数据授权、结果文件持久化与完整性、聚合阈值及不可变导出仍由后续实际编排负责；本切片没有提供新的CLI run动作。测试使用临时SQLite/MLflow及执行替身，没有真实模型加载、GPU或完整评测，也未同步训练机、push或merge。M4保持进行中。

初轮完整测评记录回归239 passed/89.22秒/exit0，日志/private/tmp/mvllm2-m4-eval-events-regression.log；补强断言后的专项12 passed/5.69秒/exit0，日志/private/tmp/mvllm2-m4-eval-events-final.log。独立reviewer确认一个P2：子Run创建成功后的首次get_run失败发生在清理范围外，会留下RUNNING并阻断重试。新增真实SQLite故障注入回归先RED（1 failed/1.57秒/exit1，/private/tmp/mvllm2-m4-eval-review-red.log），随后把创建响应的child ID与后续读回分离，适配器取得本次ID后在try内读回；失败清理与原异常保留均覆盖该窗口。旧create_eval_fold_run公开快照接口保持兼容。

独立复审通过，P2关闭，无剩余可执行finding。reviewer实际专项13 passed、227 deselected、6.74秒、exit0（--basetemp=/private/tmp/mvllm2-review-eval-events-final-20260912）；公开create_eval_fold_run签名、原校验和快照返回兼容。未验证并发调用、创建请求已提交但响应丢失、后端持续不可用或进程强制终止恢复；不能将本轮异常处理测试解释为这些场景已获保证。

修复后主Agent完整测评记录回归：240 passed、93.98秒、exit0，日志/private/tmp/mvllm2-m4-eval-events-fixed.log；git diff --check通过。此次代码与证据由Mac提交，具体提交可通过git log -- versioning/mlflow_eval.py追溯。本机main仍是任务HEAD祖先，无主线漂移需要重新设计；未跟踪agent-handoff.md保持原样且不纳入提交。

## 31. M4f 正式validation测评编排（2026-09-12）

本机Mac，基线c93f53a7；用户要求继续正式eval run接线。新增公共eval prepare/validate/run/export及finetune/eval_run.py实际编排。当前覆盖与Registry一致的single_fold（fold0）和cross_validation三折模型，使用显式data原有完整validation划分；full与holdout实际数据读取尚未接入，新动作在真值或权重访问前拒绝，既有低层授权门维持。阈值由调用者显式提供非空最低率mapping，无默认质量门槛，不新增采样要求。

Test List包括数值Model Version错误先于权重解析拒绝、prepared无eval Run、冻结Prompt/成员/标签/媒体与评分实现、实际loader/strict scorer接线、三折及single/merged路由、运行失败与质量失败区分、上游/冻结输入/运行中媒体和权重漂移、CLI拒绝raw目录/参数覆盖、MLflow权威输出验签与completed补导出。首6项因缺API得到RED（6 failed/3.83秒/exit1，/private/tmp/mvllm2-m4-formal-red.log），初实现6 passed/4.88秒；CLI和无旧指针导入专项RED为2 failed、1 passed/1.45秒（/private/tmp/mvllm2-m4-formal-cli-red.log），接线后13 passed、1 skipped/5.77秒。首次联合发现旧测试把“import runtime必须读活动指针”当要求；已改为“显式请求legacy RELEASE_ID时缺指针仍fail-closed”，同时保留正式纯推理导入不读指针测试。

精确增加实际model_runtime直接依赖finetune/validation/constants.py的惰性旧路径读取，并在Plan文件白名单说明原因；不改变旧数据路径的返回值、生成参数、标签或划分。该隔离连同eval_run/release_validate/v4_1_runtime解除新路径导入时的活动指针读取，旧文件和旧CLI身份继续保留至M7。versioning/SCRIPTS沿用Document Contract补充正式测评命令，finetune README增加入口链接；独立reviewer已逐项核对输入来源、命令、阈值、支持范围和恢复限制。

初轮广回归479 passed、1 skipped/159.43秒/exit0（/private/tmp/mvllm2-m4-eval-regression.log），不作为后续路径修复的最终证明。独立reviewer初轮27 passed、1 skipped/15.87秒，并用临时SQLite验证单折实际编排与父summary上传失败；确认P1：真实loader把base-model映射到base_model，如果同名兄弟目录已存在，可能加载未被inventory覆盖的另一份权重。新增回归先RED（1 failed/2.46秒/exit1，/private/tmp/mvllm2-m4-eval-alias-red.log），修复复用实际_sanitize_model_path并要求resolve等于已核验目录，基座和adapter/processor均在加载前与执行后检查。独立专项3 passed/3.01秒，错误目录/错误软链接拒绝、正确软链接兼容；额外运行中别名改指向故障注入使父failed且无manifest。P1关闭，专项复审通过，无剩余finding。

已有输出/失败Run不自动重跑或覆盖；completed导出使用冻结input及相同评分实现，从MLflow下载合并输出、核对摘要/样本/评分/指标/结论后幂等发布。export不重读live数据或依赖事后晋级状态，保留已经完成的历史事实；eval本身invalid仍拒绝。持续后端故障、强制终止、创建响应丢失和真实GPU权重加载不由本机替身测试证明。以下追加最终回归和训练机证据。

### 31.1 训练机隔离验证范围（执行前）

只读核对训练机正式checkout仍clean main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52，任务隔离checkout仍123b4ab22ff93fe7121418ae372a9f3176186297、tracked clean，四个既有未跟踪环境/验证目录保留。/data/mVllm_2/records/models下无manifest，/data/mVllm_2/workspace/mlflow/mlflow.db不存在；因此不能声称已有可供真实正式eval准备的新体系已注册模型，不构造伪造完成训练或登记历史不合格模型来补齐证据。

后续先将本机已审查代码通过校验SHA/verify和祖先关系的增量bundle快进到原任务隔离checkout，不push/merge main。已核实不存在的新输出目录为 `/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m4-eval-verification-20260912`。使用既有.venv-m3（不安装依赖）执行tests/test_eval_run.py、tests/test_v4_1_runtime_pointers.py、tests/versioning/test_cli.py、tests/test_train_with_contract.py，basetemp与日志均限新目录。CUDA_VISIBLE_DEVICES为空、OMP_NUM_THREADS=4、HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE=1。输入是测试自行建立的小媒体/模型文件、临时SQLite与受控loader/inference；不读取正式真值、不加载真实权重、不触发GPU或正式测评，不修改/data正式store。预计CPU几十秒、少量临时文件。完成后在实际训练机提交轻量证据，再校验bundle回传Mac；具体命令、版本、结果随后追加，执行前文字不代表已通过。

### 31.2 本机最终验证与提交

路径修复后的六文件广回归（tests/test_eval_run.py、tests/test_v4_1_runtime_pointers.py、tests/versioning/test_cli.py、tests/test_train_with_contract.py、tests/versioning/test_mlflow_eval.py、tests/versioning/test_registry.py）486 passed、1 skipped/215.61秒/exit0，日志/private/tmp/mvllm2-m4-eval-final-regression.log。跳过的是缺本机legacy发布数据的历史validation集测试，不影响隔离fixture的正式入口验证。

随后收紧配置要求：调用者必须显式声明aggregation: pooled，确认使用现有按行合并的评分口径；缺省/其他规则拒绝。评分算法本身未变，不设实际业务阈值。新增缺字段回归先RED（1 failed/1.81秒/exit1），最终受影响的四文件联合回归114 passed、1 skipped/22.19秒/exit0（/private/tmp/mvllm2-m4-eval-final-config.log），没有重复未改动的低层广回归。独立专项1 passed/1.33秒且非法值检查全部拒绝，配置专项复审通过。三折与单折、adapter/merged、执行中媒体/基座漂移均已纳入最终测试；模型调用始终使用受控替身。

git diff --check通过；当前可审阅实现与上述本机证据在Mac原子提交，代码版本由git log -- finetune/eval_run.py追溯。下一步按31.1执行既有训练机隔离同步与非GPU验证，不把本段本机通过写作Linux或真实模型效果证据。

### 31.3 Linux实际执行与独立核查

代码7cb24398与前序c93f53a7通过增量bundle同步到训练机隔离分支；bundle SHA a3e6ab805c5fb55c8a691f46c8109be8310cbeb48b0a1bb14ad6a19846804b4e，两端一致、bundle verify通过，祖先关系0/2，git cherry-pick --ff保持相同提交对象。正式main未参与同步。

按31.1在新RUN目录真实执行四个指定测试文件：114 passed、1 skipped，pytest耗时33.44秒，进程36.854秒、exit0。完整命令与环境在RUN/report.json，输出在RUN/linux-tests.log；报告SHA为21563b253df3f264b3859126c27539c460cc05ae3c65924437ee0b20754076df，日志SHA为fc014488d9225bdabc9e01fd9e54ba53322383169273114751ad4cd791c50838。轻量副本已回取Mac /private/tmp/mvllm2-m4-eval-evidence-20260912/ 并核对摘要一致。实际Python3.11.16、torch2.5.1+cpu、transformers4.56.1、MLflow3.15.2、DVC3.67.1，禁用CUDA可见设备、离线模式、OMP4；未安装依赖。

独立reviewer仅只读SSH和SQLite mode=ro核查，未复跑测试：远端代码路径相对7cb24398无差异；报告/日志/软件版本与两端SHA一致。抽查成功fixture为3样本、0运行失败、completed/passed并有passed manifest；质量失败fixture为3样本、0运行失败、0合法预测、completed/failed并有failed manifest；运行失败fixture为fold0一次运行失败、父failed、无outcome/manifest。独立证据核查通过，无finding。报告中的原进程退出码/耗时/环境变量只能按既有报告核对，未声称事后重建进程状态。

原正式checkout始终clean main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52；任务隔离checkout为tracked clean，保留原有环境和新增验证目录，不能称为整体clean。本段在实际训练机提交轻量验收事实，再通过已验签增量bundle回传Mac。本轮没有真实权重加载、GPU、完整正式评测或/data正式store写入。正式新体系无已注册模型，真实eval准备成功路径仍无证据；不能把这些临时fixture登记为正式模型或效果结论。

M4的正式validation执行接线已完成本机/训练机CPU范围验收；full/holdout实际读取与真实模型成功路径保持显式限制，M4不据此关闭。下一步可推进不依赖真实合格模型的M5服务入口严格拒绝/路由接线，同时保留后续真实模型登记与授权测评的依赖。

## 32. M5服务入口接线（2026-09-12，Mac）

本轮输入为临时SQLite/MLflow、完整data/prompt/train/model/eval身份与合成小权重；ChatModel/uvicorn为受控替身。本机测试不涉及真实权重加载、GPU推理或运行中服务进程变更；本节后续单列训练机只读预检及隔离CPU验证。

Test List覆盖：实际CLI拒绝raw模型路径、无alias/非法模式、模型invalid、current缺失、缓存字节修改、Registry损坏；成功路径只能加载Registry绑定的基座和adapter。公共交付校验删除开发例外入口，管理工具与HTTP smoke统一使用显式alias与mode；smoke检查完整身份、数值Model Version与指纹。旧组件校验的四项历史审计保留为私有函数测试，不构成新准入证明。

初始resolver/启动测试5 failed，交付工具2 failed，smoke路由2 failed，均在实现前观察有效RED。实现后工具16 passed；五文件联合回归179 passed/78.05秒/exit0（tests/test_serve_smoke.py、tests/test_serve_validate_delivery.py、tests/test_v4_1_service_contract.py、tests/versioning/test_materialize.py、tests/versioning/test_registry.py；日志/private/tmp/mvllm2-m5-regression.log）。随后补充Prompt输出字段校验和五类实际启动拒绝，受影响三文件26 passed/10.02秒/exit0（/private/tmp/mvllm2-m5-final-local.log）。

共享resolver先检查alias晋级门和Git manifest/current，再逐文件比较所有声明artifact缓存与MLflow权威源，并把所选模型、基座、身份纳入SHA256指纹；禁止artifact软链接。临时下载目录先正规化系统临时路径（Mac /var指向/private/var），不放宽模型目录的软链接拒绝。加载前校验10字段配置的模型/基座/指纹与Prompt，加载后再解析并核对绑定。响应原11字段deployment保持，附加model_registry供smoke核对。启动不自动物化/修复，不提供旧开发模型豁免。

独立审查已通过本轮代码与本机验证范围；M5保持进行中，不以这些本机替身测试关闭真实模型加载/推理或Linux验收。代码与本节版本由git log -- pipeline/server_proxy.py追溯。


### 32.1 本机补充验证与Linux执行范围

新增加载中基座内容漂移拒绝、merged唯一deploy_target路由，并纳入实际FastAPI受控引擎的既有production_contract回归。最终四文件41 passed/7.91秒/exit0，日志/private/tmp/mvllm2-m5-complete-local.log；四文件为tests/test_serve_smoke.py、tests/test_serve_validate_delivery.py、tests/test_v4_1_service_contract.py、tests/test_production_contract.py。先前179项底层联合回归后未修改Registry/materialize实现，不重复该批测试作为新证据。

只读SSH确认正式checkout仍clean main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52，隔离checkout仍7a750065、tracked clean，保留五个既有未跟踪环境/证据目录；m5-service-verification-20260912尚不存在。独立审查通过、Mac原子提交后，按既有授权通过增量bundle校验与祖先检查快进任务隔离分支。在新/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m5-service-verification-20260912目录输出日志、report与pytest临时对象，用既有.venv-m3执行上述四文件CPU测试。CUDA_VISIBLE_DEVICES为空、OMP_NUM_THREADS=4、HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE=1；预计几十秒、小型合成权重与SQLite文件，不安装依赖、不访问/data正式store、不启动GPU或真实服务。执行事实与提交随后追加，本段不是Linux通过证据。


独立reviewer对7a750065之后的当前改动完成只读核查：三文件27 passed/9.96秒、production契约与Registry/materialize依赖171 passed/89.21秒、新增merged专项1 passed/2.81秒，均已正常退出exit0；这些是reviewer执行结果，不是主Agent复跑。审查核对实际LLaMA-Factory模型/adapter参数消费、CLI、Prompt、响应与文档链路；发现一处前置文档引用夸大已修正并读回确认，无剩余finding。未验证Linux、真实权重/GPU/真实服务HTTP与大权重哈希开销。git diff --check通过。


### 32.2 Linux实际执行结果

已通过增量bundle将035aee2464ced0ba55ade30a1048f4a6b4fa0a47同步到任务隔离分支。bundle SHA256为30c86d0ffe1b2e956c64b771ee3ac003ee5edf135ac4ce6b472c6138c7461ccd，两端摘要与verify一致，祖先检查通过、独有提交0/1，cherry-pick --ff保留同一提交对象。

初次远程执行脚本因字符串换行转义语法错误在解析阶段退出，未创建RUN或运行测试；修正后首轮四文件40 passed、1 failed/13.61秒/exit1，失败发生在Starlette TestClient导入httpx2之前。原始report.json与linux-tests.log保留，SHA分别为f5bfb3524f2490704a7d7eaade82ee460f07f82b60fd6fa6d47b7ab6b1515e4c和7136a14d4579c2ecc90e21df564c375d9865abda6b6644df4778e0389a698e3b。

核对已安装Starlette1.6.0元数据，其full extra声明httpx2>=2.0.0；在本次RUN/dependencies内使用pip --target安装httpx2及依赖，保持原.venv-m3/.conda-m2与系统包不变，仅为复跑设置PYTHONPATH指向该目录。这是32.1“无需安装依赖”预期的局部修正，沿用已授权的隔离CPU环境范围。实际httpx2/httpcore2为2.12.0、anyio4.15.1、FastAPI0.141.1。安装日志保留既有MLflow3.15.2要求pandas<3而环境为3.0.3的兼容告警；本轮专项通过不能证明全部依赖兼容，后续真实运行前仍需处理此环境限制。

最终四文件41 passed、1 warning/13.45秒/exit0，包含报告版本查询的进程计时15.312秒。warning为Starlette使用已弃用anyio.BlockingPortal别名，不是模型推理告警。final-report.json记录035aee24、完整命令、禁用CUDA与离线/OMP4/PYTHONPATH环境及实测软件版本。其SHA为d6258843f8bd92e3c0c105affa720353b67dbf7d79ca315a41615b0f633307f4；linux-final-tests.log SHA为915bb2ab8946a78904c1ebe78a1daec6539584f0f77e7cf2ae10e1b8968e20fd；dependency-install.log SHA为babb05a98c010ee074726de1403850fe446826d053418ac5ac0b97eb6c787914。五个轻量报告/日志已复制到Mac /private/tmp/mvllm2-m5-evidence-20260912并核对摘要。此处均为实际Linux执行，不包含GPU、真实模型权重、真实HTTP服务或/data正式store操作。

M5代码接线与两端受控CPU测试已形成证据；真实模型成功路径和运行中服务切换仍未验证，M5保留进行中。接下来可推进不依赖真实合格模型的M6隔离备份/传输/恢复；M4 full/holdout实际入口和最终真实环境验收依赖继续保留。独立证据核查通过，详见下段。

独立reviewer只读核对两端五份报告/日志SHA全部一致，首轮40/1与最终41项报告对应；读取包元数据确认httpx2/httpcore2/anyio来自本次dependencies目录，实际代码与报告均035aee24。核查时正式main仍clean@f1b7d8a3，隔离checkout tracked clean且保留六个未跟踪环境/证据目录；随后主Agent仅追加本节和TODO/Plan证据。审查通过，无finding；退出码与耗时按既有报告核对，未声称独立复跑或事后重建进程环境。当前三份轻量文档在实际Linux训练机提交，随后校验bundle回传Mac；提交对象由git log追溯。


## 33. M6显式快照传输（2026-09-12，进行中）

现有backup create已使用Registry快照锁、SQLite备份及scope裁剪；restore的MLflow artifact恢复契约保留原绝对路径布局。本轮仅新增显式已完成快照的SSH传輸，不改源集合、备份范围和旧恢复语义。

Test List：成功后目标catalog/文件与源一致，原源保留；中断、错误catalog摘要、文件损坏、已有目标都不发布；归档绝对路径/越界/重复/软链/硬链/FIFO拒绝；SSH非零状态拒绝；参数不可注入shell；CLI缺参和转发校验。最初测试误用不存在的摘要helper，修正helper后观察有效RED：5 failed/5.69秒，错误均为缺transfer_backup。实现后5 passed/5.78秒；最终backup+CLI联合107 passed/37.33秒/exit0，日志/private/tmp/mvllm2-m6-regression.log。覆盖既有scope升级、源缺失、catalog修复与SQLite/artifact联合恢复；均为本机小型合成对象。

transfer使用源catalog SHA256钉扎已核验快照，SSH远端只执行tar读取，目标同级私有临时目录逐成员接收，验签全部文件及SQLite后rename发布。目标已存在或同目标锁已占用时拒绝，不合并覆盖；普通异常清理本次临时目录和锁。强制杀进程可能留下锁/临时目录，需要人工核对，不自动猜测失效或清理源。新增文档保留原路径恢复限制，大产物直接落指定存储，真实移动硬盘单独待验。独立代码与文档审查进行中。

### 33.1 后续隔离跨机验证范围（执行前）

独立审查和本机提交后，通过既有增量bundle SHA/verify/祖先检查同步训练机任务隔离checkout，正式main不参与。新输出目录拟为/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m6-backup-verification-20260912，执行前确认不存在。使用已有.venv-m3、CUDA不可见/OMP4/离线模式，运行backup+CLI测试生成小型合成fixture；不安装依赖、不读取/data正式store。

从本轮合成fixture的显式data、Prompt、models和MLflow根运行实际backup create/verify CLI到RUN/source-snapshot，核对catalog摘要及字节量。Mac使用新增transfer CLI接收到/private/tmp/mvllm2-m6-received-20260912（执行前确认不存在），只限此次小对象，执行完整验签。受控恢复在训练机：把此次fixture合成源移动到同fixture的retained-originals保留，把Mac已验签副本回传至RUN/returned-snapshot；用restore CLI恢复至原fixture绝对路径，检查父子Run、指标、Registry版本/alias及实际artifact可读和scope裁剪一致。全部原始对象都是本轮测试生成，保留移动前副本，不触碰正式唯一源、运行任务或GPU。以上执行后另记实际命令、提交和结果，不把预案写成通过。


### 33.2 独立审查修复

独立reviewer初轮107 passed/39.92秒、传输专项17 passed/5.49秒，均exit0；确认P2：最终exists检查与os.rename间若另一进程创建空目标目录，普通rename会覆盖该目录，锁仅保护合作传输者，不能保证不覆盖外部创建。新增竞态回归先RED（1 failed/1.97秒，/private/tmp/mvllm2-m6-race-red.log），随后改为Mac renamex_np(RENAME_EXCL)和Linux renameat2(RENAME_NOREPLACE)原子拒绝替换。常量/声明分别对照本机SDK sys/stdio.h及训练机linux/fs.h、fcntl.h；不支持符号/平台/文件系统时失败，不回退普通rename。测试检查竞争目录inode、内容和临时目录/锁保留边界，专项复审进行中。

另补截断tar错误归一为BackupIntegrityError供CLI明确报告；先RED再传输+CLI专项19 passed/6.48秒。一次未指定basetemp的RED出现旧pytest只读目录清理告警，未处理与本轮无关的旧临时目录，随后测试均使用显式独立basetemp。本轮失败输入不会发布目标备份。

修复后主Agent完整backup+CLI109 passed/34.44秒/exit0（/private/tmp/mvllm2-m6-final-regression.log），清理断言专项1 passed/1.82秒。独立专项复审18 passed/6.11秒/exit0，额外注入空目录/文件/悬空软链竞争、不支持平台/符号、ENOSPC和真实libc ENOENT均按预期失败并清理；P2关闭，通过本轮代码与Mac证据范围。Linux原子分支与跨机恢复仍待实际执行。提交前再次核对两端基线：Mac/训练机隔离均54e12a01，正式main仍clean@f1b7d8a3；33.1两端新输出均确认不存在。git diff --check通过，本轮代码在Mac原子提交。


### 33.3 实际SSH往返与训练机联合恢复

实现ab5543de6f53884ff3c7608592770b2a56538c77通过增量bundle同步；两端SHA为9bea9c95d7aa2a77212c18be79311b7fb9d9378eef29aa4dd123dbe512c16817，verify通过、祖先关系0/1，cherry-pick --ff保留同一代码对象。按33.1在新RUN真实执行backup+CLI：109 passed/62.78秒/exit0，包含Linux原子发布竞态；report进程67.338秒，禁用CUDA/OMP4/离线设置，不安装依赖。report.json SHA为2fb52a9123ceff49937d43740c7f7805262554c6d336210f8a2389761c55c986，linux-tests.log为4e009abd027f228738c55d3bb42cefbd771e0faa54e637d41992c2e0802f23ef。

从RUN/pytest/test_transfer_publishes_verifi0的本轮合成data、records、models、mlflow运行实际backup create和verify CLI至RUN/source-snapshot，得到6对象、23文件、905202字节；两条CLI输出相同，SHA为4a3e9f2430becc56e704b8c705c3ed60df30bdb002644196d16f5309f476c309。catalog SHA为9ecf8b34377272d641a6088b519377df3e06670fcf65e440b1b9548e4395d797。

Mac通过新增transfer CLI真实SSH读取同一源：首先故意给全零摘要，exit1/1.623秒且目标不存在；随后正确摘要exit0/1.117秒，在/private/tmp/mvllm2-m6-received-20260912发布快照，实际905202字节且verify通过。transfer-report.json SHA为d835ab6726dea2b6d49d54da46990de089f39dc870be95693a80b4e4738403eb，远端同一文件名为mac-transfer-report.json。本轮只用小型合成产物验证功能，不能外推大权重传输性能。

Mac已验签目录通过scp回传RUN/returned-snapshot并再次完整验签；此次fixture的data/mlflow/models/records移到同fixture/retained-originals保留，再运行restore CLI恢复至这些原隔离路径，exit0、输出restored=true（restore-cli.json SHA4b6ee7a2edc0cf9e8a62646773fc63a36b7b7759cfd213a48efe9bd4851215bc）。没有删除合成原件，更没有移动正式对象。

第一次恢复后核查脚本误把MlflowClient.download_artifacts返回的临时下载目录当成源artifact目录，导致路径断言失败；restore已成功。保留restore.stdout/stderr，纠正核查假设后只重做核查，不重复restore、不修改实现。最终核对实际Run artifact_uri属于恢复后的原fixture/mlflow，源文件和下载副本均为FAKE-ADAPTER-WEIGHTS；SHA34f404d340691e76a7f0af081ed9b46ef691678045959044354d1fc767286e0e。candidate=model-v4.1-r1/数值版本1，train完成且fold0/1/2均FINISHED、父子绑定正确、cv_f1_mean=0.8，eval结论passed（全部为测试构造事实，不是真实模型质量结论）。SQLite integrity_check=ok，18个Run、3个Model Version、1个alias可查；adapter范围的MLflow与模型备份无merged，production_bundle含merged。joint-restore-report.json SHA47f751f77365194c8aede3c03bf7c695197a5eb4217b76b83fc1ea1013199138。

另对恢复出的data、Prompt、model manifest/权重、MLflow artifact共21个非SQLite文件逐个核对catalog大小与SHA，全部一致；restored-file-check.json SHA8c7c73a53abf4d95631071b309b744b95bbd802e440b6f0aa51b4b7cd71cecf5。SQLite以一致性/语义查询验收，未因打开后数据库文件布局可能变化要求机械字节相同。源快照与回传快照再验均通过；报告和日志副本在Mac /private/tmp/mvllm2-m6-evidence-20260912，八份核心摘要清单为evidence-sha256.json，完整命令在对应报告中。

M6功能接线、两端受控测试、实际SSH往返和原隔离路径联合恢复完成；真实移动硬盘及真实大型产物恢复仍未验证，原绝对路径布局限制和此前MLflow/pandas环境告警保留。后续推进M7旧活动入口核查与文档收敛，同时保留M4 full/holdout实际入口及M5真实模型成功路径缺口。独立证据核查通过，结果见下段。

独立reviewer仅只读检查，核对八份关键报告两端SHA一致；三份实际快照均6对象/23文件/905202字节、逐文件验签且无额外文件。恢复文件与catalog、保留原件的非SQLite文件逐字节摘要一致；原/恢复SQLite mode=ro查询一致，确认18Run/3Model Version/1alias、candidate/三折父子/指标/eval与artifact路径及字节，scope裁剪符合声明。通过此次小型合成对象跨机与原路径恢复证据范围，无finding。核查时两端HEAD均ab5543de、隔离tracked clean、正式main clean@f1b7d8a3；其后主Agent仅更新本节及TODO/Plan。历史环境/退出码/耗时依据报告，未独立复跑；错误摘要当时无目标的状态按主Agent过程记录，不能事后直接观察。首次后核查stdin脚本未落独立文件，reviewer仅确认保留traceback及最终结果，不把第41行断言解释冒充独立重建证据。真实硬盘/大型模型/GPU与改绝对路径可用性未验证。三份轻量证据文档在实际Linux提交，再校验增量bundle回传Mac，提交由git log追溯。


## 34. M7a数据旧CLI停用与文档收敛（进行中）

基线a7e0fc14。本批依据已完成M3真实输入/人工交接/发布迁移验收，停用release_build.py、release_build_phase2.py、rebuild_data.py三个旧CLI。脚本在导入legacy业务模块前返回停用提示；--help只说明新入口，其他参数返回2，不解析旧当前路径，不提供legacy模式。私有_legacy_main及业务库保留历史测试，不声明整个legacy包已退役。

实际CLI拒绝与加载前拦截6项先RED（6 failed/1.33秒，/private/tmp/mvllm2-m7-red.log），实现后三文件联合57 passed/1.04秒/exit0（tests/test_data_rebuild.py、tests/test_rebuild_source_only.py、tests/test_release_build_cli.py，/private/tmp/mvllm2-m7-data-regression.log）。历史source-only语义测试明确调用私有入口；新增subprocess测试在独立cwd验证三个真实脚本无输出目录且help指向versioning。本机验证不涉及GPU或真实媒体构建。

数据手册第10节改为实际显式输入、真实ROI/候选/采样、完整审查包与回收、不可变payload、DVC persist；移除早期固定两条候选、隐式默认batch和release_pointer表述。原第1–9节保留并明确历史参考。README、project-guide与脚本索引区分现行操作与历史背景；entrypoint-map记录尚存ROI/审查/训练/eval和索引依赖，未删除artifact_index/resolver。独立代码及权威手册链路核查通过，详见下节。

### 34.1 根指令边界核查（review-ags）

审查对象：AGENTS.md的“新旧体系边界”两条及其状态引用；Agent/Platform：当前Codex会话，并保留项目指令服务多平台的原约束；类型：Project Root Instruction；Scope：整个仓库的新旧入口路由。结论：局部REWRITE；不声称审计其余条款或推断其他平台的自动加载机制。

P1事实/冲突：原两条把pipeline/finetune全部入口描述为尚未迁移，并把当前状态引向基础设施历史台账；与已确认Spec逐入口停止旧写入、已实现服务alias门及本批三个数据CLI停用不一致。证据为Spec“每个已切换业务入口只有一个正式写入者”、三个main停用门、server_proxy及本轮真实CLI测试。影响是后续Agent可能恢复旧回退或误认为整包不可按既有授权迁移。Ownership：根指令保留跨模块保护原则，任务TODO负责状态，CLI负责可执行拒绝；不把具体M7进度复制到长期指令。

KEEP：五族完整身份、fail-closed、历史产物保护、源保护与授权边界；删除这些原则会增加错误回退与批量清理风险。REWRITE：仅将两条改为逐入口核定、已确认方案/授权/验收范围内停止旧写入，禁止恢复宽松回退或批量删业务实现；状态指向既有唯一TODO，基础设施台账作为历史参考。精确diff见本次AGENTS.md改动，无新增工作流或删除其他规则。

验证记录：本会话明确提供用户级重大取舍/持续授权约束与项目根指令；受影响路径中rg仅找到根AGENTS，无子级覆盖。核对Task Artifact、README、CLI、测试、TODO及两个现存台账路径；这里只依赖会话已提供的作用域，不需要猜测宿主加载规则。按完整rubric检查本目标的正确性、作用域、必要性、精确性、密度/上下文成本、渐进披露、职责、重复/冲突、可执行性、验证与安全；无关包管理/CI规则未改写，未把它们包装为本目标新要求。

最终判断：Scope保持仓库级且跨模块适用；Context Cost仅两条；Signal Density为保护原则和路由；Ownership保持TODO/CLI/指令各自职责；Conflict通过符合已确认逐入口迁移范围消除；Verification以路径、代码门和测试核对。该局部修订不改变授权来源，不以修改AGENTS本身创造操作权限；独立reviewer随后核对实际diff和文档一致性。

### 34.2 独立审查与隔离 Linux 验证准备

独立 reviewer 对 a7e0fc14 工作区 diff 核查三个 CLI、变更测试、权威数据手册七阶段链路及其他同步文档和 AGENTS 两条边界，通过本轮局部范围，无可执行问题。独立本机联合测试 57 passed/0.96秒；额外脚本和模块模式以 Python -S 禁用 site packages，共30次启动边界调用通过，覆盖空参、--legacy、旧run/source-only/check-only、--help/-h。git diff --check通过。上述为 reviewer 执行结果，不是主 Agent 复跑；未验证真实媒体/GPU/大型备份。

同文件维护时关闭既有 DOC-INDEX：对照 data_rebuild 的 _update_snapshot_collection_indexes 及 promote 调用，删除脚本索引中已修复缺陷的过期描述。仅修正文档，未重新开放历史 CLI。独立 reviewer 追加核对实际 cdb8632c diff、移动后索引更新顺序及脚本索引/TODO，通过，无 finding；本次文档追加未重复运行测试。

下一步在代码提交并核对两端状态后，将增量 bundle 同步到训练机既有隔离 checkout。输出限定新目录 m7-data-entry-verification-20260912；使用已有 .venv-m3，CUDA不可见、OMP4、离线模式，执行上述三个测试文件的小型合成回归，不读取正式 /data、不执行真实媒体处理、不安装依赖。实际命令、日志及结果执行后追加。
