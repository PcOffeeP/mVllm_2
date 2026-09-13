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


## 34. M7a数据旧CLI停用与文档收敛（本批完成）

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

### 34.3 Linux 隔离回归与完成边界

实现提交881c81819725057e77d7be5d1c2c7cfaa5b08293由Mac生成，增量bundle两端SHA03b1fec56b19da1985681be67c0a55b886627bd65c4e6fe426b853cc46bacdb7；核对隔离分支/HEAD/无tracked改动、bundle verify、祖先与0/1差异后cherry-pick --ff同步同一对象。正式main在同步前clean@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52，未参与同步。

训练机新输出位于/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m7-data-entry-verification-20260912。实际使用.venv-m3/bin/python（3.11.16）执行pytest -q tests/test_data_rebuild.py tests/test_rebuild_source_only.py tests/test_release_build_cli.py --basetemp=<该RUN>/pytest --tb=short，57 passed/2.20秒/exit0，进程2.635秒。环境CUDA_VISIBLE_DEVICES为空、OMP_NUM_THREADS=4、HF_HUB_OFFLINE=1、TRANSFORMERS_OFFLINE=1；没有安装依赖、没有真实媒体或GPU任务。

report.json SHA3829b295939da55b6eb2bf04a830fe34851fbc3c81f5f51d6ffb51c277be47c8；linux-tests.log SHAbd43d7f9cf463d9ce0bcb3cfc1b84074b38e3eeea49e0dfb2f7f8024c66d0d9d。Mac副本/private/tmp/mvllm2-m7-evidence-20260912。首次SSH核查脚本因换行转义出现SyntaxError，在执行前失败、没有建立RUN；修正后首次实际测试成功，不隐去该操作错误。

M7a仅关闭三个数据CLI停用与对应文档、DOC-INDEX；保留私有历史测试函数及仍有实际调用的索引库。M7b剩余旧入口核定和文档收敛、M8最终审查尚待执行。M4 full/holdout读取与真实模型、M5真实加载成功、M6真实硬盘/大型对象等原限制未因本轮轻量回归而关闭。证据文档在实际Linux原子提交，提交通过git log追溯。

独立 reviewer 只读核对两端报告/日志字节和摘要一致、报告内日志摘要正确；实时确认隔离881c8181 tracked clean、正式main clean@f1b7d8a3、Python版本一致，通过Linux轻量证据范围，无finding。未复跑测试；历史命令/环境/耗时依据报告，首次语法错误及未建立目录仅为主Agent过程记录，独立reviewer未重建该历史状态。

## 35. M7b训练与评测旧CLI退役（本批完成）

基线45cae766。train_build_dataset/train_prepare_run/train_with_contract/eval_run公开main及脚本/模块执行在第三方导入前停止，帮助指向versioning，旧YAML/model-dir/默认选择均不能启动。原main改为私有_legacy_main；保留build_versioned_datasets、版本化准备与实际执行、run_training及评分器，新CLI继续直接调用这些函数。两个历史解析语义测试明确调用私有入口。

新增8项先RED（8 failed/16 deselected/0.35秒，/private/tmp/mvllm2-m7b-red.log），随后四文件联合65 passed/1 skipped/21.20秒（/private/tmp/mvllm2-m7b-regression.log）。覆盖48次Python -S脚本/模块启动及公开main拦截、新训练/评测接线和历史数据采样回归；skip为既有真实数据缺失，不冒充通过。均本机合成/受控执行器，无GPU或真实训练。训练说明及脚本索引补最小文档Contract，架构文档沿用Contract、保留B批次历史证据，现行链路说明按真实入口更新。独立审查与Linux轻量复验待执行。

执行前核对两端任务基线45cae766、隔离tracked clean，正式main clean@f1b7d8a3；新Linux输出拟为既有隔离checkout内m7b-training-entry-verification-20260912，当前不存在。提交后增量bundle验签同步，使用已有.venv-m3、CUDA不可见/OMP4/离线模式执行相同四个文件的受控回归；不安装依赖、不执行真实训练/推理、不修改正式/data。评测冻结输入包含评分实现文件摘要，本次eval_run.py改变会被已有冻结输入的漂移门识别；不原地改写旧input或豁免校验，新准备需明确未占用身份。

独立reviewer本机四文件65 passed/1 skipped/20.15秒，skip为test_eval_run.py:48缺历史数据；额外AST核对四模块50个原函数体保持，旧main仅改名，versioning.cli仍直接调用版本化函数。当前代码与文档范围未发现可执行问题，未执行远程/GPU。

### 35.1 Linux隔离复验

实现60dd00bc92e010cdb9df03d7864966ef3cb721cc在Mac提交，通过增量bundle同步Linux；两端bundle SHA9a6fbf4dc808e6df50c82de2bf2038b7375f572b35c910411fb6b433542996f7，verify通过、祖先和0/1差异符合预期，cherry-pick --ff保持同一代码对象。

训练机输出/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m7b-training-entry-verification-20260912。已有.venv-m3/bin/python（3.11.16）运行pytest -q tests/test_train_with_contract.py tests/test_eval_run.py tests/test_train_build_dataset.py tests/test_train_build_source_aware_dataset.py --basetemp=<RUN>/pytest --tb=short，65 passed/1 skipped/37.25秒/exit0，进程40.697秒。skip为隔离checkout缺既有V4.1真实数据，不能算真实数据验收。CUDA不可见、OMP4、HF/Transformers离线，无依赖安装或真实训练/推理。

report.json SHA147e0b9577a02935406b9d69f83f8867243be16ed0553a205a1950f1104b570c；linux-tests.log SHAfe4fc3382cefac46a9cacc4b3f44014af83b0fe9b244c24089a590398d4956c5；Mac副本/private/tmp/mvllm2-m7b-evidence-20260912。本批只关闭四个公开CLI退役及相应文档范围，剩余ROI/审查/索引辅助入口和M8整体审查待推进；真实GPU、full/holdout、大型备份等原缺口仍未关闭。轻量证据文档在实际Linux原子提交，由git log追溯，随后验签回传Mac。

独立reviewer只读获取两端原始报告和日志，逐字节一致、摘要一致，报告内日志摘要正确；核对指定命令和环境记录，实时Python3.11.16、隔离60dd00bc tracked clean、正式main clean@f1b7d8a3，通过Linux轻量证据范围，无finding。未复跑，历史执行环境/退出码/耗时依据报告与日志，实时状态不重建历史进程。

## 36. M7c辅助UI入口接管（本批完成）

基线80b7fa3e。review_candidates_app在参数解析时拒绝旧queue，避免进入current数据根和旧review_decisions写入；完整包及默认项目维护者身份不变。ROI仍是输入准备工具，公开参数要求metadata实际文件/output/project-root；拒绝缺参、无文件/目录和输出覆盖metadata，移除模块导入时current_data_paths调用；几何/媒体/人工决定函数保留。旧ROI解析器只供历史语义测试，未删除仍被业务引用的索引库。

新增入口回归先RED：8 failed/201 deselected/0.60秒（/private/tmp/mvllm2-m7c-red.log）。第一轮两文件208 passed/15.88秒；随后补充非法路径三项，最终两文件211 passed/15.28秒/exit0（/private/tmp/mvllm2-m7c-final.log）。验证限本机合成/受控业务，无真实媒体处理或新人工决定；未将旧数据/模型缺口标记完成。手册现行第10.1节补齐显式metadata来源→ROI输入文件→inputs绑定→七阶段复验，旧1–9节历史语义保留并标注停用路径。独立审查及Linux复验待执行。

拟在代码提交和两端Git核对后，增量bundle同步训练机既有隔离checkout；新输出m7c-ui-entry-verification-20260912，已有.venv-m3以CUDA不可见/OMP4/离线模式运行同两文件CPU回归。输入均本轮合成fixture，不启动Streamlit服务、不安装依赖、不读取正式/data；实际结果另记。

剩余公开辅助CLI已定位：roi_freeze_decisions.py、roi_materialize_videos.py、subvideo_build_plan.py、subvideo_materialize_media.py、review_build_queue.py、review_build_phase2_queues.py、review_route_from_history.py。均有main，需下一批逐个对照新链的库函数调用核定退役，并先补入Plan精确代码范围；不能因本批两UI接管就宣称全部写入入口已停止。build_artifact_index.py及底层索引库继续按实际依赖处理。

最终导入回归改为独立subprocess，避免reload模块改变同进程异常类身份；专项1 passed/0.43秒。独立reviewer两文件211 passed/15.60秒/exit0，追加验证ROI输出软链接指向metadata及旧--data-root均退出2且输入不变；入口控制流、ROI schema→inputs.roi_decisions→七阶段文档链核查通过，无可执行问题。限制为本机CPU，未做真实UI人工操作/媒体/GPU，Linux另验。

### 36.1 Linux隔离回归

实现09035fd4cae7d3eeec7eff79c34a837e419ec5f5在Mac提交；增量bundle两端SHA29b2592940bad9f341a5f3f6f4c3a051ac93d86a5b3369979c74da015357ccad，verify通过，核对祖先及0/1差异后cherry-pick --ff同步同一代码对象。执行前两端任务基线80b7fa3e，隔离tracked clean，正式main clean@f1b7d8a3；新RUN确认不存在。

输出/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m7c-ui-entry-verification-20260912。实际使用.venv-m3/bin/python（3.11.16）运行pytest -q tests/test_roi_annotation_app.py tests/versioning/test_data_pipeline.py --basetemp=<RUN>/pytest --tb=short，211 passed/16.09秒/exit0，进程16.686秒。CUDA不可见、OMP4、HF/Transformers离线，无依赖安装，无真实UI人工审批、媒体处理或GPU。

报告report.json SHA4f77f1bb83de228ea72abe0b7094180a4c3eb4bfa1b0a1daa5bd4ca822b79f3e；日志linux-tests.log SHAa30954db7b037749600abc3d50f9b150672d87c9fdccc497bb57c380952d5a55；Mac副本/private/tmp/mvllm2-m7c-evidence-20260912。本批完成只涵盖两UI入口及文档，剩余7个辅助CLI和最终审查不自动完成；旧源、模型、训练与full/holdout等限制保留。轻量证据文档在实际Linux原子提交，再核对docs-only增量bundle回传Mac，提交由git log追溯。

独立reviewer只读取得两端报告/日志原始字节，完全一致且报告内日志SHA正确；核对指定命令、环境与结果记录，实时隔离09035fd4 tracked clean、Python3.11.16、正式main clean@f1b7d8a3，通过Linux轻量证据范围，无finding。未复跑；历史环境/退出码/耗时依据报告和日志，实时查询不重建历史进程。

## 37. M7d剩余数据辅助CLI退役（本批完成）

基线5c650814。逐文件检查7个ROI/候选/队列脚本及全局引用，versioning和pipeline业务不调用这些CLI；新七阶段直接执行run_input_*与共享原语。公开main及脚本/模块在业务导入前停止，无legacy、check-only或dry-run绕过；原main改为私有，历史解析器与业务函数保留。精确新增文件范围先补Plan，再实现。

新增7项先RED：7 failed/44 deselected/0.49秒（/private/tmp/mvllm2-m7d-red.log）；8文件联合257 passed/10 skipped/16.71秒/exit0（/private/tmp/mvllm2-m7d-regression.log），包括84次Python -S脚本/模块边界调用、历史CLI解析与完整新数据链。10个skip源自候选计划测试所需历史数据缺失，不算通过；其中旧dry-run测试现明确调用私有main。随后文档/历史测试同步的最终核查另记。

脚本索引、数据手册、项目指南、架构及入口清单同步退役状态；B0–B12历史台账仅加后续任务路由，不改历史数字。旧服务手册仅加历史适用范围提示与现行alias入口链接，不修改历史效果证据。索引工具/库保留实际引用，不声明整包退役。独立审查与Linux复验待执行；无真实媒体/GPU/新人工审批。

扩展只读入口核查发现pipeline/prompt_control/__main__.py仍公开提供publish并调用core.publish_prompt写旧registry；此路径未列入前序数据辅助7项清单，需作为M7后续前置核定并补精确Plan，不能宣布M7全部完成。build_artifact_index.py当前仅按历史集合生成INDEX.md总览，仍使用current_data_context默认根；底层集合库保留依赖，后续区分历史审计输出与正式身份写入，不贸然删除。

独立reviewer最终8文件257 passed/10 skipped/16.45秒/exit0，AST确认7脚本全部原函数体保持（main仅改名）；额外28次Python -S脚本/模块dry-run及混合help/legacy全部退出2，结合回归84次无绕过。独立代码、调用关系、文档历史/现行范围及未完成条目核查通过，无finding。10项历史fixture缺失未动态验收。Linux复验拟在既有隔离checkout新m7d-aux-entry-verification-20260912输出，以.venv-m3、CUDA不可见/OMP4/离线运行同8文件，不安装依赖、不执行真实媒体。同步前两端任务HEAD5c650814，隔离tracked clean、正式main clean@f1b7d8a3，新RUN不存在。

### 37.1 Linux隔离回归

实现15b440095e8f64f879cdd1c1d93410992006a6df在Mac提交；增量bundle两端SHAe01a5ecc232c82b6de1a97779140a6ebe78e88bf6de395f596d733a59ee158e3，verify通过、祖先和0/1差异检查后cherry-pick --ff同步同一对象。

训练机输出/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m7d-aux-entry-verification-20260912。实际.venv-m3/bin/python（3.11.16）运行上述相同8文件pytest -q，--basetemp=<RUN>/pytest --tb=short，257 passed/10 skipped/19.62秒/exit0，进程20.275秒。CUDA不可见、OMP4、HF/Transformers离线，无新依赖或真实媒体处理。候选计划10项仍因历史fixture缺失skip，不能作为该历史环境通过。

report.json SHA15fe53f516869216d4999d2319be11b789a52e6bdae09494759c418cc08022f9；linux-tests.log SHAde78b485f7d23462ed2e3effd99dbb776bfd67632fea28735d16c19a79b2e80b，Mac副本/private/tmp/mvllm2-m7d-evidence-20260912。M7d本批只关闭7个辅助CLI及对应文档；旧Prompt发布入口为M7完成前置，索引工具和底层库按实际用途核定；M8、真实模型训练/评测、full/holdout输入、大型硬盘等原限制不因此关闭。轻量证据三文件在实际Linux提交，随后验签docs-only增量bundle回传Mac，提交由git log追溯。

独立reviewer读取两端报告985字节/日志353字节，逐字节及SHA一致、报告内日志SHA正确；核对8文件命令、环境、结果和计时口径，实时隔离15b44009 tracked clean、Python3.11.16、正式main clean@f1b7d8a3，通过Linux轻量证据范围，无finding。未复跑；历史执行环境/退出码/耗时依据报告和日志，跳过项及真实运行未验证。

## 38. M7e旧Prompt入口与历史索引边界（本批完成）

基线f293df3a。旧Prompt公开validate/publish及脚本/模块入口停止，旧main私有保留；core/__init__导出不改。模块启动仍加载既有包定义/PyYAML，不要求-S模块无依赖退出；实际main在parse_args/source读取/publish前拒绝。新versioning Prompt注册、读取、冻结和复验保持原实现。历史build_artifact_index保留仅写INDEX.md，但必填现存data-root并移除current选择；不更新集合index/LATEST或创建新版本。

7项新增回归先RED（7 failed/19 deselected/0.27秒，/private/tmp/mvllm2-m7e-red.log）；四文件联合179 passed/1.37秒/exit0（tests/test_prompt_control.py、tests/test_artifact_index.py、tests/versioning/test_prompts.py、tests/versioning/test_cli.py，/private/tmp/mvllm2-m7e-regression.log）。包含旧source/publish前拦截、脚本与模块无写入、新Prompt及CLI回归、历史索引实际输出。均本机轻量合成，无真实媒体/GPU。

versioning说明补Prompt定义→create→正式文件→freeze/verify→训练引用，并将过期legacy保持原样Contract同步为已批准逐入口退役约束、记录D001原因；旧PromptREADME只加历史范围，其他导航同步。M7e精确文件先补Plan再实施；独立审查和Linux复验待执行，M8完整差异/验收矩阵仍待推进。

代码引用复核：除core定义外，publish_prompt调用仅剩已私有化旧main；build_index仅由显式根main调用。Linux计划为既有隔离checkout新m7e-prompt-index-verification-20260912，以.venv-m3、CUDA不可见/OMP4/离线执行上述四文件，不安装依赖、不处理正式数据；同步前两端f293df3a、隔离tracked clean、正式main clean@f1b7d8a3，新RUN不存在。

独立reviewer四文件179 passed/1.20秒/exit0；AST确认旧Prompt解析/旧main及历史索引收集/渲染/生成逻辑保持，core/__init__无改动。按文档在独立临时目录实际运行create→show→freeze→verify均exit0，正式和冻结副本路径/字节一致。代码、文档Contract/链路及范围核查通过，无finding；合成Prompt不代表实际训练，未远程/GPU。

### 38.1 Linux隔离复验

实现cc02acc1abd9307dfc46191aa83962ae3d3e8c3c在Mac提交；增量bundle两端SHA36d7f72e71f8b5a05ac4586c3dd3e6a679bee4957ca57fa15509df0d7762d55a，verify通过、祖先及0/1差异检查后cherry-pick --ff同步同一对象。

输出/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m7e-prompt-index-verification-20260912。使用.venv-m3/bin/python（3.11.16）运行pytest -q tests/test_prompt_control.py tests/test_artifact_index.py tests/versioning/test_prompts.py tests/versioning/test_cli.py --basetemp=<RUN>/pytest --tb=short，179 passed/1.11秒/exit0，进程1.488秒。CUDA不可见、OMP4、HF/Transformers离线，无依赖安装、真实媒体/GPU。

report.json SHAe2811f9c476a974b639316c0f61724ba067909fde8faf2d98c71b07d1b6195c1；linux-tests.log SHA8afcd40b5d3f5c2fd044ba1bc0634f8fcc7bdab408450fe7ccf985baf2dfaa88；Mac副本/private/tmp/mvllm2-m7e-evidence-20260912。M7a–e入口与文档切片完成，下一步M8整体Spec验收矩阵/源保护/Codeup main完整差异审查及交付；切片通过不代替整体审查，不关闭真实训练/评测、full/holdout输入或大型硬盘等原缺口。轻量证据在实际Linux提交后以docs-only验签bundle回传，提交由git log追溯。

独立reviewer读取两端报告779字节/日志260字节，逐字节及SHA一致、报告内日志SHA正确；核对4文件命令/环境/结果/耗时，实时隔离cc02acc1 tracked clean、Python3.11.16、正式main clean@f1b7d8a3，通过Linux轻量证据范围，无finding。未复跑，历史执行环境/退出码/耗时依据报告与日志，不外推真实媒体/GPU。


<a id="m8-audit-20260913"></a>
## 39. M8整体审查、不可变Prompt与训练半提交修复（2026-09-13）

### 审查基线与范围

