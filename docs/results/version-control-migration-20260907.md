# 2026-09-07 可读版本控制迁移只读调查

本记录保存 Spec 起草期间的观察，不定义迁移行为契约或任务状态。关联任务：`2026-09-07-readable-version-control-migration`。训练机只读命令通过 SSH 执行，目录检查采用有限深度 find/ls，文件大小及软链接检查不读取权重内容；Git 状态、活动指针和少量身份元数据被读取。未读取受限测试真值和逐样本语义结果，未执行训练、推理、权重哈希或远端写入。初次连接超时，用户恢复 Tailscale 后调查成功。

## 真实基线与证据边界

核心基础设施承接提交为 `1b0d5823`。B0–B12 的本机测试和独立审查是前序证据，不表示训练机验收或正式迁移已完成。

2026-09-07 刷新两个远端后：

- 本地 main：`cc59312c`。
- Codeup main：`f1b7d8a3`，为本地 main 的祖先，落后 6 个提交。
- GitHub main：`702f5e2d`，为本地 main 的祖先，落后 410 个提交。

当前引用关系属于进度落后，不是分叉冲突。**Codeup 的发布地位来自用户确认**，不意味着可丢弃本地 main 独有提交；最终合并材料须覆盖这些提交和本任务提交的完整范围。

### 训练机调查状态与本地线索

**远端现状：**

- Git 为干净的 `main@f1b7d8a361b9ae5e2c7ad4ca09924f9f7af95e52`，origin 指向 Codeup，与本机已刷新 Codeup main 相同。新体系的本机提交尚未同步到该工作区。
- `workspace/data/releases` 有 `v4.1.0-760050fad303` 和 `v4.1.0-ecb5aeb9657c`，两者均发现 release manifest；训练机活动指针选择后者，与本机一致。尚未验证 payload 全量完整性。
- `pipeline/prompt_registry` 有 `v4.1-fixed-full-fields-initial-v1`、`v4.1-concise-evidence-json-v1`、`v4.1-concise-evidence-json-v2` 三个版本目录及 manifest；仍需逐训练核对实际冻结 Prompt，不能由 active Prompt 推断历史输入。
- `workspace/models/current` 指向 `releases/v4.1-agent-pipeline-fold0-r1`。该发布目录有 adapter 和 10 个 merged safetensors 分片；这证明文件存在，不证明模型加载或质量通过，也不证明服务进程正在运行。
- `/data` 挂载可见、约 3.4 TiB 可用，但 **`/data/mVllm_2`** **不存在**。设计中的该路径下 DVC remote 与 MLflow 布局尚未落地；未调查其他位置是否有旧存储。

**run 目录不能等同于完成训练。** 实际发现八个 run 目录，按存在性证据分为：

| 训练目录                                    | 本次观察                                                                     | 迁移含义                            |
| --------------------------------------- | ------------------------------------------------------------------------ | ------------------------------- |
| phase2-source-aware，seed3407 / seed3411 | 两组 fold0 均有 adapter 和 10 个 merged 分片；各有 evidence\_archive 目录             | 历史模型候选，需要继续验证来源和归档完整性           |
| phase2-coverage-first，seed3411          | fold0 有 adapter 和 10 个 merged 分片，有归档目录                                   | 同上                              |
| phase2-coverage-fallback，seed3413       | fold0 有 adapter 和 10 个 merged 分片，有归档目录                                   | 同上                              |
| prompt-minimal，seed3411                 | run 根下有 adapter 和 10 个 merged 分片，有归档目录                                   | 同上；结构与 fold0 子目录模式不同            |
| phase2-coverage-first，seed3407          | fold0 有 adapter，保留 checkpoint-250/1000/1050/1100/1125；merged 是指向发布模型的软链接 | 发布模型来源链必须一起核对，不作为独立 merged 副本计数 |
| prompt-concise-v1 / v2，seed3411         | 发现 input 资料；v1 另有 prepared-config-untrained；本次未发现权重                      | 按准备资料调查，不能导入为 completed 训练或保留模型 |

以上 run 名均带 `v4.1-` 前缀及 `-v1-seed<N>` 后缀，concise-v2 使用 `-v2-seed3411`。`workspace/runs/v4.1-prompt-concise-cv-v1-seed3411` **预期路径不存在**；不能因此断言模型在整台训练机上不存在，仍需沿历史报告查定位线索。

**归档尚未证明完整。** 五个远端 `workspace/evidence_archive` 目录与本地五个证据目录对应。对这些归档目录检索深度 6 内名称含 record 的文件，没有匹配结果；未据此断言所有位置均无原始记录。抽查 source-aware seed3411 的 training\_run\_manifest，仍记录旧 LlamaFactory adapter 路径及外部 tensile-data 路径，说明历史冻结位置与当前物理位置必须分开核对。仅有归档目录或旧 manifest 哈希不足以认定恢复链完整。

以下只用于安排远端核对，不代表真实产物已验证：

| 本地来源                                                  | 当前可见内容                                             | 训练机仍需核对                       |
| ----------------------------------------------------- | -------------------------------------------------- | ----------------------------- |
| [活动数据指针](../../finetune/active_data_release.json) | `v4.1.0-ecb5aeb9657c` 及钉扎 manifest 摘要 | release、payload、审查来源与实际使用关系 |
| [模型指针](../../pipeline/model_registry/current.json) | `v4.1-agent-pipeline-fold0-r1` | 注册记录、权重、来源训练及实际服务选择 |
| [交付配置](../../delivery/model_component.json) | `production_approved: false`，Stage B/D/G 标记为 false | 既有质量证据的真实含义；false 不自动等同于已执行失败 |
| [归档索引](model_evidence/README.md)及同目录文件 | 索引称一个试点，实际存在五个模型证据目录 | 各目录对应的完整归档、原始记录与权重是否存在 |

五个本地证据目录为 `v4.1-prompt-minimal-v1-seed3411`、`v4.1-phase2-source-aware-v1-seed3407`、`v4.1-phase2-source-aware-v1-seed3411`、`v4.1-phase2-coverage-first-v1-seed3411`、`v4.1-phase2-coverage-fallback-v1-seed3413`。目录存在不证明归档完整，也不证明这些对象都需迁移。历史 concise-cv 权重缺失记录仍须在训练机核实，不能沿用旧快照作为当前结论。


## 补充：活动 Prompt 与 alias 门禁

- 本机及训练机 `pipeline/prompt_control/active_prompt.yaml` 均声明 `revision_id: v4.1-concise-evidence-json-v2`。历史 registry 中有三个版本不表示当前活动 Prompt 有三版。
- 训练机旧发布 manifest 为 `v4.1-agent-pipeline-fold0-r1`，来源 release 为 `v4.1.0-ecb5aeb9657c`、fold0、seed3407、1125 optimizer steps；`production_approved: false`，limitations 包含 `quality_gates_not_passed`。
- 本机 `versioning/registry.py` 的 alias 写入和读取门均对 candidate/production 调用 require_passed=True 的 eval 校验；`versioning/materialize.py` 的 development 模式没有豁免该门。此为当前实现事实，不授权修改门禁。
