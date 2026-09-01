# 模型归档证据包索引

本目录是**已归档模型证据包**的统一存放根，是未来 Agent 查找模型测试结果的引导入口：
先看本索引，再进具体 `<model_id>/` 目录，需要原始逐样本记录或完整日志时再到训练机
`workspace/evidence_archive/`（见「如何使用」）。归档归属与清理状态以
[MODEL_INVENTORY.md](../../MODEL_INVENTORY.md) 为准，本索引不自行判定清理是否放行。

## 这个目录是干什么的

每个被清除或评估过质量的过程模型，其「怎么训练、评测了谁、结果如何、哪里失败」的
自包含证据包按 `<model_id>/` 存放于此。证据包的定位：

- **只保留小而关键的归档文件**（身份、配置、效果摘要、哈希），大权重与逐样本记录
  按政策留在训练机、不入 git；
- 每个模型目录自含 `README.md` 作人类/Agent 可读的结论与失败特征说明，
  `MANIFEST.json` 作结构化哈希与身份清单；
- 这里是模型测试结果的**引导索引**，替代挨个翻 `docs/results/` 的检索方式。

> 本目录是归档根，不等于目录内模型已被授权删除；删除仍须满足
> [MODEL_INVENTORY.md](../../MODEL_INVENTORY.md) 第 8 节的归档验收与显式授权。

## 证据包标准结构

每个 `<model_id>/` 子目录应含以下文件（本目录仅同步小文件，logs/ 与 loss png 等
保留在训练机完整归档中）。字段模板对应 MODEL_INVENTORY.md 第 8.2 节的 6 类信息：
模型身份、完整训练配置、数据与 Prompt、训练过程、效果证据、归档验收。

| 文件 | 作用 | 对应 8.2 信息类 |
| --- | --- | --- |
| `README.md` | 人类/Agent 可读：模型身份、训练配置、评测对象、效果指标、失败特征、缺口说明 | —（汇总） |
| `MANIFEST.json` | 结构化：schema、run_id、fold、训练数据/采样/Prompt/超参、大文件 sha256 与大小、证据包逐文件 sha256 | 模型身份 / 归档验收 |
| `identity/run_identity.json` | 该次运行的唯一身份标识（run / fold / seed / 基座与代码版本） | 模型身份 |
| `input/experiment_contract.json` | 冻结的实验契约与训练输入哈希 | 数据与 Prompt |
| `input/summary.json` | 该次实验的输入摘要（数据/采样/Prompt 选择记录） | 数据与 Prompt |
| `input/dataset_info.json` | 评测/训练所用数据集信息 | 数据与 Prompt |
| `adapter/trainer_state.json` | 训练过程状态（含 log_history）、best/停止 step | 训练过程 |
| `evaluation/evaluation_summary.json` | 严格评测摘要：合法率、四字段正确率、joint 等 | 效果证据 |
| `evaluation/evidence_manifest.json` | 评测证据清单（对应产物与哈希） | 效果证据 |

不在本目录、留在训练机的项（`evidence_archive/<model_id>/`）：`logs/`（train/merge/
evaluation 日志）、`adapter/*.png`（训练 loss 图）、`evaluation/evaluation_records.jsonl`
（逐样本原始记录）、大权重适配器与 merged 分片。这些仅在本目录 MANIFEST 中登记 sha256
与字节数，不复制权重本体。

## 模型清单索引

当前仅一个试点归档模型。新归档模型按同一结构追加一行，并同步到
[MODEL_INVENTORY.md](../../MODEL_INVENTORY.md) 对应条目。

| model_id | 一句话结论 | 证据包 | MODEL_INVENTORY 定位 |
| --- | --- | --- | --- |
| `v4.1-prompt-minimal-v1-seed3411` | prompt-minimal（seed 3411, fold0）：精简 prompt 致 valid 100%→86.12%、joint 41.18%→24.00%，四字段正确率同步下滑 | [证据包](v4.1-prompt-minimal-v1-seed3411/README.md) | [第 3 节清单 条目 4](../../MODEL_INVENTORY.md#3-模型清单)；归档边界见[第 8 节](../../MODEL_INVENTORY.md#8-2026-08-31-清理可行性核查) |

## 如何使用

对想查找模型测试结果的未来 Agent：

1. **先看本索引**：按 `model_id` 定位目标，读「一句话结论」判断是否相关；
2. **进具体模型目录**：读该 `model_id/README.md` 获取配置、指标与失败特征，核对
   `MANIFEST.json` 的哈希与身份；
3. **需要原始数据再上训练机**：逐样本记录（`evaluation_records.jsonl`）、完整训练
   日志、loss png 与权重本体在训练机 `workspace/evidence_archive/<model_id>/` ，
   不入 git；本目录不包含这些大文件。

跨模型横向对比、模型清单与清理放行前置条件见 [MODEL_INVENTORY.md](../../MODEL_INVENTORY.md)；
归档/清理任务的进展跟踪见 [project-todo.md](../../project-todo.md) 的 MODEL-ARCHIVE 条目。

## 维护约定

- 每新增一个归档模型：在 `docs/results/model_evidence/` 下新建 `<model_id>/` 目录，
  按上表结构落盘小文件与 `README.md`、`MANIFEST.json`，并在本索引「模型清单索引」
  追加一行（结论一句话、附证据包链接与 MODEL_INVENTORY 定位）。
- 只索引真实存在、已落位的证据包，不预填尚未归档的模型。
- 本索引只做归档定位，不修改代码、契约、指针，不删除任何文件。