执行者Codex。Mac任务分支`refactor/2026-09-07-readable-version-control-migration`冻结于
`0963642bdb47c87af0df78b809a2262ee7e1ea30`；Codeup `main`经本轮远端只读查询仍为
`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，两侧独有提交计数0/117，差异148文件、76054行新增/456行删除。
本地main `cc59312c`原有6个独有提交（cc59312c、f8209b61、d8cba46a、7b8192bd、8acaf2cf、cdb8632c）
全部纳入范围，不能只审查Task Artifact之后的提交。

独立reviewer `review_m8_full_diff`按冻结差异核查Spec、入口、Registry、状态、不可变发布、备份及原6提交，
在隔离临时对象上独立复现下列4项。结论为**驳回修改**；风险抽样审查不宣称逐行证明76k行新增内容。

| 固定问题标识 | 优先级/已证实问题 | 当前动作与验收 |
| --- | --- | --- |
| M8-R1 | P1：公开train/eval手工状态命令不执行训练/推理、不产生冻结input或权重，仍可通过model register/finalize及candidate alias；Registry只核状态元数据 | 未解决，列为当前前置。须同时封住公开手工绕过和已有状态齐全但缺产物的记录；实际执行器保留。不能仅删除CLI后称证据门完成 |
| M8-R2 | P2：Prompt同ID并发create双成功，后者覆盖先者；freeze同类窗口 | 本轮create/freeze均改完整临时文件加原子排他link发布，冲突返回PromptConflict，赢家正文保持。新增2条确定性并发回归 |
| M8-R3 | P2：train完成先写workflow_state后终止Run，I/O中断留下completed/RUNNING，同目标无法重试 | 本轮仅对同目标completed/RUNNING补完原Run，恢复前重验父记录及三折/summary门；普通读取、非法目标及已完成自环不放宽。新增中断恢复与缺折拒绝2条回归 |
| M8-R4 | P2：改根隔离恢复后SQLite仍保留旧artifact URI；使模拟原源不可达后，恢复目录虽有文件仍下载失败 | 未解决，已证实实现缺口。先前第33节原绝对路径恢复证据不作废，但不能解释为任意隔离路径可恢复；真实硬盘仍单独未验证 |

R1独立复现脚本`/tmp/m8_reviewer_probe.py`通过`versioning.cli.main`顺序执行：Prompt create/freeze →
train create → 三折fold-start/fold-end → summary/complete → model register → eval create/fold-start/fold-end/summary/complete
（outcome=passed）→ model finalize/scope(adapter)/alias(candidate)。输入base_model、eval config和结果引用均不存在；
最终actual_model_files为空、training_frozen_manifest=false，get_model_by_alias仍返回candidate。
该复现不调用训练器和推理器。R2/R3脚本`/tmp/m8_reviewer_edges.py`分别用屏障并发发布、set_terminated一次I/O故障复现。
R4脚本`/tmp/m8_reviewer_restore.py`仅临时移动并恢复它自己创建的模拟原源；未操作真实模型或数据。
脚本临时路径只作本轮复核入口，长期修复验收以仓库回归测试及本节记录为准。

另有待确认线索：已通过eval与服务实际权重清单的绑定需在R1修复时构造内容漂移反例验证。
独立reviewer未完成这一反例，不把它写成已证实问题。`history-summary.yaml`实物缺失则由主Agent直接盘点确认；
其构建器测试不代表本次历史对象整理已落盘。

### 本机测试与修复边界

- 基线整仓CPU命令：`CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q tests --basetemp=/private/tmp/mvllm2-m8-full-20260913 --tb=short`。
  输出`2603 passed, 11 skipped in 322.11s`、正常退出0；日志`/private/tmp/mvllm2-m8-full-20260913.log`。11项skip为既有历史fixture缺失。这是主Agent本轮执行，reviewer仅引用，不是其复跑。
- R2先运行新增create/freeze并发回归，2 failed，均观察到两个published；修复后Prompt及migration联合292 passed。
- R3先注入终止中断和缺折恢复，两项均RED（IllegalStateCombination，尚无恢复分支）；随后补实现。
- 最终本机联合：`.venv/bin/python -m pytest -q tests/versioning/test_mlflow_train.py tests/versioning/test_prompts.py tests/versioning/test_migration.py tests/test_train_with_contract.py --basetemp=/private/tmp/mvllm2-m8-repairs-green --tb=short`，
  `466 passed in 44.08s`、正常退出0，日志`/private/tmp/mvllm2-m8-repairs-green.log`。
- R2/R3最终独立reviewer复跑Prompt/train两文件：251 passed，41.55秒，退出0；额外缺summary、错误run_status、半提交改向及完成后自环均拒绝，专项复审通过。训练机同组466项通过，见本节末尾。本轮修复不涉及R1/R4，不能据466项通过关闭M8。

### 训练机原对象与物理存储根复核

本轮仅SSH只读：原项目`/home/liuyang/文档/mVllm_2`为干净`main@f1b7d8a3`；隔离项目
`/home/liuyang/文档/mVllm_2-migration-7eeb93a7`为任务分支`0963642b`，tracked干净，原环境和M3–M7验证目录均保留。
没有加载权重、执行GPU/训练/评分，未写原项目、更新指针或修改source。

初次探测误用了release根下`manifest.json`，该路径不存在；随后按source-inventory声明的
`manifest/release_manifest.json`复核成功，不能将初次路径错误解释为源对象丢失。
两份正确源manifest的SHA与M0/M3一致：
- 760050fad303：`c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`；3846字节。
- ecb5aeb9657c：`ba61695cdc78fcdbfe55f7cc6a1474235709aee4c798abc98905f35a8d34d65b`；4986字节。

当前旧Prompt `manifest.json` SHA为`de737c67149b58e1f5ae2f9ce493287237eabc83aa88f8d4935011eff0402e5d`，
`prompt.yaml`为`8870c537bea1fb86b0c2419555c279e934227e4602d1c2f724438b9cc6e460af`；
隔离checkout内新Prompt为`907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`，均与第27节一致。
原模型Registry manifest仍为`3d3fbd91be5cdb7a55aa729ebd7066f8c247ed18f10fa17bf3dc677787bb6008`。
旧数据指针SHA `66770b94e9762e56bce5aea00a0e407d80b7bc7f606e2c0bc73121ed6845da73`、旧模型指针SHA
`ec9b876b15c1ac964e50bc1950eadad52cd472676096c60f5b3b971227f54bb8`为本轮只读快照；未另做历史摘要对比，不扩大为所有原对象不变的完整证明。

`/data/mVllm_2/data/releases/data-v4.1-r1/r2/release.yaml`存在；各SHA为
`7bbbf15f350c17d522fa33b9052d9fafc5279f70343980d84ee8b419a124940f` / `3a42da0db7837c3a21d36d923a428b1b009f7b2d7b00bde7cf7ecafab84f0039`。
该根下`records/prompts/prompt-v4.1-r1.yaml`不存在；Git Prompt已迁移与`/data`训练输入是否备齐是不同事实。
完整只读JSON保留于`/private/tmp/mvllm2-m8-source-audit-20260913.json`。本轮未重算20个payload和全部外部媒体摘要，前序真实验证仍按原章节归因。


### 历史汇总只读试构建（未发布正式历史文档）

使用训练机隔离代码`2b8cbc89`的`build_history_summary`纯构建API：对原项目声明3个Prompt、6个有权重run、
1个缺失run、2个prepare-only及1个旧Registry模型；对隔离checkout中明确声明的5个归档eval包另行构建。
18项均保留原ID，未分配新train/model/eval身份，未创建或修改任何Run，未调用固定路径history-write。
API返回值经SSH写入Mac临时`/private/tmp/mvllm2-m8-history-probe-20260913.json`（65699字节）。

3个Prompt各取得6个有来源事实；旧Registry模型16个有来源事实、1个unknown；5个eval摘要共54个已知字段、6个unknown。
6个权重run各取得3个目录结构事实，但9个核心参数均unknown：原项目root不存在已提交到任务分支的归档包，
构建器单root定位无法同时取得原权重观察/adapter_config与隔离checkout归档资料。缺失run的12个字段保留unknown，
2个prepare-only各9个参数保留unknown。**这些unknown是本次来源布局导致的提取缺口，不是已证明历史参数不存在。**
下一批须按既有归档文件清单校验跨根来源并保留字段provenance后再发布history-summary；不能把这次临时JSON当作完成的交付物，
也不能为运行构建器向原正式checkout复制归档或制作虚假权重占位文件。


### Linux修复验证与同步

代码提交`2b8cbc891d12282dfc4f55a6f0aa45d6714cd22f`，四文件实现/测试范围，已通过Mac专项及独立复审。
增量bundle SHA为`63cada6811cf74d7c08a8f8a1634cf75caa6e12bdf963aa2eab1d7d86b289f71`。
首次用纯SHA范围生成bundle被Git拒绝为空，未触碰训练机；改用具名`HEAD ^0963642b`成功生成。
传输前后检查分支、HEAD、tracked修改、bundle摘要、依赖及祖先关系，0/1后仅`cherry-pick --ff`隔离分支。

训练机`m8-verification-20260913/`为本轮新建且冲突即停的隔离证据目录，保存`code.bundle`、`sync.json`、
`pytest.log`及`result.json`；`.venv-m3/bin/python`运行与Mac相同四份测试文件，
`CUDA_VISIBLE_DEVICES=''`、`OMP_NUM_THREADS=4`、HF/Transformers offline。
结果`466 passed in 92.12s`，进程正常退出0；含解释器与MLflow初始化的命令耗时105.20秒。
日志SHA为`0e9ed84d5630e6e84b9905cdb183e7d4ac5d0b425501f73f2415b73a425c6d55`。
实现SHA与reviewer本机复审一致：Prompt `e6f5752d0a3ec1d785b058b4694bb9b8c82189d730cf57a0b0e8945ed4fea955`，
train `a88808252daf89f33c133f3951cbdf38731eb2f75a29b1e456dd82cdb8932d53`。
Linux验证后tracked干净；无安装、GPU训练/推理、真实完整评分、原源写入、merge或push。
R2/R3在本轮指定范围解决，R1/R4和历史汇总仍未解决，最终整体审查结论继续为驳回修改。
本节与台账/Plan/交接的同次轻量证据提交由`git log -- docs/results/version-control-migration/verification.md`追溯。


<a id="m8-r1-evidence-20260913"></a>
## 40. M8-R1 正式晋级必须具有实际执行证据（2026-09-13）

本轮从`b1887b26c97a83d63e30c05a109fa7772fc1e531`继续用户已授权实施，修复第39节R1。
代码提交为`3b63aa52c79267376d6274cedf77f13df16f53ec`（Mac），本节轻量证据提交由本文件Git历史追溯；未push/merge。

### 实现与证据边界

- 公共手工train `create/fold-start/fold-end/summary/complete`及eval对应动作（含aggregate和旧manifest）在store创建前拒绝，提示实际prepare/validate/run/export。底层Python记录与holdout授权API保留；旧completed/passed记录缺少实际产物也无法通过Registry。
- 训练准备冻结视频及基座全部文件SHA/大小，Run创建前、每折前后复验。实际三折上传后核对adapter权重、配置、train_results与Run指标，生成父Run的`training-evidence.json`并用不可改写param钉扎摘要；完成导出仍复验所有折。
- Registry登记、模型manifest及物化复验训练血缘、冻结输入、证据和声明权重的完整子树。下游不要求恢复未声明折权重，仍核对被钉扎的三折事实与指标。adapter还必须对应实际训练时的基座。
- 正式评测结论门只读核验冻结input、实现摘要、逐样本records/failures/summary，重新计算严格评分与outcome，核对实际被评权重。single_fold所选artifact必须等于deploy_target；finalize、alias读写、服务入口和已绑定eval的model manifest复用该门，没有export递归。
- 备份按原声明范围保留权重，增加轻量训练input/proof。新实际CLI闭环先model manifest、再current、最后backup create/verify，明确断言fold0在位而fold1/2权重不在备份。
- 旧prepared若缺基座清单、旧completed若缺执行证据都会拒绝；不能倒填成功证据或覆盖旧冻结版本。代码/输入变化须重新准备新完整身份。基座校验增加CPU流式I/O，未加载推理模型。

### Mac测试与独立复核

主Agent先运行无证据训练及手工CLI拒绝回归，原行为3 failed；修复后首轮81 passed。
实际执行链逐步升级fixture：训练器/推理器为CPU替身，数据准备、实际执行器、MLflow、证据门、Registry、服务及备份直接调用实现。
中间失败均保留于`/private/tmp/mvllm2-r1-*.log`，包含旧Prompt fixture不匹配、较早漂移拒绝改变错误文本、测试未先生成manifest等；不将中间失败写为最终通过。

三个旧政策模块`tests/versioning/test_registry.py`、`test_materialize.py`、`test_backup.py`仅在各自模块内替换三项证据validator，以保留状态/保留策略故障测试；这些测试不证明实际执行证据。
主Agent政策组含`test_manifest.py`共413 passed，162.64秒；实际证据、服务和E2E测试不使用上述替身。

主Agent实际链专项：`tests/test_train_with_contract.py tests/test_eval_run.py tests/test_serve_smoke.py tests/versioning/test_cli.py tests/versioning/test_cli_holdout.py tests/versioning/test_e2e.py`，
153 passed/1 skipped，56.26秒，正常退出0；日志`/private/tmp/mvllm2-r1-execution-pass.log`。skip为既有历史数据fixture缺失。
本机整仓CPU最终命令：`CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q tests --basetemp=/private/tmp/mvllm2-r1-full-20260913 --tb=short`。
结果2623 passed/11 skipped，502.13秒，进程正常退出0；日志`/private/tmp/mvllm2-r1-full-20260913.log`。summary后Python退出清理仍耗时，已等待真实exit0；11项skip为既有历史fixture缺失。整仓包含最后的备份范围断言与测试导入整理。Linux最终结果见本节末尾；CPU结果不代替真实GPU证据。

独立reviewer发现并复现三项：训练后首次eval前基座可替换、adapter评测可晋级未评merged、选择性保留后删除声明weights仍能登记。修复分别为冻结基座、single_fold被评路径=deploy_target、声明完整子树全等。
reviewer独立16例首轮15 passed/1 failed（12.29秒）；唯一失败为新测试current先于manifest，修正顺序后该例1 passed（5.80秒）。
另独立攻击旧passed模型的deploy_target漂移，alias读取与finalize重试均拒绝，未改alias或增加ModelVersion；exit0。
独立实际备份39文件，input/proof/fold0在位且无fold1/2 adapter，create/verify均0。
reviewer对R1代码及`versioning/SCRIPTS.md`、`docs/DATA_PROCESSING_RUNBOOK.md`局部审查通过，无残留可执行问题；主Agent广回归不记为reviewer复跑。

审查最终SHA：registry `500feb5bd8edf266bc76e6b7af2f961c624565cfd57d94e06a06747382a92aee`；
train_prepare `2946e882b7914f611d4de761174540129e3c1483032bc10809e3767e7eee5854`；
eval_run `1e598fb0e8b138dfbc10a3be1733c24c0c661adafb0e20c1650c091858cbe3e8`；
backup `f525e17e19c2309464fc336feca32c6c951df289e4e98b52414911eaa33f4538`。

### 训练机边界与未完成项

本轮同步前SSH只读复核：原项目`main@f1b7d8a3`干净，隔离任务分支`b1887b26`tracked干净；旧环境及m3–m8证据目录保留。
本轮已将代码3b63aa52以bundle快进隔离分支，增量bundle SHA为`9d354ae51b7f48a93f3b7247bc762a569bf1a5c21308241ab283fd3da56da063`；同步前后核对HEAD/分支/tracked修改、摘要、bundle依赖及0/1独有提交后，使用`cherry-pick --ff`。
合成CPU回归写入新`m8-r1-verification-20260913/`；执行前估计约10分钟、数百MB临时产物，首轮资源失败及后续重跑耗时单列。不读取真实权重或受限测试集。
R4异根恢复、history-summary实物、物理`/data`下Prompt备齐、full/holdout实际接线及真实模型/GPU成功证据仍未完成。M8整体验收继续进行中，不能因R1局部通过而关闭。


Linux首轮12文件同进程回归未正常完成：默认RLIMIT_NOFILE为soft1024/hard1048576，约60%后出现批量setup错误，pytest收尾报`OSError: [Errno 24] Too many open files`，exit1，410.69秒；没有可用最终通过汇总。
失败日志`m8-r1-verification-20260913/pytest.log`与`result.json`保留，日志SHA `15fe1552e4dc93588f7247b48eb9e04f4401300dc561d369f35cd3e80a7ac4be`。
该单进程创建大量独立临时MLflow/SQLite store；后续保持1024软限制和相同已提交代码，把原12文件按实际执行6文件、策略4文件、底层状态2文件分为三个独立pytest进程，隔离进程级store缓存。不修改系统限制或安装依赖；最终结果另记，不覆盖首轮失败。

训练机已安装MLflow实现的`mlflow/store/tracking/sqlalchemy_store.py:327–339`使用进程级`_engine_map`按数据库URI缓存engine；本次测试不断生成新临时URI，分进程会释放这些资源。该代码观察支持测试资源累积解释，不证明长期真实服务的句柄使用已完成验收。


### Linux最终分组结果与R1结论

同一代码`3b63aa52`、默认NOFILE soft1024/hard1048576，复用`.venv-m3`及前轮`m5-service-verification-20260912/dependencies`中的httpx；没有安装或升级依赖。
三组都设置`CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`，每组新的`pytest-<组名>`临时目录。

- execution：`153 passed, 1 skipped in 87.09s (0:01:27)`，命令耗时93.44秒，exit0；日志`execution.log`，SHA `0aee17589451abd2d59325741eed5be922a050a393267d57be3efa7105185f38`。

- policy：`413 passed in 254.68s (0:04:14)`，命令耗时282.74秒，exit0；日志`policy.log`，SHA `0f742ec71e6d0791ca0c93b1b355b9221ee0d06f02148ef9f87e88d93ef2d924`。

- state：`390 passed in 267.12s (0:04:27)`，命令耗时301.75秒，exit0；日志`state.log`，SHA `0a60c5d0c1b9dfa5d43a1c706ed5518c78ef96b6bd0d4447e34d21febd150617`。

三组共956 passed/1 skipped。execution为上述实际链6文件，policy为上述策略4文件，state为`tests/versioning/test_mlflow_train.py tests/versioning/test_mlflow_eval.py`；与首轮12文件完全一致。
完整命令、环境、SHA及结果保存在训练机`m8-r1-verification-20260913/grouped-result.json`，各组还有独立`<组名>-result.json`；本机留存`/private/tmp/mvllm2-r1-grouped-result.json`。
全部测试进程真实正常退出0，最终tracked干净，四份关键实现SHA与独立reviewer及Mac提交一致。首轮pytest.log/result.json未覆盖。

M8-R1已解决本轮范围（代码3b63aa52）：Mac整仓2623 passed/11 skipped，Linux分三进程956 passed/1 skipped、各exit0，独立代码/操作文档局部审查通过。首次Linux单进程回归触及1024文件句柄上限而exit1，已保留日志；相同代码及原限额分组复验通过，不能外推长期服务资源验收。完整证据见verification第40节。下一步M8-R4异根恢复、history-summary实物与最终整包复审；真实GPU/full/holdout及物理存储缺口保持，M8整体不关闭。

最终独立证据核查通过：reviewer只读核对三组日志SHA/汇总/退出码、相同12文件集合、两端代码和Git状态，并确认此前P3文档状态冲突已闭环，没有把本机测试或主Agent执行冒记为独立复跑。
两端`grouped-result.json`共同SHA为`90a9fccb2fe7e6b8141322e87ce670f079939184cc9c1876a08b9bcc62866ec2`。四份轻量证据文档在训练机按核对过的原/新SHA写入并提交，随后通过增量bundle同步回Mac；同次提交版本由本文件Git历史追溯。


<a id="m8-r4-restore-20260913"></a>
## 41. M8-R4：异根恢复的MLflow地址重定位（2026-09-13）

基线`7bea45330d6743b90adc845c09503366958620d0`。本轮只实现已授权的隔离恢复，不读取真实权重/受限测试语义结果，不移动、删除或覆盖原正式store。原模拟store不可访问的RED已复现：实际执行证据门在`_run_artifact_root`找回旧地址并拒绝；日志`/private/tmp/mvllm2-r4-red.log`，1 failed，6.73秒。

### 实现与验收范围

`versioning/backup.py`在任何对象写入前读取已验签SQLite，按catalog源store规划五类活动存储地址的重定位：`experiments.artifact_location`、`runs.artifact_uri`、`model_versions.source`/`storage_location`及存在时的`logged_models.artifact_location`。本地路径转为新artifact根的file URI；合法已知Run的runs URI按MLflow的原始path语义校验并保留。没有Run或logged-model的Default空占位例外落到新根`artifacts/0`；其他越界、网络/未知地址均拒绝。映射只应用在恢复私有副本，原快照保持字节不变。

恢复预检拒绝软链接/特殊输入、目标重叠与冲突。各目标路径同级暂存并以no-replace发布，模型实体目录和manifest分两次发布；保留数据封存权限，只对预检见到的同一空MLflow目录使用rmdir。四个根不是整体事务，晚期I/O或竞态失败可能保留此前已发布对象，已有对象不会自动回滚或覆盖。该语义与外部依赖边界已写入`versioning/SCRIPTS.md`。

实际执行链测试复用R1 CPU训练/推理进程替身，调用真实prepare/run/finalize/alias/backup入口，未替换实际证据validator。测试仅移动自己创建的tmp/store，保留外部合成基座/媒体。恢复到含空格新路径后：原store仍不可访问；SQLite全部原表行除允许地址列外全等；alias和ModelVersion身份保持；Run artifact与ModelVersion下载定位新根；显式model current及开发服务准入通过；新Run日志artifact写到新根；可再次create/verify备份。它证明store级恢复和服务准入，不证明真实推理或所有外部依赖可迁移。

### Mac验证与独立核查

主Agent使用`.venv/bin/python`，设置`CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。
受影响三文件命令：`-m pytest -q tests/versioning/test_backup.py tests/test_eval_run.py tests/versioning/test_cli.py --basetemp=/private/tmp/mvllm2-r4-stable --tb=short`，175 passed/1 skipped，96.72秒，exit0；日志`/private/tmp/mvllm2-r4-stable.log`。skip为既有历史数据fixture缺失。
该进程已包含软链接拒绝、SQLite事实全等与第二次备份，尚未包含最后的runs URI严格化；该局部变更另跑`tests/versioning/test_backup.py -k literal_mlflow --basetemp=/private/tmp/mvllm2-r4-uri`，6 passed/72 deselected，6.99秒，exit0；日志`/private/tmp/mvllm2-r4-uri.log`。不冒称本轮整仓重跑；前轮R1整仓证据见第40节。

