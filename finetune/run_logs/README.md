# 训练日志目录

这里存放历史训练入口、推理服务和迁移管理产生的日志、PID 与状态 JSON。新实验的
实验内日志优先放在 `workspace/runs/<experiment-id>/logs/`；跨实验服务、迁移和资产管理
日志仍放在本目录。除本说明外，内容只保存在训练机，不提交 Git。

```text
run_logs/
├── README.md
├── v4_1_0_760050fad303_20260724_visual/  当前正式视觉运行日志
├── archive/
│   ├── v2/                               V2 历史流水线日志
│   └── v4_1_language/                    20260723 语言层基线日志
├── experiments/                          消融、诊断和 4-bit 实验日志
├── services/                             审查界面与推理服务日志
├── v4_1_agent_pipeline_fold0_r1/          当前 V4.1 中间服务日志与凭据文件
├── checkpoint_management_20260729/        Checkpoint 计划与执行报告
└── scratch/                              冒烟、失败和可丢弃的临时日志
```

正式运行目录在证据冻结完成后保持原名。移动历史日志不会改变模型或评测结果；
日志内记录的旧绝对路径作为历史现场保留，不做批量重写。

`service.env` 等凭据文件必须保持 `0600`，不得复制到 Git 或文档。checkpoint
`checkpoint_plan.json` 与 `cleanup_report.json` 是训练机运行证据；Git 只保存不含大型
路径列表的摘要和报告 SHA-256。
