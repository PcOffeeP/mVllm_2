# 虚拟视频测试集泄漏审查与 110 条真实源视频去重审计

> **状态**：只读审查报告（2026-11-25）；**基线提交**：`d8e0b35`（`github/feat/tensileagent-finetune`）。  
> **核心问题**：本仓虚拟视频（`data/virtual/video-V1`，65 条）中哪些参考了固定测试集（`data/splits/three-fold/test.json`，21 条）或其近重复真实源、是否存在训练/评测数据泄漏，以及是否存在超过 65 条的新增虚拟视频。本次未修改任何划分、标注表或媒体文件，也未连接训练机或运行模型推理。

---

## 1. 审查结论总表（虚拟视频 → 测试集数据泄漏判定）

**总体判定：存在明确的虚拟视频 → 测试集关联风险；65 条 `video-V1` 中共 15 条须严格禁用于训练与开发调参（12 条直接参考 `test` 源 + 3 条通过真实源近重复间接关联 `test` 源），其余 50 条仅关联开发源（须按所在折隔离，不得跨折泄漏）。**

| 泄漏分类（`leakage_type`） | 虚拟视频数 | 涉及参考真实源 | 占比 | 处置结论 |
| --- | ---: | --- | ---: | --- |
| `direct_test`（直接参考固定 `test` 真实源） | **12** | `video_0025`（1 条）、`video_0032`（11 条） | 18.5% | **强制隔离**：禁用于训练与开发调参 |
| `transitive_via_near_dup`（参考与 `test` 同实验近重复的 `dev` 真实源） | **3** | `video_0006`（`fold_0_val`，经核实为 `test` 源 `video_0010` 的同实验近重复） | 4.6% | **强制隔离（本次新增）**：原[虚拟视频溯源报告](virtual-video-provenance.md)仅隔离 12 条，本次审计后须同步纳入隔离，**合计 15 条** |
| `clean_dev_only`（仅参考未与 `test` 重合的开发源） | **50** | 其余 8 个开发源（`video_0003`、`0014`、`0020`、`0040`、`0050`、`0058`、`0097`、`0100`） | 76.9% | 可用于开发/非冻结诊断，但**严禁将参考某折 `val` 源的虚拟视频投入该折训练** |
| **合计（本仓 `data/virtual/video-V1`）** | **65** | **11 个 `source_id`** | **100%** | 本仓 `data/virtual/` 无超过 65 条的新增已交付数据包 |

> **关键补充核对**：经逐条核对 `BlenderTensileVideo/datasets/video-V1/manifest.json`（与本仓 `data/virtual/video-V1/manifest.json` 65/65 ID 及 SHA-256 零失配）：
> - `video_0010`（`test`，与 `video_0006` 近重复）在 `video-V1` 中直接派生虚拟视频数为 **0**（3 条金属韧断虚拟视频均登记参考 `video_0006`）；
> - `video_0079`（`fold_1_val`，与 `video_0032` 近重复）在 `video-V1` 中直接派生虚拟视频数为 **0**（11 条淡绿高分子脆断虚拟视频均登记参考 `video_0032`）。

### 1.1 须隔离的 15 条虚拟视频逐条清单（12 条直接关联 + 3 条间接关联）