独立reviewer先复现并推动修复三类问题：Mac封存目录rename需owner-write、同字节外链备份能被解引用、runs URI经规范化后被错误接受。修复分别为持目录inode fd临时修改发布权限并恢复、restore入口普通树预检、按MLflow原始Run ID精确校验。中间10 passed/1 failed的Mac发布失败及主Agent早期current未显式激活的1 failed/3 passed保留，不计为通过。
reviewer独立实际链及四类并发目标保护5 passed（7.00秒），四类外链/特殊输入4 passed（4.42秒）；独立比较59张表111条原始行，除五类地址外保留全部事实，实际测试新写入仅另增Run/tag。最终runs URI六例及完整异根链由reviewer独立复跑7 passed，9.40秒，exit0；分组有重叠，不合并计数。代码与操作说明局部审查通过，无待修复可执行问题；该次局部审查时Linux尚未执行，最终结果另见本节末尾。

### 跨机执行前记录与限制

SSH预检原项目`main@f1b7d8a3`干净；隔离任务分支`7bea4533`tracked干净，既有环境与证据目录保留。新验证目录`m8-r4-verification-20260913/`不存在，复用`.venv-m3`和前轮service dependencies，不安装依赖或更改系统限制。当时计划以同一代码运行三文件CPU回归，未提前标已解决；执行后结果见下文。
真实移动硬盘/大型模型、外部基座/媒体整机恢复及GPU推理未验收。原冻结训练/评测内容与基座引用保留原文；历史汇总实物、物理/data下Prompt备齐、full/holdout实际输入与M8最终整包复审继续保留。

Mac代码提交`2fce3ab13afa1af02b9f4e2d03e8bf32085e805e`，含backup实现、两份测试与操作索引。增量bundle SHA `08d5b0fbb12389ee0782d9bf9203455d2df1cc3e2eed5afb0e2a6f4212b27c6c`；训练机同步脚本核对7bea4533基线、tracked干净、bundle依赖及0/1独有提交后用cherry-pick --ff同步。仅隔离checkout写入，原项目保持只读。

### Linux最终结果与R4结论

同一代码`2fce3ab13afa1af02b9f4e2d03e8bf32085e805e`，CPU环境与命令完整记录于训练机隔离目录`m8-r4-verification-20260913/result.json`；命令为`.venv-m3/bin/python -m pytest -q tests/versioning/test_backup.py tests/test_eval_run.py tests/versioning/test_cli.py --basetemp=<RUN>/pytest --tb=short`。复用前轮httpx依赖目录，CUDA不可见、OMP4、HF/Transformers离线。

最终汇总：`181 passed, 1 skipped in 175.94s (0:02:55)`。

进程正常退出0，外围耗时187.33秒，NOFILE soft1024/hard1048576，最终tracked干净；本轮未调整系统限制。最终181项含最后runs URI六例、链接/竞态拒绝和完整新根链。日志`pytest.log` SHA `23b64ffff3c9f2c69e81015a1ae7230deca182dedb57a6459731104d700e4a5e`；报告两端SHA `85f8b4b24e8327fea3f9a1e77ce163e3c07db8255163c08cd7ebe687c1eb2833`，本机副本`/private/tmp/mvllm2-r4-result.json`及`/private/tmp/mvllm2-r4-linux.log`。

代码/测试/操作索引SHA与reviewer最终核查及两端提交相同：

- `versioning/backup.py`：`1dff40c9715862e9c4d420b6f1838d8043c2935593ca9bd1a1ab576e9442785d`。
- `versioning/SCRIPTS.md`：`296f5b70f8a2fb20b426fccef853df30b2a25aff95adc37a446e96770b61f015`。
- `tests/versioning/test_backup.py`：`a0d025d777b0758f73d8cfcc9670abf8d4f7d8b2deb38ef850459c1cfb8ac9f2`。
- `tests/test_eval_run.py`：`eb6ca38a0f4d2b17085f073caa3447615b60c2eef031a201ad13ed5a580fbb80`。

M8-R4已解决本轮store级异根恢复范围（代码2fce3ab1）：Mac受影响回归175 passed/1 skipped，最后URI严格化另6 passed；Linux最终同一提交181 passed/1 skipped、exit0；独立代码/操作文档局部审查通过。原模拟store不可访问时，新根artifact读取、显式current/服务准入、后续写入与再次备份均通过；冻结事实和原备份保持。验证见第41节；真实硬盘/大型产物、外部依赖整机恢复与GPU不在通过范围。下一步补实际history-summary并做M8最终整包复审，整体迁移不关闭。

最终Linux证据与四份文档独立只读核查通过：reviewer核对两端原始报告/日志及摘要、HEAD/四文件摘要、汇总/退出码/NOFILE与原项目和隔离checkout状态，无新增可执行问题。以上Linux执行由主Agent完成，不计作reviewer复跑；局部通过不代表M8整包通过。四份轻量文档在训练机按明确旧/新摘要写入并原子提交，再通过bundle同步Mac；同次提交版本由相关文件Git历史追溯。


<a id="m8-history-20260913"></a>
## 42. M8实际历史汇总交付与batch来源修正（2026-09-13）

本轮承接`a14b3d0ae252c91368b2e0d3608b215ab81bd6ee`，按已确认Spec整理历史查询事实，不创建正式train/model/eval，不触发模型晋级。训练机原项目`/home/liuyang/文档/mVllm_2`的main仍为`f1b7d8a3`且干净；隔离checkout开始为相同任务分支`a14b3d0a`、tracked干净。原项目没有Git归档包，隔离checkout有五个归档包但没有workspace/runs；两种根不互相冒充。

### 产物及完整性

固定输出为本目录`history-summary.yaml`，已审发布字节SHA `fb9dc8d25b00dc9b774680db938c2f8a8bc172119ad1111d6bf26b4182382a12`，21个唯一条目、234个有来源值与152个有原因的未知字段。所有条目保持`history_only: true`、`formal_identity: none`。

基础18条包括3个Prompt、6个有权重观察run、2个仅准备run、1个权重路径缺口run、1个Registry发布模型和5个归档eval。另保留coverage-first seed3407两份不同契约的已有eval，以及concise-cv报告声明条目，共21条。两个data旧ID及已确认r1/r2映射只作来源关联，不改绑历史训练输入。

两组prepared的当前目录与input/summary.json experiment_id使用`v4.1-prompt-concise-v1-seed3411`/`v4.1-prompt-concise-v2-seed3411`；M0 inventory的`v1/seed3411`、`v2/seed3411`拼写作为历史标签另存，不新建实验或静默丢弃旧标签。现场目录与无权重命名文件的观察随产物保存。

汇总逐字段保留root、相对路径、摘要或未知原因；generation记录47份实际读取的轻量源文件size/SHA、权重stat、生成时间、代码提交与生成脚本位置/摘要。六组权重只做存在性、文件大小、mtime与已限定merged链接链观察，没有读取权重字节或重算权重SHA。归档里的旧权重SHA明确为来源声明，不能当成本轮完整性验签。

五份归档eval都没有split，继续未知。两个source-aware契约摘要为47e393…b937，其余三份为3798f0…38ab，分别保存；JSON比例保留0–1，报告百分数保留0–100。seed3407额外两eval按各自summary/run_identity交叉核对，并将评估model_dir与Registry冻结merged路径、origin数据/fold绑定，保留旧路径，不改写为当前物理目录。concise-cv原声明run路径仍不可见，报告中的完成、质量未达标和当时待独立审查均标为历史报告声明，不能替代当前运行或权重证据。

发布模型关联delivery model/service/deployment历史声明，保留production_approved=false和质量门未通过；其中artifact/runtime历史passed不成为当前正式质量准入。未取得的基座修订、优化器、精度及图像/视频处理等字段均明确未知，不从活动配置猜测。

### 生成方法与复核

本次在训练机新`m8-history-verification-20260913/`目录中使用现有`build_history_summary`纯构建器按显式原/隔离root读取，再由一次性历史资料组装脚本补齐可绑定的归档事实。没有修改CLI来隐式选择跨根来源，也不把这次离线组装称为公共history-write的双根端到端验证。正式发布采用已审字节的排他新文件写入，不覆盖目标。

最终脚本`m8-history-verification-20260913/mvllm2-history-acceptance.py`，SHA `f9e2f6456d750c563e26457c2b9d82eef3994e5e7e44d28bb14a857b3a2d7fc8`；它在`a14b3d0a`上生成`history-summary.acceptance.yaml`，两端副本一致。命令为在隔离checkout设置`PYTHONPATH=. CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4`后，用`.venv-m3/bin/python`执行该脚本。脚本及中间candidate/review/checked草案保留在RUN，最终记录不覆盖中间证据。生成前后核对HEAD与tracked状态，源轻量文件末尾重算摘要；本机未用缺权重目录重新生成实际存在性。

独立reviewer最初核定18条最低对象清单，再检查21条实际产物。发现并修正：模型已知data/fold重复写未知、CV历史执行/质量/待审声明遗漏，以及把单进程batch累积乘积误称全局有效batch。最终产物两端SHA一致；reviewer通过只读SSH独立重算47源文件size/SHA、两prepared目录、旧/new ID拼写及无权重命名文件事实，核对模型/评估绑定和数值来源后，局部验收通过。没有复跑训练或重新评分。

主Agent独立脚本`mvllm2-history-validate.py`再次检查21条唯一性、fact形态、history-only、split与global batch未知、47轻量文件摘要及权重stat，并在Linux运行现有history专项：76 passed/115 deselected，0.36秒，exit0（外围0.551秒）。日志SHA `efa4b7e35e2e3a38687e834c6c5287bbbf6bdce12196579f0340e0349c18e11b`；RUN中的`history-result.json`保存完整结果。本机同专项76 passed/115 deselected，0.42秒，exit0。这是生成时a14b3d0a的验证；随后batch代码修复的回归另记。

### 同轮闭环：公共历史生成器的batch口径

reviewer另确认既有H9代码未读取历史world_size，直接将train_batch_size×gradient_accumulation_steps命名为effective_batch_size。实际历史汇总先行纠正为per_process_accumulated_batch并保留两因子来源，全局有效batch未知；随后本轮按既有允许文件修复`versioning/migration.py`及对应`tests/versioning/test_migration.py`，公共构建器也保留限定含义的乘积和推导来源，缺world_size不再声明全局值。

有效RED：目标测试因缺per_process_accumulated_batch失败，1 failed/190 deselected，0.70秒；日志`/private/tmp/mvllm2-history-batch-red.log`。修复后Mac完整migration+CLI两个文件247 passed，2.79秒，exit0；日志`/private/tmp/mvllm2-history-batch-final.log`。此局部事实口径修复不扩展训练执行、正式身份或历史来源范围。

代码提交、Linux最终回归及最终配套文档独立核查结果见下文。本轮仅历史证据交付及已证实的batch误记修正；真实GPU/模型成功、full/holdout实际输入、物理/data下Prompt备齐、真实硬盘/大型产物与M8完整差异复审仍未完成，整体迁移不关闭。


### 最终代码与Linux回归

batch口径代码提交`d2ae4ceeda0f5f8a26393b2550b528e3fb3ae93a`，Mac产出，仅两个允许的实现/测试文件。增量bundle SHA `71598a4c8b44a976bbb07a375e937196b85e47a5f3c0efb349190e03eb218e01`；核对隔离a14b3d0a基线、tracked干净、bundle依赖与0/1独有提交后，通过cherry-pick --ff同步，原正式项目保持只读。

reviewer独立代码专项15 passed/176 deselected，0.22秒，exit0，覆盖成功归档、哈希/路径/bool拒绝及源树保持；确认既有batch P2闭环。Mac完整migration+CLI247 passed，2.79秒，exit0。Linux同一提交、同两个测试文件247 passed，2.46秒，exit0（外围2.81秒），CUDA不可见、OMP4、HF/Transformers离线，既有环境未修改；RUN `pytest-final`与先前生成时history专项分开，日志及结果不覆盖。Linux最终tracked干净。

Linux日志`pytest.log` SHA `5204aa4c2652e82d100bb2990ed50d96445a4bab60a28dbf389354a3980d2ee2`，报告`result.json`两端SHA `e4e41808446da9041c47ff9c3e2e0d05a3d82463b72352cee61bab85b57b4443`；本机副本`/private/tmp/mvllm2-history-linux.log`、`/private/tmp/mvllm2-history-linux-result.json`。代码SHA `1d883bfca9703d1a0f65f557246bc9184d1d19988e613a8f4a8390e2237370ae`；测试SHA `548c9cb2726e966458e113ce4fe287a16d99024478d8cddd2f708404bad8f8dd`，与reviewer审查一致。

实际历史YAML保持已审字节及其生成时代码a14b3d0a归因；随后d2ae4cee只修复公共生成器，没有改写历史来源或产物事实。最终配套文档及Linux证据独立只读核查通过：reviewer确认实际YAML仍为已审SHA，两端报告/日志、代码SHA、247 passed/退出码、原项目及隔离tracked状态一致；TODO中的早期“正在补汇总”已改为当次审查历史时点。Linux主Agent回归不计为reviewer复跑，本次局部通过不代表M8整包通过。产物和四份轻量文档在Linux按已核对旧/新摘要提交，再通过bundle同步回Mac；同次证据提交版本由Git历史追溯。整体M8仍未通过，不据历史整理取得GPU、受限测试、push或merge授权。


<a id="m8-final-20260913"></a>
## 43. M8物理Prompt登记与最终完整范围复审（2026-09-13）

### 范围、版本与原状态

本轮承接两端任务分支`ab5c71aea61b6ed4c083379f2883f574365722a9`，仅补齐已确认当前Prompt的物理存储位置并核对最终验收；没有改动运行时代码。Codeup main重新只读核对为`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，完整独立审查冻结范围为这两个提交之间的125提交/149文件，包含本地main原有6个独有提交。Intent→Spec→Plan提交祖先关系及当前实施授权均已核对。

训练机原项目`/home/liuyang/文档/mVllm_2`仍为干净main@f1b7d8a3；隔离项目`/home/liuyang/文档/mVllm_2-migration-7eeb93a7`为上述任务HEAD且tracked干净。写入前`/data/mVllm_2/records`及目标Prompt不存在，已有两份release与data迁移凭证存在；逐层普通路径检查通过，目标冲突即停止。

### 已确认Prompt的物理落位

使用既有公开CLI，从隔离checkout的已提交`records/prompts/prompt-v4.1-r1.yaml`加载定义，只向已授权根新增相同身份的1200字节文件：

```sh
PYTHONPATH=. CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
.venv-m3/bin/python -m versioning prompt create \
  --root /data/mVllm_2 --version prompt-v4.1-r1 --protocol v4.1 \
  --definition /home/liuyang/文档/mVllm_2-migration-7eeb93a7/records/prompts/prompt-v4.1-r1.yaml
```

实际create exit0、同root/version的`prompt show` exit0。目标`/data/mVllm_2/records/prompts/prompt-v4.1-r1.yaml`为普通文件，SHA `907e3b5a025df70add5933ec6bf1795d09b5a7a723c6adc98f34a77a0cf82bd6`，与Git定义逐字节相同；system_prompt、user_prompt、output_fields三字段与原项目concise-v2逐项相等。重复同一create exit1，报`prompt 已存在`，原目标SHA不变。没有新train/model/eval身份，没有绑定新训练或制造冻结副本。

原Prompt YAML/manifest、原数据活动指针、原模型current、Git定义、r1/r2 release.yaml与两份data receipt共9份文件写前写后SHA一致；原正式项目保持干净，隔离tracked干净。本轮只复算这些轻量文件，没有重扫两份release全部payload或外部媒体。两data已有各自迁移receipt；公开Prompt create没有另一个Prompt receipt schema，本次动作以命令、原新字段及摘要报告追溯，不伪造新凭证格式。

Linux证据目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m8-prompt-verification-20260913/`保存preflight/progress/result及三个CLI的stdout/stderr。`result.json` SHA `4641bb6dc22cf456250b3ef05b5fe4c04143734ab297959c2e5d9ac8f7059d1e`，Mac副本`/private/tmp/mvllm2-m8-prompt-result.json`摘要相同。执行脚本Mac路径`/private/tmp/mvllm2-m8-prompt.py`，同字节保存于Linux证据目录`prompt-execution.py`（SHA `b2dffb14e11f0913248850e7a2622822868dbb74d762402049adb49a0d805860`）；整个实物动作exit0，持续约1.88秒，未加载权重、使用GPU或读取受限测试结果。

