# V4.1 intermediate pre-acceptance service

Stage B intermediate model `stage-b-intermediate-8e1fdb09f8e6` 已在训练机独立端口
`127.0.0.1:8002` 以 BF16 merged 模型启动。服务仅在显式
`--contract-version tensile-vlm/v4.1` 时选择 V4.1；默认 V2 行为保持不变。

真实 MP4 smoke 已验证：

- contract 与完整 deployment identity 一致；
- 模型输出满足 V4.1 严格四字段；
- request ID、实际帧表、tensor digest 和 tensor shape 完整；
- credential 只存在训练机权限 `0600` 的运行环境文件中。

随后执行了受控 V2 回滚演练：优雅停止 V4.1、加载旧 V2 merged model、通过同媒体
V2 smoke、优雅停止 V2，再恢复完全相同的 V4.1 deployment identity。两套模型未同时
驻留 GPU，未使用强制终止。

该服务是 `intermediate_development_model` 的 pre-acceptance 入口，不占用生产别名，
不授权独立验收或完整生产通过。
