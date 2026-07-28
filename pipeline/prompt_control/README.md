# V4.1 Prompt Control

`active_prompt.yaml` 是 V4.1 固定全字段任务的唯一人工 Prompt 编辑入口。它不保存训练
超参数、数据标签、模型路径、seed 或评测阈值。

校验草稿：

```bash
python -m pipeline.prompt_control validate \
  --source pipeline/prompt_control/active_prompt.yaml
```

发布不可变 revision：

```bash
python -m pipeline.prompt_control publish \
  --source pipeline/prompt_control/active_prompt.yaml
```

发布后生成 `pipeline/prompt_registry/<revision_id>/prompt.yaml` 和 `manifest.json`。相同
revision 与相同内容是幂等操作；相同 revision 的内容发生变化时拒绝覆盖。

新实验只能从已发布 revision 生成自包含 experiment contract。历史
`pipeline/prompt_library.yaml` 和历史 V4.1 contract/overlay 继续服务旧链路，不能作为新
固定 Prompt 实验的正文来源。