### 当前完整Spec验收缺口

物理Prompt缺口已补齐，但不能把该文件存在等同于训练、测评或服务全链路已完成。full/holdout正式测评实际输入仍未接线，是实现缺口；GPU训练、真实模型加载/评分是独立的验证缺口，二者不能合并为“缺实机证据”。

独立reviewer新增复现M8-R5（P2，服务Prompt来源未与被评冻结输入绑定）：`pipeline/server_proxy.py:447–452`要求模型注册Prompt的system/user/字段与固定service analysis契约完全相同。当前已迁移concise-v2的system/user不同，output_fields相同。在CPU临时真实prepare→三折Run及证据→注册→正式eval passed→finalize→candidate→manifest/current链路中，仅训练/推理使用进程替身，不mock证据门；合法绑定通过resolve_service_model后，server_proxy.main仍在加载器前拒绝。独立fixture位于`/private/tmp/mvllm2-final-concise-service-0bdr7oux`，该复现exit0，不是GPU或模型效果通过。

同一独立fixture还复现同ID漂移错误放行：仅将临时store中当前Prompt文件替换为固定service contract内容，训练/eval冻结事实不改，resolver的binding/fingerprint保持不变，实际server_proxy.main反而调用CPU替身loader及serve并返回0；此服务反例还替换create_integrated_app与uvicorn.run，未启动真实HTTP服务，随后已恢复临时文件原字节。当前服务读取可变的同ID定义，却未与被评冻结内容绑定。因此修复还必须比较训练/eval冻结Prompt，绑定其内容摘要，并拒绝当前同ID内容漂移；仅删除固定相等门不满足修复要求。此替换只在独立临时fixture，不曾改动Git或/data正式Prompt。

M8-R5阻断“当前迁移Prompt对应合格模型可服务”的验收，不能解释为Spec允许的“缺合法alias时拒绝”。推荐后续让服务analysis输入使用模型已冻结且验签的Prompt，并保留输出结构、评分、alias、审批及备份门禁；需同步核对请求识别、重试及交付契约。另一方向是保留固定服务Prompt并明确批准缩小可部署范围；这会使当前迁移Prompt对应模型仍不可部署。两者都会触及输入行为或交付范围，须先由用户确认。当前不删除相等校验、不改写不可变Prompt，也不把推荐方案记成已批准。具体任务与依赖统一见TODO M8-R5。

独立reviewer已复核完整125提交/149文件范围及最终新增实物证据：跨SSH重新验证目标普通文件/1200字节/SHA与Git相同、旧源三字段一致，9份保护文件当前SHA全部匹配，两个工作区tracked clean；CLI 0/0/1与报告SHA一致。另执行最终整合专项11 passed/58 deselected，14.66秒，exit0，覆盖实际candidate→backup异根、alias字节漂移拒绝、未选fold退休、deploy artifact、固定服务fixture成功及加载中漂移；这不是当前concise服务成功。完整range diff-check通过。最终完整代码审查结论为“整包驳回修改”，唯一新增可执行finding为上述P2；R1–R4和历史局部验收继续有效，不因本次拒绝撤销。最终CPU回归已正常退出，结果与skip原因见下文。整体迁移未完成，未请求或执行push/merge。


独立11项回归精确命令（上述相同CPU/离线环境）：`.venv/bin/python -m pytest -q tests/test_eval_run.py tests/test_serve_smoke.py -k 'actual_execution_chain or qualified_alias_rechecks or service_main_loads_only or declared_fold_evidence or evaluation_cannot_qualify' --basetemp=/private/tmp/mvllm2-final-range-review-20260913 --tb=short`。独立Agent没有另外保存日志文件，原始输出在本次reviewer工具执行记录；R5两反例由stdin临时Python命令执行，输出标记`REVIEW_REPRO`、`PROMPT_DRIFT_REPRO`，未另存脚本/日志，保留上述临时fixture。这里引用独立执行结果，不记为主Agent复跑。


### 本机最终整仓CPU回归与文档收尾

冻结代码ab5c71ae，Mac运行：

```sh
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=4 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q tests --tb=short --basetemp=/private/tmp/mvllm2-m8-final-20260913
```

实际结果 **2647 passed/11 skipped，452.07秒，exit0**。汇总打印后进程仍有终止耗时，主Agent等待到exec会话实际返回0才记录完成；后续尝试进程采样时进程已退出，没有取得可用于本次归因的堆栈，不把历史GC诊断冒充本轮采样结论。日志`/private/tmp/mvllm2-m8-final-20260913.log`，SHA `011e79fb99d89748c94d492996da8936f76d2244d4871ec9ee0ace39b4d07490`。

为明确skip原因，另仅执行既有跳过项：`.venv/bin/python -m pytest -q -rs tests/test_subvideo_build_plan.py tests/test_eval_run.py::test_loads_committed_fold_validation_sets`，11 skipped/0.18秒/exit0；其中10项缺V3本机历史fixture，1项缺V4.1本机workspace数据，不能计为通过。日志`/private/tmp/mvllm2-m8-skip-reasons.log`，SHA `dd2bcd3804428e91ce9f5e6f66614dfaf5783c27086177f975aeb224631efd8d`。CPU报告`/private/tmp/mvllm2-m8-mac-regression.json`与上述两份日志复制到Linux本轮证据目录，名称分别`mac-regression.json`、`mac-pytest.log`、`mac-skip-reasons.log`；明确来源为Mac，没有在Linux重跑全仓套件。

四份变更文档的52个本地链接可达，`git diff --check`通过。独立文档核查确认第43节/当前矩阵准确保留两个R5反例、CPU替身及无真实HTTP边界、Prompt实物验证和full/holdout实现缺口；旧审查时点与当前终态已区分。最终完整审查为驳回修改，并非未完成审查；任务上层继续进行中，R5兼容策略待用户确认，同ID漂移门可按既有完整性要求先修复。真实GPU、受限测试、硬盘/大型产物/外部依赖整机恢复未执行，未请求或执行push/merge。

本轮仅四份证据文档变更，运行时代码保持ab5c71ae。Linux在核对原/新文档摘要、物理Prompt及9保护文件、Mac回归日志摘要、两工作区状态后原子提交；提交版本由本节相关文件Git历史追溯，再以校验bundle回传Mac。用户未跟踪agent-handoff.md及原stash必须保持；提交/同步的实际结果另由Git与证据目录docs-commit.json追溯，不把代码审查结论扩大到未经执行的后续操作。


<a id="m8-r5-prompt-20260913"></a>
## 44. M8-R5服务冻结Prompt绑定修复（2026-09-13）

### 已确认行为与代码

用户在第43节复审后明确回复“可以”，确认服务analysis使用模型训练及passed正式评测时冻结并验签的Prompt，保留现有输出和准入门禁。Spec已单独提交`789fa4fc`，下游Plan复核及精确范围提交`511cfc14`；既有实施授权持续。Codeup main只读核对仍为`f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，没有新的基线漂移。

Mac代码提交`de1b51dd163bd4694a6823dc9b54a056248cd61f`只包含3个运行时文件、2个测试文件和versioning/SCRIPTS.md。共享resolver在既有训练/评测/alias/current/权重门之后读取训练冻结Prompt，比对当前同ID定义及passed eval冻结内容，在末次在线复验后再比较快照；缺失、链接、正文不一致及加载时漂移均拒绝。返回Prompt与规范化内容SHA，将内容纳入fingerprint。server_proxy与smoke共享派生契约，只替换analysis system/user并重算实际contract_hash；原输出字段、生成参数、重试提示、evidence、评分及审批/备份门保持。重试仍从同一冻结Prompt开始，不直接删除固定相等检查而放弃绑定。

没有改写Git或/data中的正式Prompt、旧业务契约、历史训练/评测记录，也没有自动重写部署元数据。已有部署config_fingerprint须由显式resolver新绑定取得；旧fingerprint不被默认放行。eval输入沿用规范化JSON摘要，仅增加尾部空白不等于正文漂移，不宣称拒绝所有原始字节变化。

### 本机验证与独立复核

有效RED使用修复前511cfc14的三个运行时文件及已修正fixture的新增测试：3 failed/21 deselected、exit1，分别为缺共享派生函数、当前同ID漂移未拒绝、concise仍在loader前被旧门拒绝。日志`/private/tmp/mvllm2-r5-valid-red.log`；测试后恢复本轮实现。更早初测曾因fixture把version重复传给create_prompt失败，修正后才做上述有效RED，不把fixture错误作为产品失败证明。

Mac受影响7文件回归：`tests/test_serve_smoke.py tests/test_eval_run.py tests/test_production_contract.py tests/test_v4_1_service_contract.py tests/test_serve_validate_delivery.py tests/versioning/test_materialize.py tests/versioning/test_backup.py`，共同环境CUDA不可见、OMP4、HF/Transformers离线，命令`.venv/bin/python -m pytest -q <上述文件> --tb=short --basetemp=/private/tmp/mvllm2-r5-broad`，**195 passed/1 skipped，193.63秒，exit0**。唯一skip是本机缺V4.1历史workspace数据；未重新运行第43节的整仓2647项，不将其归因到本轮修复。

随后新增5项冻结内容回归，以`-k 'frozen_prompt_damage or individually_valid'`运行服务测试文件，basetemp为`/private/tmp/mvllm2-r5-frozen-final`：**5 passed/25 deselected，13.91秒，exit0**。首次损坏注入被fixture封存0444权限挡住，修正为仅对测试自建文件加owner-write后注入；主工作区及正式文件没有被改权限。五项覆盖训练/eval冻结正文损坏、当前定义缺失/链接，以及训练和eval各自证据有效但Prompt不同的混用拒绝。

新增完整成功路径使用本次Git迁移Prompt正文，实际prepare→三折运行证据→模型登记→正式eval passed→finalize→candidate→manifest/current→server_proxy.main→FastAPI TestClient→smoke。analysis初次返回非法输出，第二次使用同一冻结Prompt及原重试提示；旧固定正文请求422拒绝。训练器、推理器、processor及HTTP transport/uvicorn监听为CPU替身，实际准入门、FastAPI路由、请求校验和包装未mock；没有真实HTTP监听、媒体解码、GPU或真实模型效果证明。

独立reviewer对511cfc14至修复工作树的6文件及操作说明局部复审通过，无可执行finding，前轮R5两反例闭环。独立服务文件25 passed/23.73秒/exit0，basetemp`/private/tmp/mvllm2-r5-independent-review-20260913`；新增5项随后独立5 passed/25 deselected/13.86秒/exit0，basetemp`/private/tmp/mvllm2-r5-independent-final-20260913`。另独立注入训练/eval冻结正文损坏并验证拒绝，恢复自建fixture后binding保持，派生hash独立重算一致；探针及独立测试原始输出在reviewer工具记录，没有另存独立脚本/日志。独立范围不自动包括后续Linux回归或整体迁移通过。

### 双机同步与Linux验证

增量bundle从bb9ef57b到de1b51dd，包含Spec、Plan和代码共3提交，SHA `85f3f17880587c903e70460fa99867c66a357f75dd48e13e3b4a43e7833d6598`。预检原项目main@f1b7d8a3及隔离bb9ef57b均tracked干净；bundle verify、0/3独有提交及6文件摘要通过后，仅cherry-pick --ff到隔离任务分支。原项目保持只读，环境不修改。

Linux使用既有`.venv-m3/bin/python`，`PYTHONPATH=.:m5-service-verification-20260912/dependencies`，CUDA不可见、OMP4、HF/Transformers离线；为避免既有MLflow进程缓存文件句柄上限，分两个新进程执行同7测试文件，第一组为5个服务/eval/契约/交付文件，第二组为materialize/backup。证据目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m8-r5-verification-20260913/`，新增日志及临时fixture，不复用旧演练输出。两组均正常退出，最终结果见下文。

Mac日志`/private/tmp/mvllm2-r5-valid-red.log` SHA `ec5f0559d680dd65528ab5e59a71ef4dc8ee44bafae3efbcc6c936049194d764`。

Mac日志`/private/tmp/mvllm2-r5-broad.log` SHA `f6289f285261ab3281344b58ef80955172b88a7523bec70d4222034291d88cf5`。

Mac日志`/private/tmp/mvllm2-r5-frozen-final.log` SHA `8c68498129137b8ea59cb5e9a44e543af8a8073df330634c9830c041306b4fa7`。


### Linux最终结果与交付结论

同一提交de1b51dd、原CPU环境，第一组 **97 passed/1 skipped，99.72秒，exit0**（外围106.624秒）；第二组 **103 passed，115.60秒，exit0**（外围125.051秒）；合计 **200 passed/1 skipped**。第一组唯一skip仍为缺本机V4.1历史workspace数据；Starlette TestClient另有1条AnyIO BlockingPortal别名弃用告警，没有安装或变更依赖。第二组覆盖现有物化及store备份/恢复行为，不扩大为真实硬盘或外部基座/媒体整机恢复。

RUN中的`pytest-group1.log` SHA `37852c7a790777bb34d1859fe3456c1c247192ec6b77d70e79902be9ae73ad6c`，`pytest-group2.log` SHA `44a61ea6b1ea652255e4b616fd045d8fc1a2a918c25e258e8417b38da42afe1c`，`result.json` SHA `753d905ad50cb15a21507b6ebcdb6162ee7e8d62699ed5d192fa9ab6403a1764`；Mac副本为`/private/tmp/mvllm2-r5-linux-group1.log`、`mvllm2-r5-linux-group2.log`、`mvllm2-r5-linux-result.json`，两端摘要一致。执行脚本保存于RUN `execution.py`（Mac `/private/tmp/mvllm2-r5-linux.py`）；Mac broad/frozen原日志同字节复制为RUN `mac-broad.log`、`mac-frozen.log`。RED初次以文本读取传输，进度条CR/CRLF换行被规范化为LF，RUN `mac-valid-red.log` SHA `e19e17899961fedacb96df24cb5b1bd59b87376451841c55fc489ed0d823fd8f`及mac-result.json如实保留这份文本副本；后续另传原始字节为`mac-valid-red-source.log`，SHA `ec5f0559d680dd65528ab5e59a71ef4dc8ee44bafae3efbcc6c936049194d764`，与Mac原文件一致。规范化规则已逐字节校验，测试结论未改变；未覆盖初次副本，也未将Mac执行写成Linux复跑。

Linux结束后7份保护轻量文件SHA全部保持，包含/data正式Prompt、两个release.yaml、两份data receipt、原数据活动指针和模型current；原正式项目仍干净main@f1b7d8a3，隔离tracked干净de1b51dd。六文件实际摘要两端一致，其中model_registry.py `f6fa5418ec40c3ec1c34c153b5b58ea25118f7d2f946b088906187aa9fcacf8f`、server_proxy.py `c2da52db27fdac092c2fdcac4c098dc5ca75582e339ad2b2fab3b25ab52880c2`、serve_smoke.py `2d1395ba2bfda0fff5c7e850975d0b607c38717335d96360eeb97dbd724c7ef9`，与独立审查对象一致。

M8-R5本轮范围已解决：用户确认的冻结Prompt服务路径通过实际入口和CPU HTTP路由/重试/smoke，原错误拒绝及同ID漂移放行均闭环。独立代码/操作说明结论为局部通过；最终双机证据与四份文档按实际原日志另核查。第43节完整代码范围驳回保留为历史结论，本次局部通过不冒充新的整包审查；full/holdout实际输入仍未接线，GPU/模型效果、真实硬盘/大型产物及外部依赖整机恢复仍未验证，整体迁移不关闭。

仅四份轻量证据文档在Linux按已核对原/新摘要原子提交，再经校验bundle回传Mac；同次证据版本由本节文件Git历史及RUN `docs-commit.json`追溯。用户未跟踪handoff与原stash保持，未push/merge、改旧源或执行GPU/受限测试。


<a id="m4-full-holdout-20260913"></a>
## 45. 独立 full 训练及 holdout 实际接线（2026-09-13）

### 授权、实现与证据边界

用户要求“补齐吧”，并明确回答“接受，增加独立全量训练范围”。Spec `0bf0baed`与Plan `ef025f57`/`63ec035c`/`3cfa5b77`记录授权与精确文件范围；设计文档一致性维护由Plan `0666462d`纳入。本轮实现代码为 `fed9bcfcf35736c304cc548fab4d7e93721c73d2`，不执行真实训练、GPU推理、真实holdout构建或真值读取，不push/merge。

full准备使用同一开发release三折共同全集按媒体身份去重，冻结六份来源及新增full输入；训练只调用一次实际适配器并保存full/adapter，无fold子Run。Registry要求full范围与冻结输入、实际结果及权重证据对应。三折划分、采样和旧manifest字节格式保持。

holdout准备绑定无标签媒体清单、模型训练Prompt、严格规则/阈值、预注册与claim；run仅媒体推理，显式score才读受限真值。private目录保存预测、访问记录、真值快照和逐样本评分；未建立评分承诺时必须对照原source truth并复算明细，文件自洽不能代替实际评分。公开MLflow仅保存无标签输入及aggregate证据，消费前钉扎评分承诺；已承诺完成恢复不重新推理或重读原truth。模型准入与导出核查公开承诺、绑定、权重和consumed，不公开逐样本结果。

### 本机验证与独立审查

所有测试使用Mac隔离合成数据和训练器/模型回调替身，不能作为GPU或真实模型质量证据。

- claim新增三种身份不匹配测试：最初断言错误地期待exit2，只是测试断言错误；调整为现有业务错误exit1后，`/private/tmp/mvllm2-holdout-preflight-valid-red.log`复现错误参数仍留下冻结目录的3个有效失败。修复在冻结前核对四元组，发布后继续复验。
- full/claim/原训练联合 **44 passed，6.09秒，exit0**，日志`/private/tmp/mvllm2-full-fixed.log`；独立训练审查发现full完成半提交恢复及旧三折导出兼容两项P2，修复后独立 **5 passed，2.84秒，exit0**，局部复审通过。
- 广回归 **679 passed、1 skipped，451.78秒，正常exit0**，日志`/private/tmp/mvllm2-full-holdout-broad.log`。命令为`.venv/bin/python -m pytest tests/test_full_training.py tests/test_eval_holdout.py tests/test_train_with_contract.py tests/test_eval_run.py tests/versioning/test_mlflow_train.py tests/versioning/test_mlflow_eval.py tests/versioning/test_registry.py tests/versioning/test_cli.py tests/versioning/test_cli_holdout.py -q --tb=short`，CUDA不可见、OMP4、HF/Transformers离线。该轮启动早于holdout最终P1/P2修改，未变化路径的广回归与最终holdout复验分开记，不把前者写成所有最终代码重新跑过。
- 最终holdout **16 passed，21.40秒，exit0**，日志`/private/tmp/mvllm2-holdout-source-fixed.log`。覆盖正常媒体推理/评分、质量失败也消费、错误身份/规则/媒体标签拒绝、三类metadata symlink拒绝、评分与完成中断、单份及完整私有评分伪造拒绝、来源快照核验与公开aggregate不读truth。
- holdout独立审查先发现链接提前读取truth的P2、只凭收据恢复的P1；第一次P1修复仍可伪造完整私有阶段，强化反例实际达到passed并finalize。最终增加原source truth校验后，独立 **7 passed、9 deselected，10.24秒，exit0**，P1闭环；前轮链接P2的独立15项复验通过保持。最后核查`finetune/eval_holdout.py` SHA `0879372e06cb32c606416011d69cc5637856e7040bb0468241548a3ea2b0354b`，与代码提交一致。训练、holdout与两份操作说明均局部通过；设计文档精确修改另经只读一致性核查通过，不等于完整迁移差异审查。