| # | `virtual_video_id` | 本仓相对路径（`data/virtual/video-V1/` 下） | `referenced_source_id` | `source_split` | `leakage_type` | `recommended_action` |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `polymer_yellow_film_grip_root_baseline_v2` | `videos/polymer_yellow_film_grip_root_baseline_v2.mp4` | `video_0025` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 2 | `polymer_pale_green_brittle_flat_strip_baseline_v1` | `videos/polymer_pale_green_brittle_flat_strip_baseline_v1.mp4` | `video_0032` | `test`（且近重复 `fold_1_val` 的 `video_0079`） | `direct_test` | 禁用于训练与开发调参（隔离） |
| 3 | `polymer_brittle_stage1_position055_v1` | `videos/polymer_brittle_stage1_position055_v1.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 4 | `polymer_brittle_coupled_position055_time12_v1` | `videos/polymer_brittle_coupled_position055_time12_v1.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 5 | `polymer_brittle_527d847f2741` | `videos/polymer_brittle_527d847f2741.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 6 | `polymer_brittle_7c88eeeae51f` | `videos/polymer_brittle_7c88eeeae51f.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 7 | `polymer_brittle_b0cd99f7ae30` | `videos/polymer_brittle_b0cd99f7ae30.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 8 | `polymer_brittle_b9ab8a238e19` | `videos/polymer_brittle_b9ab8a238e19.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 9 | `polymer_brittle_bcfe3a307376` | `videos/polymer_brittle_bcfe3a307376.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 10 | `polymer_brittle_e2c15b3c1473` | `videos/polymer_brittle_e2c15b3c1473.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 11 | `polymer_brittle_ea23f4e39317` | `videos/polymer_brittle_ea23f4e39317.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 12 | `polymer_brittle_f89aa7bc8961` | `videos/polymer_brittle_f89aa7bc8961.mp4` | `video_0032` | `test` | `direct_test` | 禁用于训练与开发调参（隔离） |
| 13 | `metal_round_ductile_baseline_v1` | `videos/metal_round_ductile_baseline_v1.mp4` | `video_0006` | `fold_0_val`（近重复 `test` 的 `video_0010`） | `transitive_via_near_dup` | 禁用于训练与开发调参（本次新增隔离） |
| 14 | `metal_round_ductile_stage1_a2_v1` | `videos/metal_round_ductile_stage1_a2_v1.mp4` | `video_0006` | `fold_0_val`（近重复 `test` 的 `video_0010`） | `transitive_via_near_dup` | 禁用于训练与开发调参（本次新增隔离） |
| 15 | `metal_round_ductile_coupled_a2_time12_v1` | `videos/metal_round_ductile_coupled_a2_time12_v1.mp4` | `video_0006` | `fold_0_val`（近重复 `test` 的 `video_0010`） | `transitive_via_near_dup` | 禁用于训练与开发调参（本次新增隔离） |

### 1.2 其余 50 条仅关联开发源的虚拟视频汇总（按当前三折划分）

下表按 2026-11-19 重生成后的当前三折划分（`data/splits/three-fold/`）列出全部 50 条未与 `test` 关联的虚拟视频归组；这 8 个参考源均不属于第 2.2 节的 32 条 `1280×720` 复材固定机位簇：

| `referenced_source_id` | 当前真实源所在折 | 虚拟视频数 | `leakage_type` | 使用约束（三折防泄漏） |
| --- | --- | ---: | --- | --- |
| `video_0014` | `fold_0_val` | 13 | `clean_dev_only` | 不得进入 `fold_0` 训练（仅可在 `fold_1/2` 侧或开发诊断使用） |
| `video_0020` | `fold_0_val` | 10 | `clean_dev_only` | 同上，不得进入 `fold_0` 训练 |
| `video_0003` | `fold_1_val` | 11 | `clean_dev_only` | 不得进入 `fold_1` 训练 |
| `video_0050` | `fold_1_val` | 4 | `clean_dev_only` | 不得进入 `fold_1` 训练 |
| `video_0040` | `fold_2_val` | 1 | `clean_dev_only` | 不得进入 `fold_2` 训练 |
| `video_0058` | `fold_2_val` | 1 | `clean_dev_only` | 不得进入 `fold_2` 训练 |
| `video_0097` | `fold_2_val` | 3 | `clean_dev_only` | 不得进入 `fold_2` 训练 |
| `video_0100` | `fold_2_val` | 7 | `clean_dev_only` | 不得进入 `fold_2` 训练 |
| **小计** | — | **50** | `clean_dev_only` | `15 + 50 = 65`（全量核对闭环） |

### 1.3 新增虚拟视频与历史暴露核查

- **本仓 `data/virtual/` 校验**：运行 `.venv/bin/python -m script.checks.virtual_dataset --all`，仅检出 `data/virtual/video-V1/`（65 条，`28,732,471` bytes），`manifest` / `upstream` / `labels` / `videos` 四项全通过；其于 `2026-11-19T07:47:17+00:00` 从 `BlenderTensileVideo` 干净提交 `8a37a1a2bf39304dc7002ccf89028b491f577273`（`datasets/video-V1`）导入，65 条 MP4 SHA-256 与上游清单 0 失配。
- **上游 `BlenderTensileVideo` 是否有超过 65 条的新增视频**：上游 `datasets/` 目录仍只有 `video-V1`（尚无 `video-V2`）。上游 `review/` 与 `_work/` 存在未收录、未导入本仓的待审候选（本地实存 `review/visual-space-20261121/` 12 条独立外观候选 + 1 条总览，其 JSON 均标明 `source_id=None` / `source_video_inputs: []`，属独立合成设定；另有提交 `8a37a1a` 的 `20261114` 批次与 `_work/coverage-20261120/`）。上述候选均未获正式收录，也不在本仓 `data/virtual/` 内。
- **本仓历史暴露检查**：检索本仓 `config/` 与 `script/`，未发现 `video-V1` 或 `data/virtual/` 被接入任何模型训练、调参或评测脚本（仅存在只读校验 `script/checks/virtual_dataset.py` 与输出路径守卫 `script/subvideo_generation/virtual.py`）。因缺少训练机完整历史日志，仍不能仅凭本仓静态检索排除仓外历史暴露。

---

## 2. 真实源视频去重审计（110 条，5,995 对）

上述第 1 节之所以将 `video_0006` 组 3 条虚拟视频升级为间接测试泄漏，源于本次对全部 110 条真实源视频（`test` 21、`fold_0_val` 30、`fold_1_val` 30、`fold_2_val` 29）执行的去重审计：

- **精确去重通过**：110 条源视频的 SHA-256 与文件字节数全部唯一（0 重复），与 [ROI 清单](../../data/roi/manifest.json) `source.sha256` 100% 一致（0 失配），抽帧 seek 0 失败。

### 2.1 确认为同一物理实验的 2 对跨 `dev ↔ test` 近重复（高危泄漏）

| 源视频 A（划分） | 源视频 B（划分） | 划分关系 | 材料 / 模式 / 位置 | 分辨率与时长（A / B） | 断裂时刻（A / B） | ROI 相似度（`score / d / p / s`） | 核验结论与泄漏影响 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `video_0006` (`fold_0_val`) | `video_0010` (`test`) | **`dev ↔ test`**（`fold_1/2_train` 含 A） | 金属 / 韧性 / 标距内 | `1120×880`, `23.30 s` / `792×722`, `27.07 s` | `21.63 s` / `24.37 s` | `0.8389` (`0.819 / 0.847 / 0.851`) | **确认同一实验**：断裂对齐 ROI NCC 在 `t_f + 0.3 s` 达 `0.6566`，目视确认背景斜线、墙缝、颈缩与断口形貌、断帧拖影一致；B 为更紧裁剪与稍长起止截取。**双重影响**：既导致真实 `dev ↔ test` 泄漏，又使 `video-V1` 中参考 `video_0006` 的 3 条虚拟视频间接关联 `test`。 |
| `video_0032` (`test`) | `video_0079` (`fold_1_val`) | **`dev ↔ test`**（`fold_0/2_train` 含 B） | 高分子 / 半脆半韧 / 标距内 | `402×726`, `4.53 s` / `440×708`, `3.04 s` | `3.40 s` / `1.91 s` | `0.7859` (`0.805 / 0.762 / 0.790`) | **确认同一实验**：断裂对齐 `t_f + {-0.5, 0.0, +0.3} s` 的 RAW NCC 为 `0.764–0.769`（ROI NCC `0.601–0.609`），精确 `~1.49 s` 片头截断（断后余长同为 `1.13 s` vs `1.12 s`）、裂纹位置与夹具手柄角度完全一致；A 前段多 4 个白色叠加箭头。**影响**：`video_0079` 在 `dev` 侧直接泄漏 `test` 源 `video_0032`（`video_0032` 另已有 11 条虚拟视频隔离）。 |

- **排位显著性**：排除 `1280×720` 复材批次内部配对（两端均在 32 条内）后，上述 2 对位列全量及同材料 ROI 相似度 **第 1 与第 2 位**（`0.8389` / `0.7859`），显著高于第 3 位 `video_0040 ↔ video_0095`（`0.7308`，分辨率与时长悬殊，非重复）；若进一步排除任一端属于该 32 条批次的配对，最高同材料 ROI 分为 `0.6899`（`video_0057 ↔ video_0061`）。
- **处置方案（须经用户拍板，本报告不自动改写划分）**：
  - **方案 A（推荐，最小扰动）**：保持现有固定 21 条 `test.json` 不变，在所有训练与开发调参阶段**强制排除 `video_0006` 与 `video_0079`**（及其派生子视频），有效开发源由 89 降至 87，同时按第 1.1 节隔离 15 条虚拟视频。
  - **方案 B（合并来源组重划）**：若需合并这两对为同一来源组，**不能**在保留现行 `test.json` 的前提下仅重跑三折（`script/data_split/generate.py` 会拒绝跨 `test` 与 `dev` 的来源组），必须经用户确认后重新划分测试集与开发集。

### 2.2 32 条 `1280×720` 复材视频说明（同实验台背景，非重复）

- 元数据聚类显示 32 条复材源视频来自 2 组固定机位拍摄批次：`1280×720 @ 30 fps`（23 条，含 5 条 `test`：`video_0037, 0063, 0087, 0094, 0095`）与 `1280×720 @ 25 fps`（9 条，`video_0102`–`video_0110`，全在 `dev`）。另有 `544×960 @ 30 fps` 金属 2 条（`video_0018` [`test`] 与 `video_0028` [`fold_1_val`]），目视确认机位与试样均不同。
- 抽样目视核查 7 对高分 `1280×720` 代表性配对（含 `video_0104↔0105`、`0009↔0027`、`0034↔0052`、`0044↔0063`、`0064↔0087`、`0037↔0044`、`0037↔0076` 及唯一 0.1 s 同长对 `0103↔0110`）均确认为**同实验台/同机位下的不同物理试样**（非重复视频；未逐对目视的其余簇内配对不以分辨率/帧率单独排除近重复）。这 32 条均未被 `video-V1` 虚拟视频参考，仅需在模型评测时注意同机位背景耦合即可，不构成源重复泄漏。

---

## 3. 审计方法、输入指纹与失效条件

### 3.1 四层只读审计口径

1. **字节与清单一致性**：逐条计算 `data/videos/video_0001.mp4`–`video_0110.mp4` 的 SHA-256 与字节数，与 `data/roi/manifest.json` 交叉比对。
2. **元数据聚类**：用 `ffprobe` 提取编解码、分辨率、帧率与时长，分别按 `(width, height, fps_round2, codec)` 及附加 `dur_round0.1s` 聚类。
3. **双通道感知相似度（全量 5,995 对）**：
   - 全画幅通道（`data/videos/`）：每片等距抽 9 帧（`5%`–`95%`），计算 64-bit `dHash`、`pHash`、8×8×8 HSV 颜色直方图与 16×16 空间余弦，按时间偏移不变的对称最优帧匹配打分（`composite >= 0.90` 的 63 对全部落在 32 条 `1280×720` 复材批次内）。
   - ROI 通道（`data/roi/videos/`）：每片等距抽 5 帧（`10%`–`90%`），计算 `roi_score = (d_best + p_best + max(0, s_best)) / 3`，并排除 `1280×720` 复材批次内部配对后检索全量与同材料 Top 12。
4. **目视与断裂时刻对齐核验**：对 11 对高分/跨划分候选生成多时刻对比图目视复核，并对 2 对高危跨划分候选按断裂时刻 `t_f + {-0.5, 0.0, +0.3} s` 对齐计算 RAW/ROI NCC。**核验边界**：本报告的“确认 2 对”基于双通道高分阈值与上述复核截点得出，不声称已对全部 5,995 对逐一完成人工全帧排错。

### 3.2 输入文件指纹

| 文件 | SHA-256 |
| --- | --- |
| `data/annotation-table-full.csv` | `c928bea3d769eb16ad55ed7d872a877a3b4fd327d0af5422bc2bb682c1ec354c` |
| `data/splits/three-fold/test.json` | `26fc3070662b8ac2c8683a50bd8dea9c78a96162ad5e4c0e83a6afc454c7d8dc` |
| `data/splits/three-fold/manifest.json` | `1ad84afb9a9eb122d6d7cdc13b78a975567a51667eaeacfabd5748c1055f6ae2` |
| `data/roi/manifest.json` | `24b2dfa3019462dbef27fc00314901d30ad308802a458b31d95a90e4dc6948b3` |
| `data/virtual/video-V1/manifest.json` | `4c1da6b5d7bdecfaaf6c8541ea4c3b5c21fade13f0d689aee27c6c1fb5208d20` |
| `data/virtual/video-V1/labels.csv` | `a236073d548fb8d1ce7a73c6118b0cf7eb64887a17e10bcd89bedb4a93c43a5d` |
| `BlenderTensileVideo/datasets/video-V1/manifest.json` | `662693ddb70cf9bb94c79d57087cd33cffca97072fc45a4896aa964ae3b56444` |

### 3.3 失效条件

以下任一条件变化时，本报告对应结论失效，须重新审计：
1. `data/videos/`、`data/roi/videos/`、`data/roi/manifest.json`、`data/splits/three-fold/` 或 `data/annotation-table-full.csv` 发生新增、替换或成员变更；
2. `data/virtual/` 导入新版本虚拟数据包（如 `video-V2`）或上游 `BlenderTensileVideo` 候选批次经用户确认并正式交付；
3. 后续训练或评测日志披露了 `video-V1` 或上述真实源视频的仓外历史暴露记录；
4. 若用户确认按本报告更新 15 条隔离口径，后续需同步在 `docs/design-test.md` 与 [虚拟视频溯源报告](virtual-video-provenance.md) 标注旧“12 条”口径已被本报告更新。
