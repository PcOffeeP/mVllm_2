# 项目任务跟踪表

> 周期：两周冲刺  
> 主目标：完成新增视频数据处理与 MiniCPM-V-4.5 重训闭环，同时确认其他候选模型的微调框架和最小可行配置。  
> 更新规则：只更新状态、负责人、日期、备注；新增任务时保持表格结构。

---

## 0. 执行假设

- 数据准备以 `vllm_-json/` 为唯一源头，输出规范化数据与 LLaMA-Factory 可训练 JSON。
- MiniCPM-V-4.5 重训继续在 `finetune-cpm/` 中完成，优先复用现有 LLaMA-Factory 流程。
- 其他模型默认先尝试 LLaMA-Factory；只有 smoke test 失败时再考虑 Transformers + PEFT。
- 两周内优先完成 MiniCPM 新数据重训闭环；其他模型以框架确认、配置草案、dry-run/smoke test 为主要交付。
- 数据 split、标签空间、评测集必须共用，避免不同模型之间不可比。

## 1. 状态说明

| 状态 | 含义 |
|------|------|
| `TODO` | 尚未开始 |
| `DOING` | 正在处理 |
| `BLOCKED` | 被外部信息或前置条件阻塞 |
| `REVIEW` | 已完成初稿，等待核对 |
| `DONE` | 已完成并通过验收 |

---

## 2. 两周里程碑

| 时间 | 目标 | 验收标准 | 状态 | 备注 |
|------|------|----------|------|------|
| 第 1-2 天 | 数据资产盘点完成 | 新增视频、标注表、旧数据、split、merged datasets 全部列清；缺失视频和异常标注有清单 | TODO | 先确认新增视频实际路径 |
| 第 3-5 天 | 数据处理链路修复并冻结 v1 数据集 | 产出可训练 JSON、manifest、校验报告；路径、标签、时间格式、fold 泄漏检查通过 | TODO | MiniCPM 重训前置条件 |
| 第 6-8 天 | MiniCPM-V-4.5 重训启动并完成 | 训练配置开启 eval；保存训练日志、checkpoint、loss 曲线 | TODO | 若训练资源排队，先完成 dry-run |
| 第 9-10 天 | MiniCPM 新模型评测完成 | 产出 time/type/joint 三类指标，并与旧 baseline 对比 | TODO | 使用统一评测脚本 |
| 第 1-10 天并行 | 其他模型框架确认 | 每个候选模型有框架结论、模板、配置草案、风险点 | TODO | 不阻塞 MiniCPM |
| 第 11-14 天 | 冲刺复盘与下一轮计划 | 明确是否继续 MiniCPM 调参、哪些模型进入正式微调、下一轮数据缺口 | TODO | 输出决策表 |

---

## 3. 主线 A：数据处理与冻结

| ID | 任务 | 优先级 | 依赖 | 产物 | 验收标准 | 状态 | 负责人 | 备注 |
|----|------|--------|------|------|----------|------|--------|------|
| DATA-01 | 盘点新增视频与标注来源 | P0 | 无 | 新增数据清单 | 每个视频有唯一 `video_id`、源路径、标注状态 | TODO |  | 先确认视频是否仍在 `/hy-tmp/videos` 或本地路径 |
| DATA-02 | 修复 merged dataset 命名 | P0 | 无 | `*.json` 合并产物 | `3k0/3k1/3k2` 补 `.json`；`kfold_5_flod_0` 更正为 `kfold_5_fold_0.json` | TODO |  | 当前问题位于 `vllm_-json/JSON_workflow/data/merged_datasets/` |
| DATA-03 | 补齐 5-fold merged datasets | P0 | DATA-02 | `kfold_5_fold_0~4.json` | 5 个 fold 合并产物全部存在且可解析 | TODO |  | split 文件已有，merged 产物需补齐 |
| DATA-04 | 统一标签闭集 | P0 | DATA-01 | 标签映射表 | 训练数据中不再混用英文标签、同义词、错拼标签 | TODO |  | 建议统一中文闭集 |
| DATA-05 | 统一时间字段格式 | P0 | DATA-01 | 清洗后标注数据 | 正常断裂样本统一为 `<float>s`；异常/未断裂样本时间规则明确 | TODO |  | 需处理 `null` 策略 |
| DATA-06 | 统一视频路径与分隔符 | P0 | DATA-01 | 更新后的 JSON | 所有视频路径使用 `/`；训练环境中路径可访问 | TODO |  | 不同机器路径用 manifest 映射 |
| DATA-07 | 检查 split 泄漏与类别分布 | P0 | DATA-03, DATA-04 | split 校验报告 | 同一视频不跨 train/val 泄漏；各 fold 类别分布可解释 | TODO |  | 特别检查 `batch_000` |
| DATA-08 | 生成规范化 manifest | P0 | DATA-04, DATA-05, DATA-06, DATA-07 | `dataset_manifest` | 包含 `video_id`、`video_path`、`fracture_time_sec`、`fracture_type`、`split_id`、`source_batch` | TODO |  | 作为后续所有 exporter 的源头 |
| DATA-09 | 导出 LLaMA-Factory ShareGPT video JSON | P0 | DATA-08 | 训练/验证 JSON | `messages + videos` 格式可被 LLaMA-Factory 读取 | TODO |  | 先服务 MiniCPM |
| DATA-10 | 同步数据到 `finetune-cpm` | P0 | DATA-09 | `AAA-TS-Video/data/JSON/*.json`、`dataset_info.json` 更新 | MiniCPM 配置能引用新数据键名 | TODO |  | 保留旧 baseline 数据 |
| DATA-11 | 输出数据冻结报告 | P1 | DATA-10 | 数据报告 | 样本数、类别分布、fold 分布、缺失项、清洗规则完整记录 | TODO |  | 后续模型对比依据 |

