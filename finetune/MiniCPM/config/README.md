# MiniCPM 训练配置目录

配置按当前用途分组，不再把正式配置、消融配置和历史配置平铺在同一层。

```text
config/
├── active/v4_1_visual/       历史完整 V4.1 视觉 LoRA 三折对比配置
├── experiments/v4_1/        fold0 视觉与自动子视频扩充消融配置
└── archive/
    ├── v4_1_language/        2026-07-23 V4.1 语言层 LoRA 基线
    └── v2/                   冻结 V2 三折与全量训练配置
```

## active/v4_1_visual

绑定不可变发布 `v4.1.0-760050fad303`，启用视觉塔 LoRA、完整 `resampler` 训练和
4-bit bnb 基座。它们是当前视觉基线的正式配置，但当前模型尚未通过生产效果验收。

## experiments/v4_1

只用于已经完成的 fold0 可归因实验：

- `fold0_visual`：只开放视觉适配；
- `fold0_augmented_language`：自动子视频扩充、语言层 LoRA；
- `fold0_augmented_visual`：自动子视频扩充、视觉 LoRA。

自动扩充数据没有完成人工审查，不得把这些配置当作生产训练入口。

## archive/v4_1_language

上一轮只覆盖语言层的 V4.1 三折基线。保留用于复现和对照，不作为下一轮默认配置。

## archive/v2

冻结 V2 的三折、全量训练和合并配置。只有在 V2 封存环境中复现时使用。

移动配置后，运行脚本和测试必须引用这里的实际分类路径；不要在根目录重新创建同名副本。
