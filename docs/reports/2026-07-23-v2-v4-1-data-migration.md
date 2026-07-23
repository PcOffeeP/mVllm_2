# V2 / V4.1 数据隔离迁移报告

迁移时间：2026-07-23  
主数据仓库：训练机 `/home/liuyang/文档/tensile-data`

## 状态

- V2：`tensile-data/v2`，已冻结为只读。
- V4.1：`tensile-data/v4_1`，当前唯一活跃数据链路。
- 仓库内原数据目录继续保留，未移动、未覆盖、未删除。
- 两版 workspace 只链接到各自版本根目录，不存在跨版本链接。

## 清单

| 契约 | 文件数 | 总字节数 | 发布 |
|---|---:|---:|---|
| `tensile-vlm/v2` | 19,917 | 16,649,624,156 | `v2.0.0-1dab1e5e` |
| `tensile-vlm/v4.1` | 14,798 | 7,295,938,566 | `v4.1.0-760050fad303` |

## 验证

- 所有源目录与目标目录均执行 rsync checksum dry-run，差异数为 0。
- V2 发布清单 SHA-256：
  `fdcb9880595d2b89fe1339b413eb9f5fa6b38f4d422370bf3daea63c4fbe5ba0`
- V4.1 发布清单 SHA-256：
  `c7a5fe349137b5b5f1e37082ae69b0e5d175bf174e4a27b71061975afac3c036`
- 使用新 V4.1 workspace 重新执行发布构建，得到同一个 release ID、1275 个发布候选和相同
  三折样本数量。

每个外部版本根目录均保存 `migration_manifest.json`，记录来源提交、迁移时间、清单统计和
发布清单哈希。