---

## 4. 主线 B：MiniCPM-V-4.5 重训闭环

| ID | 任务 | 优先级 | 依赖 | 产物 | 验收标准 | 状态 | 负责人 | 备注 |
|----|------|--------|------|------|----------|------|--------|------|
| MCPM-01 | 复核现有训练配置 | P0 | DATA-10 | 配置差异说明 | 明确 `video_maxlen`、LoRA 参数、epoch、eval、输出目录 | TODO |  | 当前 v2 配置已开启 eval，可作为基础 |
| MCPM-02 | 设计 MiniCPM v2 训练数据键 | P0 | DATA-10 | `dataset_info.json` 数据项 | train/eval 数据项命名清晰，不覆盖旧结果 | TODO |  | 例如 `tensile_video_v2_train/eval` |
| MCPM-03 | MiniCPM 数据加载 dry-run | P0 | MCPM-01, MCPM-02 | dry-run 日志 | 小样本能完成预处理、视频读取、一次训练/推理 | TODO |  | 先暴露路径和 processor 问题 |
| MCPM-04 | 启动全量重训 | P0 | MCPM-03 | checkpoint、训练日志 | 训练完成；开启 eval；checkpoint 可复用 | TODO |  | 不再只看 train loss |
| MCPM-05 | 跑 time/type/joint 推理 | P0 | MCPM-04 | `results_v2/*/*.jsonl` | 三类任务在同一验证集上都有原始输出 | TODO |  | 保留旧 `results/` |
| MCPM-06 | 跑统一评测 | P0 | MCPM-05 | metrics、错误样本、混淆矩阵 | time/type/joint 指标完整，失败原因可追踪 | TODO |  | 复用现有 validation 脚本 |
| MCPM-07 | 新旧 MiniCPM 对比复盘 | P1 | MCPM-06 | 对比报告 | 明确新增数据和配置变更是否带来提升 | TODO |  | 决定是否继续调参 |
| MCPM-08 | 记录可复现 runbook | P1 | MCPM-07 | runbook 更新 | 从数据到训练到评测的命令可复跑 | TODO |  | 包含路径、模型目录、输出目录 |

---

## 5. 并行线 C：其他候选模型准备