### Linux 隔离验证

执行目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m4-full-holdout-verification-20260913/`。从b40eaa90至fed9bcfc的6提交bundle SHA `7e11aad6e9e56eab730ded96a4a43880887346022a8aaf491390782c13dd492b`；同步前验证原项目与Codeup main均f1b7d8a3、隔离b40eaa90且tracked干净，bundle verify及0/6独有提交核对后只快进隔离分支。`execution.py`及`code.json`固定实际代码、12文件摘要和7份保护轻量文件；原项目不写入。

使用既有`.venv-m3/bin/python`，`PYTHONPATH=.:m5-service-verification-20260912/dependencies`、CUDA不可见、OMP4、HF/Transformers离线；分三个新CPU进程避免既有MLflow进程缓存文件句柄累计。三组均正常exit0：第一组163 passed/1 skipped、91.46秒；第二组390 passed、256.03秒；第三组266 passed、305.26秒；合计819 passed/1 skipped。外围进程耗时分别98.595、290.485、329.985秒。唯一skip仍为历史workspace fixture缺失，第三组另有既存AnyIO BlockingPortal弃用告警，没有修改依赖或系统限额。Mac原日志通过scp按字节复制到RUN，摘要与`mac-result.json`对应；没有把Mac测试说成Linux复跑。


最终RUN `result.json` SHA `2430f0be047c905743ce5da5945f121b0c2eceff7ee470d12bf2a9d037e48686`。三组日志SHA依次为：

- `pytest-group1.log`：`bc02f598aadec102ea2d8c6268ae2823de9df0afd4515a72b80982f3b5b05026`。
- `pytest-group2.log`：`1d44aa6282168b1ab29f3370b4a1eb3d096dab2601c50e0b393551b6486d5ae1`。
- `pytest-group3.log`：`7409dc48f423ba95d41a40f99cb7750b8764aadd074aa870d6930334f8038dd4`。

Mac对应副本为`/private/tmp/mvllm2-full-holdout-linux-result.json`、`mvllm2-full-holdout-linux-pytest-group1.log`至`group3.log`，按原字节回传并验签。RUN的`mac-result.json` SHA `8e02fcb51f5580160ce64e1c41d746a09cc403be32e53ce4d21793fa469f2536`；其原日志与来源说明保持Mac执行归属。

三组覆盖：① full训练、holdout、原训练适配器、eval执行器和公开train/eval/claim CLI；② MLflow训练及测评状态；③ Registry、物化、备份及实际服务smoke。测试结束时12份代码/操作说明摘要与fed9bcfc一致，7份保护轻量文件前后SHA一致：/data正式Prompt、两data release.yaml、两receipt、原数据活动指针、原模型current。原项目保持干净main@f1b7d8a3，隔离tracked干净fed9bcfc。额外Plan维护范围提交0666462d只改变Plan，在测试后以0/1独有提交、单文件diff及bundle验签快进；不把它写成重新跑过代码。

本轮full/holdout实现缺口已补齐且双机隔离CPU验证通过。M4仍保留真实训练/模型加载/评分验证缺口，HOLDOUT-BUILD仍未实际构建授权新数据；M5真实服务成功路径、真实硬盘/大型产物和外部依赖整机恢复亦未验收。下一步是更新Codeup main至当前分支的完整差异并完成整包审查；本轮局部通过不替代整包验收，也不授权push/merge。设计、TODO、Plan、verification、handoff五份轻量文档按最终证据同步，提交由本节文件Git历史及RUN `docs-commit.json`追溯；用户未跟踪agent-handoff及原stash保留。

最终五份文档与双机证据已由独立reviewer只读核查通过：原日志、实际退出码、12份代码摘要、7份保护文件及两端Git状态与记录一致。发现的1项P3当前状态残留（Plan及TODO共4处）已修正并复核闭环；未重跑测试。此结论仅覆盖本轮文档和证据，不替代M8整包差异审查。


<a id="m8-complete-20260913"></a>
## 46. full/holdout 接线后的完整迁移复审（2026-09-13）

### 冻结范围及执行前核对

用户要求“下一步”，继续已批准M8整包审查。Codeup main `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52` 至任务分支 `e1d70c58e7176591bd325cd516222ffce1b2874c`，共138提交/152文件；包括承接基础设施及本地main独有提交，不局限于最后full/holdout修改。`git diff --binary`冻结patch SHA `5bb22a90a019e4e332f1e31126bb191da78de514eafb7792e410e313a5d70818`。

Mac证据目录`/private/tmp/mvllm2-m8-complete-20260913-e1d70c58/`，`scope.json`保存完整文件清单、分支、提交和保护摘要，`complete.patch`保存冻结差异。用户未跟踪agent-handoff SHA保持`9b89b64994954f1adb6b37f04ef013b952a0a9fbe4304815ea9f97a5ba4d5b51`，原stash保持`38613e5eb42b0af3ca43a7274d9c3f3d73cb0200`。

本轮通过SSH只读核对原项目干净`main@f1b7d8a3`、隔离任务分支tracked干净`e1d70c58`；七份保护文件当前摘要与第45节结束值完全一致。首次尝试在原远程工作区使用不存在的`codeup`别名，`ls-remote`返回128；后改从Mac已配置的`codeup`远端查询，main仍为上述基线。没有修改远端配置；成功结果和首次错误说明保存在`preflight.json`。

### 验证与审查状态

Mac整仓命令`.venv/bin/python -m pytest -q --tb=short -rs`已执行完成（结果见下文），CUDA不可见、OMP4、HF/Transformers离线，使用合成CPU对象，不运行真实训练、推理或真实holdout。`run.py`保存实际进程退出码、耗时和`pytest.log`摘要至`result.json`。

独立reviewer已核查冻结的全部差异、Spec逐项验收及活动入口/失败恢复/训练与holdout/Registry/备份/服务交互；允许必要CPU合成验证，只读代码和文档。既有局部通过不代替本轮整包结论。真实GPU成功路径、真实holdout构建和使用、真实硬盘及大型产物恢复的限制保持；未请求或执行push/merge。


### 已确认发现与文档校正

M8-R6（P2）：独立合成CPU探针在prepare之后替换adapter_name_or_path的权重内容，verify通过，执行替身读到“changed after freeze”，训练completed并可登记full model。源代码仅冻结base_model_files，LLaMA-Factory实际加载/合并外部adapter，主Agent已核对二者。原日志`/private/tmp/mvllm2-final-range-external-input-probe.log`，fixture`/private/tmp/mvllm2-final-external-input-2791otwy`，输出EXTERNAL_INPUT_DRIFT_ACCEPTED。独立resume_from_checkpoint探针随后也复现准备后替换checkpoint仍可completed，日志`/private/tmp/mvllm2-final-range-checkpoint-probe.log`输出CHECKPOINT_DRIFT_ACCEPTED；两反例合并为同一M8-R6。本轮保持被冻结代码不变。

finetune/README.md及entrypoint-map.md仍声明full/holdout拒绝，已按已批准Spec与fed9bcfc实现同步独立full范围、媒体run/授权score及真实环境限制；参数继续引用versioning/SCRIPTS.md，不复制schema或引入新方案。待独立核对最终文档。


### 最终结果与结论

Mac整仓 **2686 passed / 1 failed / 11 skipped，504.68秒，实际exit1**；外围进程571.311秒。pytest.log SHA `48a636b9ac06e5149120808274951b2f29f017465e8812b848cc29d42ccca437`，不能以通过数量掩盖整仓失败。11项skip为1项缺V4.1本机数据、10项缺V3轻量fixture。295条告警包含pytest清理既有只读合成目录时Directory not empty；未删除既有测试目录以掩盖告警，未改系统环境。

唯一失败为tests/test_train_with_contract.py::test_training_entrypoint_prefers_current_repository_llamafactory，ROOT被其他测试收集时重新插入sys.path，先前导入的训练模块不会重排。主Agent单独复跑该项 **1 passed，0.15秒，exit0**；组合收集tests/test_eval_holdout.py、tests/test_publish_training_release.py、tests/test_train_with_contract.py，以-k只运行该项，**1 failed/49 deselected，0.99秒，exit1**，证实顺序依赖，记录M8-R7。isolated-test.log SHA `976ea3fe6dfa65b827ec05fc16bf49cec94d3fda3b2d6ad4719708e74a38b32d`；ordered-test.log SHA `c75a832007d0756a08712cecb57e3830182f178b323cf4088d0ed8b081948678`；对应result文件保存精确命令与实际退出码。运行时仍校验实际LLaMA-Factory来源，不把此测试失败扩大为已证实错包加载。

独立整合回归 **34 passed，40.41秒，exit0**；日志mvllm2-final-range-selected-e1d70c58.log SHA `38e5f1fdbd7cd4447a1269a13b3f2a436e369c8a1bb63e6c6fb745c22440d4d4`。独立合成full训练→holdout推理/score→candidate→备份→原模拟store不可用→异根恢复→current/服务准入探针exit0，恢复前后指纹一致且准入truth读取tripwire未触发；日志mvllm2-final-full-restore-probe.log SHA `db7cbdb784a2ea8b2478f80066e378c1224d034a17ff6afda8de09ff13848fe8`。它不是实际模型推理或真实硬盘恢复。

两项外部权重反例均exit0，表示错误被接受而非修复通过。adapter日志SHA `d555e0b287a86d58b73ceac3fb66da6c2ee7d2a86c198773915118156f4d9241`，checkpoint日志SHA `dc5bb2c948d7efc9a7fa88db5ed930c9d8c16406ab563740a38be2fcb4f4e201`。adapter首次通过stdin执行的原脚本已保存为mvllm2-final-range-external-input-probe.py，SHA `7bffc6d718ca68afa93fb53b3bc070bdb2f9ca494ab529286428b70f99425b5a`，从repo cwd设置PYTHONPATH=.及上述CPU离线环境可复跑。以上独立证据原字节复制到本轮Mac证据目录，review-result.json由主Agent据独立报告整理，未冒充主Agent复跑。

本轮独立整包审查结论为**驳回修改**：一项运行时P2（M8-R6）及冻结文档P3；主Agent另定位整仓回归问题M8-R7。审查覆盖138提交/152文件和Spec矩阵，未变化部分复用同一reviewer前轮完整范围与修复核查，本轮重查R5、full/holdout及跨模块交互，不能表述为每项历史动态验证均重新执行。文档P3修改另核对当前六份文档，不改变运行代码冻结目标。下一步先修M8-R6/M8-R7，再做回归与独立复核；M8整体保持未关闭。

本轮Mac原始证据共19文件已按字节复制到Linux隔离目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m8-complete-verification-20260913-e1d70c58/`，含完整冻结patch、范围、原日志、进程报告和独立探针脚本。压缩包SHA `2821625060e9c3c20e04be2366bfb8c008c1535bca293b8b1d2f6e165379f1ea`，逐文件摘要、七份保护文件和原项目干净状态复核通过，copy-receipt.json记录；这是Mac证据存档，不是Linux复跑。六文档本地链接已检查70项无缺失，新训练/holdout链接锚点另对照实际标题。文档提交及隔离分支快进由Git历史与RUN同步凭证追溯，不push/merge。

最终六文档及第46节证据已由独立reviewer只读核查通过：P3过期入口说明已修正，M8-R7导入链归因与单项/组合证据一致，Linux19份存档与Mac摘要一致；没有重跑主Agent测试，也不把文档通过覆盖M8整包驳回。新增M8-R7链接后最终本地链接复查71项均可达（final-doc-links.json），git diff --check通过。M8-R6/M8-R7仍待修。


<a id="m8-r6-r7-20260913"></a>
## 47. 外部训练输入冻结与整仓测试隔离修复（2026-09-13）

用户要求执行下一步，按第46节及TODO先修M8-R6/R7，沿用既有明确实施授权。保持三折与独立full训练范围、模型晋级门和历史对象，不运行真实训练/GPU/真实holdout。M8-R6选择未实现外部权重冻结时fail-closed：配置中的非null`adapter_name_or_path`或`resume_from_checkpoint`在prepare前拒绝，旧冻结配置在validate/run拒绝，MLflow训练证据门在模型登记前再次检查。旧completed状态不重写或删除，只拒绝将无来源证据的结果晋级。M8-R7将路径优先级测试放入新Python进程，保留run_training对实际模块来源的运行时校验。versioning/SCRIPTS.md同步明确可接受的配置边界。

本机合成RED：四个CV/full×两类外部权重prepare测试此前均未拒绝；旧full含外部adapter的completed记录仍能register model。第一轮RED总6 failed（其中两个旧冻结测试由于拦截函数尚未实现而报AttributeError，不能算已复现业务缺陷）；单独旧模型登记反例1 failed，实际外部模型被创建。修复后Mac受影响训练/Registry联合179 passed、62.94秒/exit0；原第46节失败的三文件导入顺序组合1 passed/49 deselected、0.95秒/exit0。均使用CPU合成数据、CUDA不可见、OMP4、HF/Transformers离线；正式真实效果仍无证据。该时点整仓回归及独立复审仍在进行；最终结果见本节末。


独立reviewer已核查五文件代码/操作说明工作树差异，局部结论通过、无可执行新问题：定向11 passed/35 deselected、5.80秒、exit0，日志SHA `a40f9f8a5b8ffe406c707c7ab018474ae13f990f1a9d6261315daa0465190a15`；原收集顺序及错误实际包来源拒绝2 passed/48 deselected、2.34秒、exit0，日志SHA `e4e985bf99cddcd63304a955fcb9b359b4f23aff9261500827a007f4402ed91a`。审查者直接使用上轮原始adapter/checkpoint反例旧记录，validate/run/export/register及已登记模型测评准入均拒绝，原Run/ModelVersion/状态/params前后不变，探针exit0、日志SHA `4c3d9f31e99175903e5db6aba794f5026f9c2c4ad38b7611a0bb00edbfc09343`。三份原日志在Mac`/private/tmp/mvllm2-r6-r7-20260913/`按原字节留存；此为独立局部验证，不是整仓或Linux复跑。该时点最终整仓及双机证据尚待完成；本节末记录最终结果。


### 代码提交与 Linux 隔离 CPU 复验

代码/操作说明提交为`d9ec12270d5b3f106a1e1da6e5b2c6eb443aaea7`（五文件）；独立局部复核先于提交通过。Codeup main及训练机原项目仍是干净`f1b7d8a3`，隔离基线`2caac393`。增量bundle SHA `3dd5f2d321ae1cf59c6baeb17ce184741f1326101b8ce47573939b41f7dbe257`；在隔离工作区验证bundle、0/1独有提交及精确五文件后快进，不触碰正式项目。

