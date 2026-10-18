# 评测结果目录

本目录按结果用途整理。目录位置本身表达结果的生命周期，不再依赖冗长文件名猜测。

```text
results/
├── README.md
└── experiments/
    ├── diagnostics/                      诊断推理输出
    └── prompt_sweep/                     Prompt 扫描输出
```

## 根目录

根目录只保留仍被正式证据链或当前 V4.1 对比实验直接引用的版本化运行。
历史视觉三折结果目录已随 2026-10-18 清理移除，prompt-concise 三折的 Git 摘要记录
同样移除，现存版本化运行目录见本节上方目录树。最新 prompt-concise 三折结果位于对应
`workspace/runs/` 的 evaluation 目录。
上一轮语言基线及 fold0 消融的 V4.1 证据目录已随 2026-10-18 清理移除；其指标结论见
`docs/results/model-inventory.md`，删除前逐文件指纹与 SHA-256 见 `pi-workspace/mVllm_2-audit/deleted-artifacts-manifest-20261018.tsv`。

## 已清理的历史结果集

2026-07 legacy 结果集（V2 正式流水线以前的 base/finetune 冒烟结果）与 v2.0.0（20260719）
冻结发布结果集（三折、全量训练与测试）已于 2026-10-18 清理移除，`archive/` 目录不再存在。
这些结果原本只用于追溯，不作为当前模型质量结论；删除前逐文件指纹与 SHA-256 见 `pi-workspace/mVllm_2-audit/deleted-artifacts-manifest-20261018.tsv`。

## experiments

`diagnostics` 与 `prompt_sweep` 是可再生成的实验输出，不进入 Git。
这些结果可以帮助定位问题，但不能替代冻结的正式验证结果。

## 安全规则

- 不在这里存放模型权重；实验权重统一位于 `workspace/runs/`，发布权重位于
  `workspace/models/releases/`。
- 不覆盖已有版本化运行；新运行使用新的 run ID。
- 发布或迁移正式结果前先生成完整 SHA-256 证据索引。
- 历史 JSON 中记录的绝对路径是运行时快照，迁移目录不会改写这类原始证据。