| ID | 任务 | 优先级 | 依赖 | 产物 | 验收标准 | 状态 | 负责人 | 备注 |
|----|------|--------|------|------|----------|------|--------|------|
| MODEL-01 | 确认候选模型清单 | P0 | 无 | 模型矩阵 | 模型名、HF/ModelScope 路径、参数量、上下文/视频能力列清 | TODO |  | 与 ROADMAP 保持一致 |
| MODEL-02 | 确认 LLaMA-Factory 支持情况 | P0 | MODEL-01 | 支持矩阵 | 每个模型对应 template、model id、是否 multimodal | TODO |  | 本地已注册多数候选模型 |
| MODEL-03 | 准备 InternVL3.5-8B 配置草案 | P1 | MODEL-02, DATA-09 | YAML 草案 | 能定位模型、数据、template、输出目录 | TODO |  | template 预计 `intern_vl` |
| MODEL-04 | 准备 GLM-4.1V-9B-Thinking 配置草案 | P1 | MODEL-02, DATA-09 | YAML 草案 | 能定位模型、数据、template、输出目录 | TODO |  | 注意 thinking 输出对 JSON 的影响 |
| MODEL-05 | 准备 MiMo-VL-7B-RL-2508 配置草案 | P1 | MODEL-02, DATA-09 | YAML 草案 | 能定位模型、数据、template、输出目录 | TODO |  | 需优先验证 processor |
| MODEL-06 | 准备 Qwen3-VL-8B-Instruct 配置草案 | P1 | MODEL-02, DATA-09 | YAML 草案 | 能定位模型、数据、template、输出目录 | TODO |  | 优先尝试 `qwen3_vl_nothink` |
| MODEL-07 | 每个模型做数据加载 smoke test | P1 | MODEL-03, MODEL-04, MODEL-05, MODEL-06 | smoke test 日志 | `max_samples` 小样本能通过预处理和最小训练步骤 | TODO |  | 不要求两周内全量训练 |
| MODEL-08 | 形成框架决策表 | P0 | MODEL-07 | 决策表 | 每个模型明确：LLaMA-Factory 可行 / 需 fallback / 暂缓 | TODO |  | 两周内核心交付之一 |
| MODEL-09 | 选择下一轮正式训练模型 | P1 | MODEL-08, MCPM-07 | 下一轮候选排序 | 按可行性、资源、预期收益排序 | TODO |  | 不在本轮强行训练全部模型 |
| MODEL-10 | V-JEPA2 旁路特征基线评估 | P2 | MODEL-08, MCPM-07 | feasibility note / prototype plan | 明确是否冻结 V-JEPA2 encoder 提取视频特征，并训练轻量 `type` 分类头和 `time` 时序定位头 | TODO |  | 不作为主基座；仅用于诊断视频时序表征瓶颈 |

---

## 6. 横向共用标准

| 项目 | 当前决策 | 后续可调整点 |
|------|----------|--------------|
| 数据源头 | `vllm_-json/` 产出规范化 manifest | 如数据量扩大，可拆出独立 `datasets/` 目录 |
| 训练格式 | 优先导出 LLaMA-Factory ShareGPT video JSON | 若某模型不兼容，再增加专用 exporter |
| V-JEPA2 定位 | 不作为主基座；只作为旁路视频特征 baseline | 若主 VLM 仍无法定位断裂时刻，再做冻结 encoder + 轻量 head 实验 |
| 标签空间 | 中文闭集标签 | 英文输出只作为推理展示，不进入训练标签 |
| 时间格式 | `<float>s` 或规则化 `null` | 后续可增加帧级字段 |
| 评测集 | 所有模型共用同一 split | 后续可增加冲击测试独立 split |
| 评测指标 | time/type/joint 三类指标 | 部署阶段再加入吞吐、延迟、显存、token 成本 |

---

## 7. 当前风险与处理策略

| 风险 | 影响 | 策略 | 状态 |
|------|------|------|------|
| 新增视频路径不统一或不可访问 | 阻塞训练 | 先做 manifest 和路径校验，不直接进入训练 | TODO |
| 标签中英文混杂 | 类型分类继续塌缩 | 训练标签统一中文闭集 | TODO |
| 旧数据 split 与新增数据混合后泄漏 | 评测结果不可信 | 重建或校验 split，保留报告 | TODO |
| MiniCPM 重训仍无明显提升 | 消耗 GPU 但收益小 | 用 eval 和统一评测快速判断，及时转向数据/模型问题 | TODO |
| 其他模型 LLaMA-Factory 支持不完整 | 并行准备受阻 | 先做 smoke test，失败模型再评估 Transformers + PEFT | TODO |

---

## 8. 下次推进顺序

1. 确认新增视频和标注文件的实际位置。
2. 从 `DATA-01` 到 `DATA-08` 完成数据冻结。
3. 执行 `DATA-09`、`DATA-10`，让 MiniCPM 能读取新数据。
4. 并行完成 `MODEL-01`、`MODEL-02`，准备其他模型配置草案。
5. MiniCPM dry-run 通过后启动全量重训。