Linux证据目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m8-r6r7-verification-20260913/`，使用现有`.venv-m3/bin/python`及先前隔离依赖目录，CUDA不可见、OMP4、HF/Transformers离线。实际两进程各exit0：训练/full/Registry **179 passed，114.27秒**（外层128.463秒）；原收集顺序复验 **1 passed/49 deselected，2.30秒**（外层2.836秒）。原日志SHA分别为`5a6ecad7a5c92e31fa6a6b1fd453b3caeb77de1acd4213d84c456a5336bc6560`、`8d6a94d33ec53abb8484abe74e555d5629c68da5bd22c0ecfb4a74cfbe6cc85d`；`result.json` SHA `6771267a5f89e70cfc79c8c316afc96eb41ae5421f117bbe79d2e0cdb3611002`。Mac副本`/private/tmp/mvllm2-r6-r7-20260913/linux-result.json`与两日志按原字节回传验签，未写成Mac复跑。

测试后五文件SHA与代码bundle一致；七份保护轻量文件前后摘要不变，正式原项目干净`main@f1b7d8a3`、隔离tracked干净`d9ec1227`。Linux验证仍是CPU合成运行，不代表真实训练/GPU/holdout或大型产物可用。该时点Mac整仓仍在运行；最终证据和整体复核见下。

### 最终整仓退出、原件存档与整包审查结论

同一代码`d9ec12270d5b3f106a1e1da6e5b2c6eb443aaea7`下，Mac整仓`.venv/bin/python -m pytest -q --tb=short -rs --basetemp /private/tmp/mvllm2-r6-r7-20260913/pytest-tmp`最终为 **2694 passed / 11 skipped，pytest 774.28秒，实际进程exit0**；外层计时1136.481秒，runner从`subprocess.returncode`记录退出码。`/private/tmp/mvllm2-r6-r7-20260913/result.json`的`log_sha256`为`b8a2aef36df3fb49d8bff100814a28897370565d71e7a73320e8b4d51aef086f`；11项skip是1项缺本机V4.1数据、10项缺本机V3轻量fixture。测试摘要打印后的长尾采样在`Py_FinalizeEx/gc_collect_main`，但最终退出码已取得，不再沿用第46节旧失败状态。测试期间仅更新此类证据文档，五文件代码字节未变。

Mac原始整仓日志、报告、runner及三份独立局部复核日志和进程采样共7文件，均按原字节验SHA复制至Linux隔离验证目录；来源清单`/private/tmp/mvllm2-r6-r7-20260913/mac-evidence.json` SHA `22e2c22df551d1716cea4003bdbd4ab0648decbd80576811d5951a9ab900a3ab`，清单注明`source_machine=Mac`、`linux_rerun=false`。远端逐文件验签7/7通过；此存档不算Linux整仓复跑。Linux实际新执行的只有前述两组179项和顺序1项，各exit0，`result.json`原件与Mac副本同SHA `6771267a5f89e70cfc79c8c316afc96eb41ae5421f117bbe79d2e0cdb3611002`。

独立reviewer核对冻结范围Codeup main `f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`至`d9ec12270d5b3f106a1e1da6e5b2c6eb443aaea7`，**140提交/152文件，更新后的整包代码差异审查通过，无剩余可执行问题**。未变化部分承接同一reviewer前轮完整范围审查证据；`2caac393`只含已核查文档，`d9ec1227`五文件SHA与独立局部复审一致。reviewer核对作者Mac整仓实际exit0和Linux原报告，未把它们记作独立复跑；独立者自身的11项、顺序/错误来源2项及原两类旧记录反例复验如本节上文。第46节的驳回是当时冻结范围的历史结论，R6/R7现已解决本轮代码与CPU范围。

验收边界：尚无真实GPU训练与模型质量、实际授权新holdout构建和评分、真实硬盘及大型产物恢复、外部依赖整机恢复证据。M4/M5等真实环境缺口与M8父任务保持未关闭；本轮没有执行merge/push。轻量台账、Plan、verification、handoff的最终提交版本按Git历史追溯。四份最终文档已请求同一独立reviewer只读核查，但该次任务触及用量限制而未产生结论；文档仅经主Agent的`git diff --check`和59个本地文件链接可达性检查，不记作独立文档复核通过。整包代码差异审查结论已先于此独立完成，不受该错误覆盖。

### 轻量文档隔离同步

Mac将四份轻量台账/Plan/verification/handoff提交为`c3685578923a46ab078f331906ad3aabbd4e7c31`，提交范围仅这四文件，尾注按实际Mac Codex执行归因。增量bundle SHA `ce4e77f8cb5182e96827304d582b49064056c40b55417b2281a0bd3c7dee3305`；Linux先核隔离`d9ec1227`、正式`main@f1b7d8a3`均干净及七保护文件与原preflight一致，再验签bundle、确认只有一提交/四文件、仅快进隔离分支至`c3685578`。事后两工作区tracked状态干净、七保护文件SHA未变。原回执`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/m8-r6r7-verification-20260913/docs-sync-receipt.json`按原字节复制到Mac`/private/tmp/mvllm2-r6-r7-20260913/docs-sync-receipt.json`，SHA `d9ffea7f77f5bc8e5e397089b63ca92718d5b20b98a1d4dd4a6f7d2fb86c71e8`。本段后续文字收口只追加文档记录，代码审查范围仍冻结于`d9ec1227`；不把隔离分支快进说成Codeup main集成。


<a id="delivery-preparation-20260913"></a>
## 48. 交付文档补核与模型主线只读准备（2026-09-13）

### 范围、机器与授权

用户明确要求继续剩余实施，先补交付文档核查，并按台账推进HOLDOUT-BUILD和MODEL-DIAG。执行前Mac工作区干净，任务HEAD为`f76d0f4ab43a23b346e38069e6625aa64b859d0b`；SSH核对Linux隔离分支同HEAD、tracked干净，正式项目干净`main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`。本机`git ls-remote codeup refs/heads/main`得到同一发布基线；本地main对任务分支独有提交为0/136，Mac与隔离同HEAD为0/0。原stash保留。本轮只读远端，未同步checkout、运行训练/推理、读取受限测试语义、删除或恢复产物、push/merge。

本轮新增机器可读证据：[model-diagnostics-preflight-20260913.json](../model-diagnostics-preflight-20260913.json)，SHA `b0e379a02249647f6d9c731d6980ef7a0b08181f997341ae237d25359b448c39`。该文件保存六段实际执行程序、返回JSON、原stdout SHA及实际exit0，执行版本均为上述基线。`preflight/locate/development/links/recompute`在Linux执行；`threshold_probe`在Mac执行。Linux前四项用系统python3，复算用隔离`.venv-m3/bin/python`，Mac配置探针用`.venv/bin/python`。复算环境为CUDA不可见、HF/Transformers离线、`PYTHONDONTWRITEBYTECODE=1`；从SSH stdin执行JSON所载程序，输出保存到Mac `/private/tmp/mvllm2-next-20260913/` 同名文件。没有把Linux原记录复算说成模型重新推理，或把Mac配置验证说成GPU证据。

### 四份交付文档独立核查

独立reviewer在冻结`f76d0f4a`上只读核对TODO、Plan、handoff和verification。第47节证据通过：Mac原日志2694 passed/11 skipped、pytest774.28秒，runner实际exit0、外层1136.481秒；Linux原报告179 passed/114.27秒及1 passed/49 deselected/2.30秒、两进程exit0。两日志与报告SHA、Mac来源7/7存档、7/7保护文件、代码及四文档bundle和同步回执一致；两个工作区tracked干净，五修复文件摘要一致。独立者核验59个文件链接可达，并以五个旧CLI业务导入前的exit2证明退役状态。本轮没有重跑整仓测试或上轮独立探针，未改变整包代码审查冻结范围。

首轮结论有条件通过，发现两项P3：① TODO MODEL-DIAG/RELEASE-POINTER/FINAL-TRAIN仍指向已退役CLI；② TODO目标条目及Plan当前进度仍要求修复已闭环R6/R7和重做完整审查。主Agent已按实际公开入口修正，历史证据仍在原节保留；原旧指针任务改为适用性待确认，不自行取消用户目标。最终局部复核结论待本节末追加。

### HOLDOUT-BUILD：来源与入口前置

用户尚未提供未参与开发/调参或旧测试的新source，已请求具体训练机路径/采集批次。`/data/mVllm_2/data/releases`本次仅列出`data-v4.1-r1`和`data-v4.1-r2`；未读取真值。对几个旧集合候选路径的不存在性只作限定观察，不据此宣布历史sealed-test消失，也不全盘扫描。

`versioning/cli.py::_handle_data`明确拒绝`data release --purpose holdout`：真实业务构建仅发布development。`versioning/SCRIPTS.md`的Full holdout流程要求先有已构建审查冻结的release；claim和eval不会创建它。历史`pipeline/scripts/archive/build_v4_1_sealed_test_release.py`仍使用旧queue/batch与哈希release约定，不能直接成为完整data身份的新正式写入口。需先指定独立source并核对人工审查，再确认新构建接线；禁止从开发样本另划或给旧测试改名。完整media manifest、owner-only真值、质量/隔离证据、封存及预注册是前置；claim必须绑定最终model/eval身份，在首次调用前形成，不提前伪造候选身份。

另发现HOLDOUT-METRICS能力缺口：Mac只调用`finetune.eval_run._formal_config`，完整full/holdout配置配以TEST-POLICY七项原名阈值时拒绝，错误为`thresholds must name supported rates with finite minimum values in [0, 1]`；仅用受支持的joint门槛作控制时通过。当前支持六个通用正确率，不能原样表达宏召回、两类召回、runtime失败数和strict合法率；holdout评分及恢复路径也按这些metrics和统一下限比较。新增TODO前置，等待确认holdout接口扩展，保留七项原定义/阈值/比较方向，validation不变。本轮未改接口或评价口径；这个新业务衔接证据限制真实验收，不否定第47节针对当时冻结代码的独立审查已完成这一事实。

### MODEL-DIAG：已有开发记录重算与权重依赖

限定核对报告声明run、`workspace/runs`的一层名称、已知结果根、`workspace/evidence_archive`一层名称，以及历史run_identity指定的LlamaFactory路径和其已知experiments子目录。concise-cv约定run、三fold adapter/merged、逐样本预测/摘要/身份及约定实验manifest均不存在，所查范围未发现迁移备份。不能据此断言全机没有备份；下一步需用户给出精确备份/迁移位置，或恢复原开发证据后再验证。

历史`v4_1_0_760050fad303_20260724_visual/three_fold_validation/fold{0,1,2}`原记录可读，合计1,171,841字节。Linux从每条raw_output重新运行现行严格解析器和评分器（不修补缺字段），核对prediction、strict_valid、scores和重复candidate：全部零差异，各fold summary metrics完全相同。

| fold | 原记录条数 | source数 | 合法率 | joint正确率 | 当前权重路径 |
| --- | ---: | ---: | ---: | ---: | --- |
| 0 | 425 | 29 | 0.981176 | 0.421176 | run_identity的merged软链接断链 |
| 1 | 445 | 29 | 0.979775 | 0.343820 | 同上 |
| 2 | 346 | 22 | 0.947977 | 0.453757 | 同上 |

三对validation source交集均为0；只证明这些验证记录之间source不重叠，不替代每个模型训练排除关系。1216条合并重算合法率0.971217、joint0.402138、state0.496711、mechanism0.506579、site0.566612、special_case0.971217；旧three_fold_summary的state为0.496710，相差0.000001，各折计数与逐条评分无差异，后续使用精确合并计数，不改写历史summary。四状态macro recall为0.3705574936；召回为发生断裂137/408、未断裂408/547、临界未断裂50/161、已断裂9/100。它们仅描述历史保存输出，不是当前模型的新增效果证据。

三条merged链接实际指向`workspace/runs/v4.1-visual-cv-v1-seed3407/fold{0,1,2}/merged`且目标均缺失。未读取或哈希权重，不修复链接到同名其他模型。此新权重依赖并入MODEL-DIAG及MODEL-ARCHIVE，不创建重复缺失任务。完整每fold记录/summary/identity SHA、解析器SHA及readlink结果保存在上述JSON。concise的1581条、共同1216条比较及最佳checkpoint回载仍只有历史报告声明，本轮没有复算，不能用visual证据替代。

真实推理任务单尚不能执行：先找回concise及visual精确权重/配置/原记录并验签，确认fold训练排除关系；再确认冻结canary与Prompt交叉对照的诊断入口。当前正式eval仅支持全validation和训练冻结Prompt，不支持任意裸模型或Prompt替换，不能绕过正式门禁完成诊断。全量训练能力已完成代码接线，仍等待开发侧验收、holdout就绪和单独训练授权。Mac只见`/Volumes/Macintosh HD`，本轮未获真实移动硬盘挂载路径，硬盘及大型/外部依赖恢复继续待验收。

### 本批最终独立结论

独立reviewer对四文档修订、第48节和新增轻量JSON局部复核通过，无剩余可执行文档问题；两项P3及过程中两处状态残留已关闭。六段程序/原stdout/JSON/SHA一致；独立在Mac重跑纯配置探针、Linux重算历史1216条开发记录及readlink，均实际exit0且stdout SHA与原件完全一致。64个文件链接及diff-check通过。本结论覆盖指标实施前的准备快照，不包括后续七指标代码。用户随后明确回复“确认，按原七项门槛补齐”；该确认将由下一批Spec/Plan承接，准备记录的待确认描述保留为当时事实。


<a id="holdout-metrics-20260913"></a>
## 49. 七项冻结holdout门槛接线（2026-09-13）

用户明确确认按原七项门槛补齐，Spec55b3f4d4和Plan061d2598已分别单独提交。定义从冻结准备对应的Git代码`f04ca7cb:finetune/v4_1_stage_d_runtime.py`读取；没有打开其受限运行结果。原函数_recall/restricted_metrics/build_gate_reports规定四状态覆盖、先原计数再宏平均/六位小数、runtime等于0及其余下限；THRESHOLDS与准备manifest七项逐项相同。

新增finetune/holdout_metrics.py集中配置及指标定义，full配置严格要求七键和固定阈值，validation六通用指标不变；holdout prepare将该模块纳入冻结实现SHA，评分与未提交恢复从完整私有记录重算并核对restricted/metrics.json。普通summary及MLflow metrics仅保存七个gate_<原名>二值，不公开实际召回/正确率；完成恢复和Registry准入核对同一摘要承诺、完整七门与结果，不重读原truth。旧泛化full配置缺少七门时拒绝，历史事实和claim不改写。

原定义差分：Mac仅提取历史两纯函数，随机seed3411的200组合成四状态记录逐项比较，7值全部一致；原源码SHA `931fb805c888a2840a59c5af489d658c3528f3e67a966f1c9373f0cc556f5896`。程序与stdout为`/private/tmp/mvllm2-next-20260913/metrics_oracle.py`、`metrics-oracle.json`。新增单位边界28项通过；原holdout16项在四状态fixture下通过，这两次为阶段证据，最终组合运行及实际进程退出见下文。独立审查及Mac广回归正在执行；Linux待代码提交后按既有授权同步隔离工作区。

Linux后续精确输出目录预登记：`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/holdout-metrics-verification-20260913/`，只读预检不存在；七保护文件与第47节相同，正式main仍f1b7d8a3、隔离f76d0f4a且tracked干净。待本机代码原子提交后，仅按既有授权向隔离任务分支传递增量Git对象与CPU验证程序，预计两组数分钟、使用既有.venv-m3及依赖目录、禁用CUDA/网络模型下载；不写正式项目或正式产物。


### 本机与独立验证进度

代码/两份入口说明已原子提交`f1be1060207930bb58a9b43239a7f2efdc125ed8`，七文件SHA与Mac runner及独立审查冻结字节相同。Mac第一组训练/full/holdout/配置与claim相关回归207 passed/1 skipped、pytest65.65秒、实际exit0，外层70.946秒；skip为既有本机V4.1数据缺失。第二组Registry/MLflow/service广回归继续运行，不能将第一组代替最终联合结论。

独立reviewer局部代码/两入口说明通过，无可执行finding。其CPU回归93 passed/1 skipped、57.41秒、实际exit0，原函数200组差分全一致。额外探针先用路径别名被已有symlink门拒绝，改用/private/tmp实际路径后：私有metrics在评分承诺前被篡改，恢复报`holdout private metric evidence mismatch`且不consumed；仅还原自建fixture原字节后同Run正常完成。消费后禁止truth读取，Registry实际_run_eval_gate正常通过；向合成MLflow写gate_joint_correct_rate=0.9后准入拒绝，consumed字节不变。该探针为独立执行，主Agent不冒充复跑。

### 隔离同步与Linux复验启动

增量bundle（基线f76d0f4a，4提交/13文件）SHA `1a9a7fad7d468a8f7860d1802154d93e1e6fddf5cc022abb6e482b7f65748fd6`，含已独立核查的文档准备、已确认Spec/Plan及七文件代码。同步首次尝试用分支名fetch失败（exit128），bundle只导出HEAD；随后的runner因代码文件未到位在收集SHA阶段退出1，未执行pytest。核对`git bundle list-heads`后改为显式HEAD引用，再次验证保护文件、bundle SHA、0/4独有提交及精确13文件，只快进隔离任务分支至f1be1060，实际同步exit0。未覆盖代码、未修改远端配置或正式main；首次错误保留为编排错误，不当作代码测试失败或通过。

Linux从既有.venv-m3启动两组新CPU进程，使用原m5隔离依赖路径，CUDA不可见、OMP4及离线。七份代码摘要在启动前均与f1be1060匹配。运行目录内`linux-run.py`保存精确命令、实际subprocess退出码及日志SHA，结果待完成后追加。


Mac最终两进程均正常退出：第一组207 passed/1 skipped、65.65秒（外层70.946秒），第二组407 passed、292.47秒（外层325.118秒），合计614 passed/1 skipped、各exit0。第二组先打印摘要后仍有退出长尾，最终runner已取得subprocess.returncode=0。Mac证据目录`/private/tmp/mvllm2-holdout-metrics-20260913/`，group1.log SHA `d5446e28e14dae81d51e599b7f361650712a9cca2c065491c491f521c08b0cc2`，group2.log SHA `d8d0d035d6c32769943020f0084966444fbd32195e8cca4eebfbe252f130e9d3`；result.json保存精确命令、机器与七文件SHA，测试后七文件与代码f1be1060字节一致。runner启动基线为061d2598工作树，随后原子提交为f1be1060，运行期间实现未变化，不把基线提交冒充含有新代码。

独立93项回归和有效对抗探针只有reviewer工具调用原始回执，没有生成磁盘日志/脚本，故没有独立原日志SHA；不事后重建为原字节日志。原函数差分脚本及主Agent结果文件可存档，分别SHA `f46ec26416da4af98d7115a4ce1168151e583b99c12452e605b28f01367265fb`、`6352f9a847044ada3e52adf8b0073bb2b46a4ff1330d34d22c9a5c69c4ab687a`。独立者复用脚本得到相同200组结论，其输出仍仅在工具回执中；后续有效探针exit0，fixture为`/private/tmp/mvllm2-metrics-adversarial-we60zuw0`。这些证据来源限制不替代主Agent正式runner原件。

最终扩大到本批7份文档的文件链接检查发现finetune/SCRIPTS.md既有archive/README.md链接不可达，当前工作树不存在finetune/archive。已将这一历史提示改为从Git历史查询；全部表格中的当前Python文件均存在。该修改仅影响文案，不改变f1be1060运行代码或任何评分语义，独立最终文档核查另覆盖。

Linux第一组207 passed/1 skipped、92.20秒，实际exit0。第二组单进程发生Errno24 Too many open files并在pytest收尾退出1，没有完整成功摘要；原group2.log与result.json保留，不计通过。已拆出registry-service与mlflow-eval两个独立CPU进程，各独立basetemp/日志、OMP4并禁用CUDA，保持代码和系统限额，重验失败组的原407项；不重复首组207项。拆组解决的是本次测试进程资源累积，不宣称修复依赖库缓存或完成Linux单进程全套验证。


### Linux最终结果、证据存档与验收边界

同一代码f1be1060在Linux拆组复验正常退出：Registry/service 167 passed、183.42秒，MLflow eval 240 passed、190.89秒，各actual exit0；加首组207 passed/1 skipped，最终覆盖原614项通过/1项skip。原合并组exit1因文件句柄耗尽，保留为进程资源限制，不抹去或改报成功；不声称Linux单进程整套通过。Registry/service另有既有AnyIO BlockingPortal弃用warning，未更改依赖或系统限额。

- `registry-service`：外层198.249秒，exit0，log SHA `74807cf7a1830d14aa7f44661ba4c4eca7996922e8c59476318d37bd69445649`。
- `mlflow-eval`：外层213.367秒，exit0，log SHA `4ec7d1dfc931e3ff953e6e43dc713a68173291e0fa9fb33d47e1a3a7da8023b7`。

Linux原result.json SHA `ee9825795e2180cb35869e8e09e6a1c9e23922372f46b030b1268a0e73bb7150`，split-result.json SHA `67c8661a992cd3ce14b75990be1c47578e8bc9631bd10fadf6d9f8f1795b099e`，首组log SHA `77beed778cbbb5d1d257f338bae2e1e3b9a2d5aa8fa08757d2b8bb5e2345f531`，失败组log SHA `4d7ee9c3920ac3ee8348ccb9fef2bf9cda85ce287b3fc14cbcec2abbe146f1d1`。原件位于已登记Linux目录，11份日志/报告/runner/同步回执逐字节复制到Mac证据目录的`linux-evidence/`并全部验签。Linux另保存并验签6/6份Mac来源原件，`mac-evidence/manifest.json`明确`source_machine=Mac`、`linux_rerun=false`，不将存档说成Linux复跑。

最终postflight核对：正式项目保持干净main@f1b7d8a3，隔离分支tracked干净f1be1060；7/7保护文件SHA与预检及第47节一致，七文件测试版本摘要一致。Mac最后仅修finetune索引旧链接及本节等文档，运行代码/测试/版本化入口说明六文件未变化；不重复CPU测试验证纯文案。Codeup main再次只读核实仍f1b7d8a3。没有push或集成main、真实训练/GPU、真实holdout构建/使用、正式产物删除或硬盘恢复。

HOLDOUT-METRICS已完成本轮七门代码、双机合成验证及局部独立代码审查；真实业务数据验收仍归HOLDOUT-BUILD/MODEL-QUALITY。四文档初始缺口已在607a14b1闭环，本批最终追加文档和双机证据另交独立核查，结论随后记录。下一步仍是指定独立新source、确认其构建接线及人工审查，提供concise/visual模型精确备份位置；不放宽模型晋级规则以跳过这些前置。父任务M8及真实GPU/服务/硬盘/外部依赖整机恢复继续未关闭。


### 本批最终交付核查

独立reviewer对当前四份迁移交付文档及finetune/SCRIPTS纯文案、双机原件最终核查通过，无剩余可执行问题。核对Linux拆组文件集合完整覆盖原失败组，614/1skip不含首组重复计数；11/11 Linux副本与6/6 Mac存档均再次SSH验签，7/7保护文件及七文件代码版本一致，70个本地文件链接与diff-check通过。发现的HOLDOUT-METRICS“仍仅支持六指标”现在时残留已明确标为第48节修复前事实并复核。本次只读核查不重跑测试，前序独立回执无原磁盘日志的限制保留。

本批文档按本文件Git历史追溯最终原子提交；随后仅快进训练机隔离任务分支，精确同步回执落于上述Linux RUN的`final-docs-sync.json`，记录最终提交、bundle摘要、0/1独有提交及保护文件核验。该回执由主Agent对实际同步读回核对，不冒充独立reviewer已核验尚未发生的同步。正式main与push/merge授权边界保持。


<a id="holdout-build-routing-20260913"></a>
## 50. HOLDOUT-BUILD 构建链路只读核查与待决方案

2026-09-13，Codex 在 Mac 的干净 `0d8a9f55` 核查当前源码；未访问真实数据或远程机器，未执行测试、训练、推理或构建。第49节测试结果为前轮证据，本节不新增通过计数。

- `versioning/data_pipeline.py::run_input_review_export` 仅纳入 `scope == development`，且无 proposal 的普通候选不会进入人工队列。`_input_release_rows` 再次排除其他 scope，并只为特定普通未断裂候选提供自动准入。因此现有审查链不能直接作为新 holdout 全量人工审查入口；并非只增加发布 purpose 即可完成。
- `run_input_release` 输出训练 datasets、带标签的 training_candidates 和分布报告，调用 `seal_release(..., purpose=development)`。不得直接复用其完整 payload 作为无真值的 holdout 推理输入。
- `versioning/data_release.py::seal_release` 已支持 holdout、training_allowed=False 及隔离目录，但创建目录与封存并不证明 source 独立或人工审查完成。
- `finetune/eval_holdout.py::build_holdout_input` 的消费端要求 `evaluation_inputs/manifest.json` 使用 `tensile-holdout-media/v1`，绑定 data、development_data、split；样本仅含 candidate_id/source_video/video_path。评分端要求 `sealed_ground_truth/labels.json` 使用 `tensile-holdout-truth/v1`，标签集合与媒体候选精确一致。source_video 当前依赖 `video_数字` 身份约定，不在本轮擅自扩展。

**待确认推荐，尚非已批准 Spec：** 增加独立 holdout 审查/构建路径，复用媒体 pin、阶段证据和不可变发布机制；新 source 隔离清单 → 候选媒体 → 全量人工审查及冻结决定 → 无标签媒体 manifest 与 owner-only 真值分离输出 → 完整性/隔离验证 → 完整 data 身份封存。构建前以已冻结 development source 和旧测试 source 的非语义身份清单验证隔离；无法验证则拒绝，不根据布尔声明推断隔离。审查标签和类别分布不得进入普通公开 payload、日志或 Git；详细质量证据留在受限目录，公开报告仅完整性及通过状态。预注册和模型绑定 claim 保持原消费端时序，不由构建阶段提前消耗。

备选是导入外部已审查包，能减少内部审查实现，但需另立可信来源、审查证明和媒体绑定契约，不能消除验证责任。推荐独立原生路径的代价是新增审查作用域及受限工作区，须验证审查往返完整性、权限、中断恢复和开发路径兼容。它涉及公共接口、数据流与安全边界，须用户确认后修订 Spec/Plan，不能将上一轮七项评分门槛的批准扩大解释为构建链路批准。

本次仅形成源码定位与可审阅方向，尚未制定最终配置 schema 或具体 CLI；新 source 的路径/批次及非语义隔离清单仍未提供。真实 holdout 构建、读取与使用分别遵守原授权边界。


<a id="test-branch-20260913"></a>
## 51. train / test 数据分支完整接线（Mac合成验收）

用户明确确认补齐test数据分支的处理、人工审查、封存发布及最终模型测试接线，并统一叙述名称：train数据分支用于三折训练/验证及全量训练，test数据分支仅用于最终独立测试。代码字段/配置值development、holdout、test_audit及历史身份不改；前文旧称为历史记录。Spec042f335e和Plan66416f0f分别提交，代码abafdbf2。执行机器Mac，使用仓库`.venv/bin/python`；未SSH、未真实媒体处理、未GPU/真实训练/测试使用、未删除既有产物、未push/merge。

### 实施与范围

新增`versioning/holdout_pipeline.py`，由七阶段CLI显式`--purpose holdout --test-config`路由。独立全test批次输入（fold成员为空、历史参考语义records为空），对照pin钉扎的train/旧测试非语义来源审查清单检查ID与原视频摘要交集；train清单ID与已发布候选集合精确一致。原清单完整性和未用于调参仍是人工证据边界，缺失不补默认通过。

工作区和test审查包owner-only，逐候选人工决定完整绑定，禁止train自动准入混用。复制受限审查包后权限不符拒绝；UI草稿与回收输出受限。发布固定data身份、无标签媒体manifest、受限真值/审查/隔离原件/五阶段证据及仅通过状态的质量报告。原始配置和队列可追溯，授权目录保持未消费，数据命令不启动模型。数据验证只读，不创建工作区/锁/绑定；真实调用会读取当前新test真值，仍需适用授权。

最终full模型测试从构建器产物消费。prepare/run只验公开媒体及构建凭证整体摘要，核对train版本元数据绑定；score授权后读取真值并核对冻结构建摘要，未承诺恢复同样验证，已承诺恢复不重读真值。公开MLflow不包含裸真值摘要；新模块纳入评分实现快照摘要。旧对象缺构建凭证拒绝，不补证或重置claim。train代码字段/算法及七门阈值不变。test分支不自动DVC remote发布，现有dvc-config仍仅服务train；受限数据存储/真实环境仍须单独验收。

### 实际验证与原失败

最终runner基线66416f0f的工作树经六文件SHA逐项核验，与随后提交abafdbf2字节一致，不把基线提交冒充实现版本。最终两组：

| 范围 | pytest结果 | pytest秒 / 外层秒 | 实际退出 |
| --- | --- | --- | --- |
| test构建/最终测试、数据七阶段、CLI、审查UI | 265 passed | 38.91 / 40.904 | 0 |
| 七门、train验证/full训练、claim及隔离库 | 162 passed / 1 skipped | 38.91 / 42.880 | 0 |

合计427 passed/1 skipped，跳过为本机缺少V4.1实际workspace数据。所有模型/处理器执行为合成替身，不构成模型效果、GPU、真实媒体或Linux证据。保留已有295条warnings（含库弃用、裸Streamlit上下文及pytest临时目录清理提示），未修改依赖或系统限制。

正式首次组合保存在原目录`/private/tmp/mvllm2-test-branch-20260913/`：261 passed/1 failed、exit1；旧缺类测试在prepare后改写真值，新漂移门提前拒绝，故原'all four'断言失配。将缺类输入改在初始receipt/prepare冻结前构造后专项1 passed，最终新目录两组通过；原失败不覆盖。更早探索使用系统python缺mlflow而收集失败、fixture封存目录写权限及corrected标签与建议相同导致的失败均已修正；不把这些探索当验收。

### 独立核查

受派reviewer对本批局部实现与调用链独立核查，确认P1：构建后真值可漂移而评分仍接受；P2：rename后最终chmod中断导致重试永久失败。两项修复后原独立反例均通过。后续指出裸truth pin进入公开input的泄漏风险，已改为仅整体receipt摘要公开，授权score才取真值pin，独立复核通过。

独立实际构建器→claim→prepare→run→score、读取隔离与恢复验证通过。其一轮两文件加两探针为27 passed/1 failed（23.80秒、exit1），当时唯一缺类fixture断言已按上文修正；最终独立四项专项为4 passed/exit0（5.69秒），涵盖缺类门、release_validate不创建工作区、七阶段CLI、test UI私有输出。独立UI权限探针另1 passed/exit0；前轮train审查定向38 passed/141 deselected来源为reviewer前次工具回执，不作本轮复跑。最终局部代码及`versioning/SCRIPTS.md`新增操作说明核查通过，入口→审查→回收→发布→最终测试链可追溯，没有剩余可执行finding。未重做M8历史整包审查。

独立探针为`/private/tmp/test_holdout_review_probes.py`；其运行记录来源于reviewer工具回执，未声称存在独立原始日志文件。主Agent最终runner与两份日志、result原件在`/private/tmp/mvllm2-test-branch-20260913/final/`。

- `final/run.py` SHA256 `dac9640b2c8ce2202ae348e31d93072edb2960978213647763ca1e0389398fbb`。
- `final/group1.log` SHA256 `446791b18ff75999c3cfb47a98eb8eb2cc17433bc630e4d4ad6ffd9662261cbc`。
- `final/group2.log` SHA256 `055716d3869f4ed7fb6222dcc7190a63ab57f96a5a35344799c937f1387c73f8`。
- `final/result.json` SHA256 `20ce13251ae19ac350e2b7e194f22d4edc567abef46d55b72d71a17dbc1b83d8`。

冻结代码/测试摘要：

- `versioning/holdout_pipeline.py`：`8cf5a95845d8b632474229709849717f229b1833cd1df6cef41a39122fc0264d`。
- `versioning/data_pipeline.py`：`b7892bd2a753bfc71ff33343c25eaf95956d35d101916a5b41c25e30762e0d56`。
- `versioning/cli.py`：`6993d80325af9bdde5a1b851bee122f5031b452c9afc77c64d517a4c805ce6e9`。
- `finetune/eval_holdout.py`：`d5ba919cfc94b4c774032c4580ad867e19cee6cebe8885118ad41c8ea16ea4cb`。
- `tests/versioning/test_holdout_pipeline.py`：`2f766ff478add1a1249b8bc16693604f38a9a192cfbd6cb4913aa0ba019e7817`。
- `tests/test_eval_holdout.py`：`8573fd5d019bf5850b2610f06155dddd01d25a493d2b55857cfe4ee587383035`。

### 状态与交接

HOLDOUT-BUILD的本批代码/合成前置完成，父任务仍阻塞于独立新source、非语义清单、人工审查、适用真实构建/测试使用授权与真实环境证据。MODEL-DIAG缺权重/原件依赖未解除。Linux本批未同步或运行，前批双机614项不得算作此代码验证；之后同步前须重新核对两端状态。本机文档提交由Git历史追溯，不在同次文档内编造自身提交ID。

最终四文档独立证据核查通过：reviewer仅对照保存原件，复算runner/两日志/result摘要，确认六文件与abafdbf2及当前工作树一致、两组实际exit0、原失败保留、版本归属及真实/Linux限制准确；新增链接和锚点、diff-check通过。主Agent另核对五份相关文档的69个本地文件链接全部存在。本次证据核查未重跑测试或访问训练机。


<a id="linux-test-branch-source-20260913"></a>
## 52. Linux隔离验收与既定test视频划分调查

用户要求“推进第一步，第二步去训练机查看即可”，并指出test视频最初已划分。此授权覆盖隔离CPU合成验收与训练机来源/划分调查；未授权真实数据构建、训练、受限测试使用或重划分。本轮无代码修改，补充第51节实现的Linux证据。

### 同步及Linux CPU验收

执行前Mac7b0e01d5干净；正式Linux`/home/liuyang/文档/mVllm_2`为干净main@f1b7d8a3，隔离`/home/liuyang/文档/mVllm_2-migration-7eeb93a7`为0d8a9f55、tracked干净，既有未跟踪环境和证据保留。核对七保护文件摘要后，在新目录`test-branch-verification-20260913`保存证据（下称RUN）。bundle包含0/5提交差，12个精确文件，SHA256 `23f32a21f11510fb91846a95a7fd34dfd55cb249eac361cf3203457eb579d037`；校验bundle HEAD、独有提交及文件集合后，仅在隔离任务分支ff-only快进至7b0e01d5，不操作正式main或push。

运行解释器为隔离区`.venv-m3/bin/python`；复用原项目级依赖，PYTHONPATH为`.:m5-service-verification-20260912/dependencies`，CUDA设备为空、OMP线程4、模型hub离线。runner、命令、环境和结果均保存在RUN。

| 测试组（与Mac第51节相同文件集合） | 结果 | pytest秒 / 外层秒 | 实际退出 |
| --- | --- | --- | --- |
| test七阶段/最终测试、数据pipeline、CLI、审查UI | 265 passed | 45.04 / 47.611 | 0 |
| 七门、train验证/full训练、claim与隔离库 | 162 passed / 1 skipped | 60.90 / 66.256 | 0 |

共427 passed/1 skipped；skip为隔离区缺V4.1 workspace真实数据。六文件SHA与abafdbf2以及第51节Mac最终测试一致；不重跑Mac，不把两机器计数相加冒充不同测试覆盖。本次实际进程均正常退出，无文件描述符耗尽失败。仅合成媒体/模型替身，非真实训练、GPU或模型效果。五份Linux runner/result/logs/sync原件已复制Mac并重算摘要一致；七保护文件前后未变，正式main和隔离tracked保持干净。

### 既定来源已定位

原始划分位置为`/home/liuyang/文档/mVllm_2/workspace/data/source/splits/`，其七份JSON为含video_ids的mapping。第一版只读探针假设其为ID列表而断言退出；核对schema后修正为提取video_ids，再成功完成，未写入源数据。训练机无rg，文件发现改用限定目录的Python列举；没有全盘扫描或读取受限语义结果。

`test.json` SHA256 `26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc`。其21个test source如下：

`video_0005, video_0008, video_0010, video_0018, video_0019, video_0025, video_0032, video_0037, video_0038, video_0041, video_0062, video_0063, video_0067, video_0078, video_0082, video_0087, video_0088, video_0089, video_0093, video_0094, video_0095`

train分支union为89source；三折train/validation分别59/30、59/30、66/23，各折内部无ID交集，与test的ID交集均为空。test列表与`workspace/data/derived/metadata/test_manifest_sha256.json`中的21个ID完全一致。`workspace/data/source/videos/<video_id>.mp4`对应21/21文件存在、非链接且大小>0。此处只做stat，不读/解码视频或计算原视频内容摘要，故身份隔离不等于已证实内容无重复。无需再让用户提供这一已定位的既定路径。

### 历史使用资格边界

在训练机既有`finetune/results/v4_1_stage_d_claims/v4.1-sealed-test-5546b8bf1ec3/claim.json`找到一次性claim，preparation为`stage-d-preparation-5cd1b3fa343c`，run为`stage-d-run-da566a5644f8`。同run的`stage_d_gate.json`记录completed及`sealed_test_exposed: true`；只提取身份和非语义暴露/状态字段，不读取evaluation_records、restricted summary、真值或审查标签。prepared_run_manifest记录旧release共299样本、20source，manifest摘要b996f054…与仓库既有release_summary一致。

prepared记录的旧目录`/home/liuyang/文档/tensile-data/current/sealed_test_releases/v4.1-sealed-test-5546b8bf1ec3`当前不存在。关联依据为仓库既有`docs/results/v4_1_stage_d_sealed_test_release/release_summary.json`（SHA256 `8abf67c9b35cb07889222e365ac0e667439526da83f8765620e74f6aa0004edb`）：其release_id/manifest_sha256与训练机prepared记录相同，identity.media_id为`candidate-media-53d068569a09`；不是仅凭source数量相同推断关联。其现存332份媒体receipt的**文件名**映射20source，均属于既定21个test，唯一没有该批receipt者为video_0005。未读取receipt内容、候选审查标签或受限测试语义。

这证明既定划分存在及历史发布已暴露，但尚无299样本release到这20source的完整逐项映射；物化receipt不能直接当精确暴露清单。video_0005没有这批receipt不证明从未使用，也不能直接认定适合独立测试。原release目录缺失同样不能取消历史暴露。保留已确认TEST-POLICY，不擅自把21个视频整体重新视为未使用测试、不重划分、不生成或消费新claim。下一动作是核清现有source使用资格与非语义溯源、准备明确输入清单，随后按适用授权推进真实test构建/审查；出现政策冲突再提交具体裁决，不重复询问已找到的路径。

### 原件、摘要与独立核查

RUN绝对路径：`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/test-branch-verification-20260913/`；Mac副本：`/private/tmp/mvllm2-linux-test-branch-20260913/`。两份调查程序及其过滤结果已存入RUN；不保存真值或逐样本语义。文件摘要如下（postflight在Mac副本名为postflight-source.json）：

- `run.py`：`a4de7cc300671d59f73629e1d1e3e688709057eefb2a7b5151721b9f2a2bc1b9`。
- `result.json`：`3fa32ed09b611c7a422bdf8c4d923e4e31a5f5d7663a0cb457a3aa784a733c2a`。
- `group1.log`：`a09819ba88319d91fc2a5b707ef52a688ea8e96a6f390655e5a3747161835230`。
- `group2.log`：`26ba1d2aa91c88300a30d18e86e21be83b1fae3eb9e877c1eabc385d20ece0e4`。
- `sync.json`：`0229cacbc37a34ad2d701e8be80a69aa6856547fb009fe2c5bde86bb1af0a513`。
- `split-audit-vetted.py`：`affeccb059b2329e0a9c5fc93e3d8772b00aee0359a7720f00b0aa284e468b45`。
- `split-audit.json`：`c4e135adec41ce6ee92921fa0d0220d2ebef382f042dfd12965f5cd623b6deb4`。
- `usage-audit-final.py`：`004a12a5c251e4e9285f03aa8795a5f4bb58fe9592f5affcba473bbb54d79ae6`。
- `usage-audit-final.json`：`aed3c09635e15a5a4aee3775e0079cda2c87e8bd997ff1d595225e87a6b3f508`。
- `postflight-source.json`：`ab1e9b9d016a2cf9bf63cf130ee7ac8bd472f0ec568e74d447af7a6610b5edf5`。

独立reviewer只读核对保存原件副本及代码提交：两组计数/实际exit、五份验收文件摘要、六代码摘要、七保护摘要、21/89集合关系、媒体stat和历史资格边界均通过；没有重跑测试或读取受限语义。当前四文档随后另行核查；文档提交及隔离同步由Git历史及RUN最终同步回执追溯。

第52节四文档最终独立核查通过：10份证据摘要及旧release_summary关联pin重算一致，计数、机器版本、来源已定位纠正、资格与内容哈希限制均准确；新增链接与锚点、diff-check通过。主Agent另核对四文档70个本地文件链接可达。此结论不包含未来提交/同步；最终仅隔离分支文档同步的主Agent回执保存为RUN/final-docs-sync.json。


<a id="test-source-history-20260913"></a>
## 53. test source历史使用映射限定只读调查

用户明确授权继续沿已有preparation、claim、发布摘要和媒体凭据查找旧发布备份/迁移清单，并单独追查video_0005；本轮只读取非语义身份信息，没有读取旧真值、预测、受限评分、审查标签或候选语义内容，没有运行测试、训练、推理或构建真实数据。上轮Linux427项为既有验证，不在本轮重跑。Mac起点02ed8a4a干净，Linux正式main为f1b7d8a3、隔离为02ed8a4a，tracked均干净。

调查范围为项目workspace/data迁移清单、既定run_identity、当前derived/metadata与已发现备份`/home/liuyang/文档/mVllm_2-data-backups/pre-semantic-portal-20260723/data/07_metadata`。目录枚举限制深度并排除审查决定/队列/参考、受限目录、视频和帧；读取限定manifest/identity的身份字段，不读取test_candidate_audit、test_materialized_audit、review_queue、evaluation_records或restricted summary。

### 已证实事实

- `workspace/data/migration_manifest.json`声明source_root为原tensile-data/current，目标为workspace/data，映射仅source、derived、training_releases→releases，verified=true只覆盖声明的20718文件及两个train release摘要；没有sealed_test_releases映射。不能从verified推断旧test发布已迁移，也不能从此清单独断旧目录被谁删除或是否另有备份。
- 已发现备份名称为pre-semantic-portal-20260723，其data顶层有05_splits、08_training_ready等旧布局目录名，07_metadata内确认两个候选媒体集合；本报告不以目录名证明其中划分文件或train发布的存在及完整性。限定枚举未找回独立测试release的manifest或一次性凭据副本；不将目录日期单独作为内容年代或完整性的证明。
- 当前数据4个、该备份2个媒体receipt集合，分别1617/904/410/332和1617/904个文件。六集合均未出现video_0005；两个备份集合的文件名清单摘要与当前同ID集合一致。因此增加了跨已发现集合的负向证据，仍不构成“从未使用”的证明。
- 18份相关manifest/identity的身份字段已核查，没有恢复出299样本的完整candidate→source发布清单。历史run_identity仍绑定release v4.1-sealed-test-5546b8bf1ec3、manifest SHA b996f054…、preparation、authorization及sample_count=299；没有逐样本身份列表。
- run_identity.status仍为authorized_not_started。历史代码`f04ca7cb:finetune/v4_1_stage_d_runtime.py`初始化身份时写入该值，执行结果另产生sealed_test_exposed=true的gate；此初始文件不能推翻第52节同run的completed/exposed记录。未重读受限结果。

### 逐source资格结论

| 范围 | 已有证据 | 本轮分类 |
| --- | --- | --- |
| 第52节列明的20个source（排除video_0005） | 与已暴露release关联的媒体物化身份存在；完整299样本映射仍缺 | 证据不足：不能标为未使用，也不把物化清单冒充精确暴露清单 |
| video_0005 | 原视频及既定test划分存在；六个已查receipt集合均无记录 | 证据不足：未生成候选的具体原因和其他使用情况未证明 |
| release/run级 | 同身份claim与后续exposed/completed gate | 已证实该历史release发生暴露；不能重置使用资格 |

本轮“已证实未使用”的source数量为0，含义是没有取得这类充分证据，不等于证明全部21个均被使用。静态候选算法存在按source类型/事件可靠性跳过等路径，但未读取对应source语义字段，不能把某条算法路径指定为video_0005的实际原因。

下一步最小材料为旧release的**无标签candidate_id/source_video发布清单及其与冻结manifest的绑定**，或包含该清单的准确备份位置。此前找到的21个路径无需重复索取。现有授权下的已知位置调查完成，未擅自扩大至其他项目、全盘扫描或受限语义文件；未修改TEST-POLICY或批准复用。

### 原件与验证

本机程序及过滤结果：`/private/tmp/mvllm2-test-source-history-20260913/audit.py`、`audit.json`。程序通过SSH在Linux执行，实际exit0；保留完整的被读文件路径/SHA、六集合身份摘要、18份身份文件的投影和两工作区HEAD。没有原视频内容摘要或模型效果结论。

- `audit.py` SHA256 `f7f0add7178abc9c90d2b159bfba897d588331fb1ee5d20f105db8f3da437671`。

- `audit.json` SHA256 `f73f617d6cda34c61493418558f00d7bd55d07e62bff2bb9a383cf928a420c73`。

两份只读调查原件已复制并验签至隔离证据目录`/home/liuyang/文档/mVllm_2-migration-7eeb93a7/test-branch-verification-20260913/source-history/`；只写新证据目录，不修改调查源。

四文档追加内容经独立reviewer核查通过：两份原件摘要、六集合计数/身份摘要、18份身份路径及历史初始化/完成状态语义均一致；备份目录名与实际内容证明已明确区分。核查仅使用保存证据与历史源码，未新增远端扫描或测试。最终文档提交由Git历史追溯；隔离同步结果另存上述source-history/final-docs-sync.json。


<a id="model-location-followup-20260913"></a>
## 54. MODEL-DIAG模型位置限定续查

2026-09-13 MODEL-DIAG限定目录续查：Linux只读目录与路径stat实际exit0。evidence_archive顶层5组名称不含目标concise/visual三折；现存concise-v1仅input/reference、concise-v2仅input，不能替代concise-cv；/data/mVllm_2/workspace仅data、finetune仅active_data_release.json。六个约定三折merged目标仍不存在。未检查其他发布库内容或全盘备份，不能断言模型全部丢失；没有读取权重/预测/test内容或重跑既有评分。下一步需目标身份绑定的模型/原始预测备份，或另行确认诊断方案；test资格阻塞不取消MODEL-DIAG，也不授权重训。证据见verification第54节及docs/results/model-location-followup-20260913.json。

本机基线bb73e4dd，远端隔离同提交且tracked干净；正式main仍f1b7d8a3且tracked干净。本轮只在Mac保存轻量证据和维护台账，没有修改远端文件，也没有同步本轮提交。七个明确目录和六个merged路径的读取程序、实际输出及SHA保存于[调查证据](../model-location-followup-20260913.json)，文件SHA256为`f70bf9b73d90015324d1b23e811ed279aaf8df0fa8d8ce244d1252efdaf4ddd5`。这里的“目标不存在”指实际stat的路径，不证明其他位置没有副本；目录名不证明其中内容完整。前轮visual1216条复算属于第48节既有证据，本轮未运行测试或推理，没有新的模型效果结论。

本轮为既有任务的证据补充和执行顺序纠正，主Agent核对JSON可解析、程序摘要、目录/路径数量及Git diff；不冒充独立审查或权威操作手册验收。


<a id="model-recovery-targets-20260913"></a>
## 55. MODEL-DIAG发布库身份与恢复比对目标

2026-09-13 MODEL-DIAG发布库身份及恢复目标：Linux只读release-manifest核查exit0，已知legacy发布库只有v4.1-agent-pipeline-fold0-r1，origin为coverage-first单折实验，不能替代concise/visual三折。已从历史concise报告提取三折summary/records共6个SHA256恢复比对目标；尚未找回文件，报告摘要不是原件或模型权重的独立证明。已知位置线索核查到此收束，等待准确备份路径/迁移记录；不重复扫描、重训或擅自改用其他模型。详见verification第55节。

[恢复比对证据](../model-recovery-targets-20260913.json)包含远端只读程序/摘要、发布manifest身份投影及文件SHA、历史报告文件SHA与六个逐fold恢复目标。现有release的origin为`v4_1_phase2_source_aware_3k_coverage_first_2a84e8b6cfc3`、fold0、seed3407、1125steps；仅核查身份清单，没有读取或哈希权重。其current链接解析到该release，不表示三折模型找回或最终模型验收通过。

本机基线0c6169e3；远端正式main f1b7d8a3、隔离bb73e4dd，tracked均干净。历史报告给出的三个summary及三个records摘要仅用作恢复后的比对依据；报告自身注明未独立审查，当前未验证这些原始文件。未来原件即便匹配，也须另外核验模型、Prompt、数据及fold训练排除关系。

主Agent核对JSON、程序摘要、六个目标的唯一性与报告对应关系，git diff --check通过；未运行模型测试、GPU推理、训练、真实数据构建或受限test读取，未修改远端或同步本轮提交。本轮没有新的模型效果结论。


<a id="conditional-cleanup-20260913"></a>
## 56. 旧数据与模型条件清理预检

2026-09-13 条件清理授权（Codex）：用户明确旧数据和旧训练run/模型两类均包括，只删除已验证完整迁移且不再需要的旧副本。本轮Linux预检exit0：历史迁移source_root已不存在；pre-semantic备份不在该迁移清单映射内；旧LlamaFactory顶层16个模型软链接，10个目标存在、6个断链，不能当作重复权重。workspace/runs包含迁移后的实际目标，当前发布库保持保护。删除白名单为空，实际删除0、释放0字节；不是授权缺失，而是完整迁移/冗余性证据未满足。后续先建立旧备份到保留位置的逐文件映射、内容一致性和引用退出证明，再在本次条件授权内清理；不继续索取缺失三折模型备份，不把此次决定解释为取消MODEL-DIAG或TEST-POLICY。

[预检原件](../conditional-cleanup-preflight-20260913.json)保存SSH程序、摘要、实际exit0、迁移清单与两份receipt、16个旧模型链接目标和两端Git状态。本机基线cf40dd70，远端main f1b7d8a3、隔离bb73e4dd均tracked干净。本轮没有远端写入；未读取权重或受限test，未计算整树一致性。主Agent验证JSON、程序摘要、16链接/10有效目标及空删除列表，git diff --check通过。迁移receipt committed不证明source/derived/备份全量移走；既有整机/大型产物恢复缺口仍在。此为清理预检记录，不是已完成删除或独立审查结论。


<a id="train-video-cleanup-20260913"></a>
## 57. train原视频副本逐文件核验与删除前阻塞

2026-09-13 train原视频清理候选：按用户条件授权在Linux核对旧备份01_videos到workspace/data/source/videos，89个train视频逐文件大小/SHA256一致，共5852142357字节（约5.45GiB），21个test视频未读内容。两工作区tracked运行代码/配置未见该备份路径引用。删除程序的占用预检遇到不可读/proc文件句柄，实际exit1且发生于首次unlink和证据目录创建之前；sudo -n只读能力探针要求密码，未提权。删除0、释放0，旧副本保留。候选清单与完整程序已保存；后续完成有权限的占用检查后再沿用授权执行，不能把候选已验签写成已删除。

[逐文件证据与程序](../train-video-cleanup-candidates-20260913.json)记录每个旧路径、保留路径、SHA256、大小、inode/mtime及远端Git。内容核验SSH实际exit0；删除尝试exit1（原stderr保留）。不可读PID最初为164474/271119/3474702；随后ps显示前两者为sd-pam和ssh-agent，第三个已退出，未将进程名当作完整占用证明。没有改系统权限、停止进程、读取test内容或删除其他产物。此批只核定89个train原视频，不外推整个备份或模型可删。主Agent检查JSON、89条唯一映射/摘要、总字节和diff-check。


## 58. 工程收口与模型交付拆分

2026-09-13 用户确认工程与模型交付拆分，Plan单独提交0d3c7461。TODO新增合并前/后续模型/非阻塞清理矩阵及MODEL-DIAG方案草案；原Intent/Spec无需改写。真实GPU、服务成功路径和恢复缺口仍逐项保留，未因拆分自动通过或豁免。下一步先做train真实输入预检与具体缺口裁决单；不再以清理或找回旧模型占据主线。本轮无远端操作、训练、测试使用、删除或push/merge。

核对现有Intent明确迁移不等于模型质量，Spec明确服务接管与模型可用性分验且移动硬盘可单独未完成；保留所有原门禁。本机起点4a7244c9工作区干净，相对本地main为0/152；此为本地快照，不冒充本轮远端刷新。主Agent检查固定任务标识、依赖与授权表述及diff-check；只维护任务记录，不运行测试或宣称独立审查。


## 59. train真实输入内存构建预检

2026-09-13 train真实输入预检：Linux隔离bb73e4dd执行正式build_versioned_datasets(scope=full)，实际exit0；data-v4.1-r2 + prompt-v4.1-r1 + 原workspace/data媒体根成功生成内存输入。三折train/validation为1253/425、1014/664、1186/492，full为1678，唯一媒体1678个共165485727字节逐一哈希；媒体名提取source与既定21个test ID无交集，此项不代替内容隔离或test资格。没有Run写入、训练或GPU执行。完整结果摘要见docs/results/train-input-preflight-20260913.json及verification第59节。

[轻量结果与程序](../train-input-preflight-20260913.json)记录实际代码版本、三折/full计数、生成内容摘要、媒体集合摘要及原始结果路径/SHA。仅使用train发布内容，test只比对既有非语义ID；未输出标签。远端正式main f1b7d8a3、隔离bb73e4dd事后tracked干净。本机0054b419为文档后续版本，不能冒充远端运行HEAD。原始结果包含1678条媒体哈希；轻量记录不声称是全部原件的独立备份。主Agent检查计数、媒体ID交集、JSON和diff-check，本轮非独立审查、无新增CPU回归或模型效果结论。


## 60. M4基座、配置与资源准备

2026-09-13 M4配置/资源预检：基座路径models/minicpm_v_4_5存在并解析到models/minicpmv4_5，config声明openbmb/MiniCPM-V-4_5；仅stat/配置，未验完整权重或冻结修订。4090查询时24564MiB总显存、约1081MiB使用、利用率0%；/data约3.4TiB可用。cpm45有torch/transformers/peft等训练包，但importlib.metadata未发现mlflow分发包；正式适配器在同进程调用run_training，不能假设CPU隔离环境与GPU环境已贯通。公共入口仅cross_validation三折整组或full，没有单折选项；前文“现成单折工程验证”建议收窄为待设计方案。下一步先核对完整执行环境与有限三折工程验证方案，不创建训练版本、不启动训练。

[环境与资源原件](../training-readiness-20260913.json)保存程序、实际exit0、包版本、基座文件stat与配置身份、GPU/磁盘输出及远端Git。代码依据finetune/train_prepare_run.py的prepare_versioned_run仅接受三个fold或full，以及execute中的同进程run_training调用。前序历史YAML仅作候选参数参考，旧数据名、相对模型路径和输出路径不能原样用于新训练。

工程验收若需要真实成功证据仍要实际执行有限训练；这不代表必须重做完整质量训练。最终模型交付另需开发验证与full训练。有限工程Run不能凭loss或完成状态登记为质量passed。cpm45缺mlflow仅指分发元数据查询结果，不声称已做import或运行兼容验证。本轮未安装依赖、加载模型、GPU推理、训练、test使用或远端写入；主Agent核对JSON与diff-check。


## 61. 用户范围澄清、agent环境及基座完整性

用户明确本分支是版本身份与DVC/MLflow链路迁移、全部入口接管，不要求重新微调；旧模型保留，质量门不补passed。Spec a5cfa86f与Plan efde1536记录纠正。逐折运行要求已记录M4-FOLD，具体接口方案待确认。

Linux agent环境只读元数据：torch2.5.1、transformers4.56.1、peft0.18.1、accelerate1.11.0、bitsandbytes0.49.2、llamafactory0.9.6.dev0；直接查询mlflow/mlflow-skinny/dvc分发包均无，find_spec(mlflow)为None。未加载模型或安装依赖，不能据此声称运行兼容性通过。

基座/home/liuyang/文档/mVllm_2/models/minicpmv4_5：29个顶层文件全部流式SHA256，读取前后大小/mtime未变；4个safetensors分片索引映射、849个tensor、数据区连续偏移及total_size=17391790560一致，SSH实际exit0。文件清单按名称排序、JSON sort_keys=True/separators=(逗号,冒号)编码的内容摘要为`2ffb284ff1a0db561633e91c768c1a9732b33838147113004966c1ff112faa21`。下载备注为Revision:master，缺可信上游固定修订摘要；本次只证明本地内容指纹与结构一致，不证明上游真实性或可加载，不创建正式训练冻结记录。隐藏._侧车也已哈希且保留，未删除任何原文件。

必要文件摘要如下；不另建长期结果文件：

| 文件 | 字节 | SHA256 |
| --- | ---: | --- |
| ._model-00001-of-00004.safetensors | 4096 | `492e691774684f6a624ea5a9cd7c68ad1ea38ac3c083c91d9319bfe14d1af9b5` |
| ._model-00002-of-00004.safetensors | 4096 | `492e691774684f6a624ea5a9cd7c68ad1ea38ac3c083c91d9319bfe14d1af9b5` |
| ._model-00003-of-00004.safetensors | 4096 | `492e691774684f6a624ea5a9cd7c68ad1ea38ac3c083c91d9319bfe14d1af9b5` |
| ._model-00004-of-00004.safetensors | 4096 | `492e691774684f6a624ea5a9cd7c68ad1ea38ac3c083c91d9319bfe14d1af9b5` |
| .msc | 1766 | `52f3ec11f0c281c0b094202c53ef760b7484948eccfb3f6c0a62a8128e79e7f4` |
| .mv | 36 | `de31a81198609b9e042141f3b3060e12122007854e616728b08001315cee14d2` |
| README.md | 25454 | `5ea75ed3217e073b80ae1c857f5b90b64f120b63d755177d28fd478120b3fa64` |
| added_tokens.json | 2862 | `1f41288392d77dd5dd9f235bdef78a3152d41651ff56b15ebdec476e3aa1cb7f` |
| config.json | 1461 | `1d6f6eb441da34dcb43db72cf3960254c7045cc2c595a3c836ae71136655ccc8` |
| configuration.json | 51 | `2d4464e2ead06bc9bc718c781309ad1e7baded626d66e8dcdc8b469ba185faf0` |
| configuration_minicpm.py | 3288 | `bfdb65b291246e0d709831df2e10aaba96b94d2369f670f3ad831711d2f97e45` |
| generation_config.json | 268 | `4009ca3d9e615561897c0f4963bd01c26bccff50eda4b00fcf2c13cf3fcc86db` |
| image_processing_minicpmv.py | 20757 | `52888748938f40fec0827d187383b4a8fa857f4cffad5a0939e2e449051950d7` |
| merges.txt | 1671853 | `8831e4f1a044471340f7c0a83d7bd71306a5b867e95fd870f74d0c5308a904d5` |
| model-00001-of-00004.safetensors | 5286612176 | `22643c1760b755c3c83b8631cd767fd667cb8aaababee5e4b3113210cd6177f0` |
| model-00002-of-00004.safetensors | 5301855088 | `8be1ef2c54e913ef8824520cfa9b4e604c2afcf089907992b340048bf502896a` |
| model-00003-of-00004.safetensors | 4546851120 | `9a2bd9a7b254f0671bccb84953876111fa64b889507dc12e22e98a1143b64fd7` |
| model-00004-of-00004.safetensors | 2256571800 | `f425aa9a351f9e9f600d1235e9a583ff6931a5225e7b2b02a159248b32bd522e` |
| model.safetensors.index.json | 72172 | `6336714ff43484b398f021536c5eb39b11b68c439420f570d618e8b8943a6749` |
| modeling_minicpmv.py | 18609 | `f385948d8321fc9e30b178f7bb39020c845c7b367eeb0b762a50746368b25d10` |
| modeling_navit_siglip.py | 41835 | `c71ca316fe7405325b7097364f98f71c317fff8c9f5c8820f30d3362b1ed5bfa` |
| preprocessor_config.json | 714 | `5c0dbc92920ded2304e2ed6ad4251da56029aa1f3f69427117ac6df9bc68496e` |
| processing_minicpmv.py | 11026 | `aeb292555aba3362108eb10827234c48b9fede526398cc15bdbec798ba2c7fdd` |
| resampler.py | 11732 | `9258b6e6e0b66fd5d3ce7127372fd82eff3659481602658045c253ae18e8d5be` |
| special_tokens_map.json | 12103 | `742d22f66cc33f367b17d45d8dcb5ffde7d777fe94a9b05ee858dc43018c2016` |
| tokenization_minicpmv_fast.py | 1647 | `770e4a934f2e74e0e88e85126bceea93e345d84b411d21e99b38c5cfd095f736` |
| tokenizer.json | 11437868 | `c5a94a2c3913b8aa2175fffb5fd6cf4301958f323d06475bfd91037c13bdd74b` |
| tokenizer_config.json | 25786 | `8cbacbea273108831f02441518bbbc73627c15e34ddaa3fec6369e7bd07b720c` |
| vocab.json | 2776833 | `ca10d7e9fb3ed18575dd1e277a2579c16d108e32f27439684afa0e10b1440910` |

这是完整性核查，不是数字签名验证或模型效果验收。仅临时计算输出与本节必要摘要，未新增仓库结果JSON。本轮未使用受限test、训练、推理、修改环境或远端状态。
