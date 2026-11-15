# 训练机生成 + 本机 SSH 审查运行手册

**状态：** 跨机审查操作手册。本轮已在训练机真机完整跑通一遍（部署、启动服务、建立 SSH 隧道、浏览器审查验证、记录回传），训练机相关操作事实来自该次执行；代码行为类结论按 `script/subvideo_review/server.py` 对应位置核对标注，未现场复验。

## 1. 适用范围与角色分工

- 训练机：执行子视频生成，媒体产物留在训练机，不回传；运行审查服务。
- 本机 Mac：通过 SSH 本地端口转发在浏览器审查片段，维护代码与文档，将审核记录带回并提交 Git。

审查服务只监听训练机回环地址，不对外暴露；本机通过 SSH 本地端口转发访问。

## 2. 事实清单

| 项 | 值 | 依据 |
| --- | --- | --- |
| 训练机入口 | `ssh liuyang@100.70.83.68`；主机名 `dell-Precision-3660` 直接登录会因默认用户名错误被拒 | 本轮实测 |
| 训练机项目根 | `~/文档/TensileAgent-Finetune`，绝对路径 `/home/liuyang/文档/TensileAgent-Finetune` | 本轮实测 |
| 训练机 Git 状态 | 该目录不是 git 仓库；快照式部署，两机同步靠 sha256 比对 + 逐文件传输，禁止在训练机执行 `git pull` | 本轮实测 |
| Python 解释器 | 训练机默认 `python3` 为 3.10.12，不满足 `pyproject.toml` 的 `>=3.11,<3.12`；审查服务须用 3.11 解释器，可用路径 `/home/liuyang/miniconda3/envs/agent/bin/python3.11`（3.11.15）；服务只使用 Python 标准库 | 解释器路径与版本属本轮实测；「仅使用标准库」按 `script/subvideo_review/server.py:3–18` 导入核对，未现场复验 |
| 服务端口与绑定 | 服务端口 8765，只绑定 `127.0.0.1` | 本轮实测（与 `script/subvideo_review/server.py:703` 代码一致） |
| 媒体与清单 | `data/sub_video/manifest.json`、`data/sub_video/videos/`（含 1,621 个 mp4）、源视频 `data/videos/`、划分 `data/splits/three-fold/` | 本轮实测 |
| 审核记录 | `data/subvideo-review/reviews.json`；Git 跟踪，schema `tensile-subvideo-human-review/2`（与 `server.py:36` 字面量一致） | 记录回传本机属本轮实测；schema 字面量按 `server.py:36` 核对，未现场复验 |
| 已知缺失 | 训练机缺少 `data/sub_video/audit.json`，因此页面「检查提示 → 标签组合待复核」筛选不可用；页面显示「未找到标签组合核验记录；不能据此判断没有待复核问题。」（与 `server.py:158` 文案一致） | 本轮实测；文案按 `server.py:158` 核对，未现场复验 |

## 3. 每轮标准流程

### 3.1 训练机生成（只定位入口）

子视频生成在训练机执行，产物留训练机，不回传。生成入口与授权边界见 `script/subvideo_generation/generate.py` 与 `docs/subvideo-current-logic.md`，本文不复述生成规则。

### 3.2 确认输入身份

审查服务启动时会校验清单、七份划分文件、`docs/label.md` 标签规则摘要；运行中任一文件被改动会导致保存失败（409）。

确认以下文件在审查期间不会被改动或新增：

- `data/sub_video/manifest.json`
- `data/splits/three-fold/` 下全部 JSON
- `docs/label.md`
- `data/sub_video/audit.json`（训练机当前缺少该文件，审查期间不得生成或拷入）

不要在审查进行中重跑生成，也不要在审查期间新增或替换 `data/sub_video/audit.json`。

可照抄的核对思路。训练机侧：

```bash
ssh liuyang@100.70.83.68 'cd "/home/liuyang/文档/TensileAgent-Finetune" && sha256sum data/sub_video/manifest.json data/splits/three-fold/*.json docs/label.md'
```

本机侧（在项目根直接执行，不带 ssh）：

```bash
sha256sum data/sub_video/manifest.json data/splits/three-fold/*.json docs/label.md
```

按相对路径逐行比对 hash；任一行不一致就先定位差异，再决定是否启动服务。

### 3.3 启动审查服务（训练机）

```bash
ssh liuyang@100.70.83.68 '
cd "/home/liuyang/文档/TensileAgent-Finetune" || exit 1
setsid nohup /home/liuyang/miniconda3/envs/agent/bin/python3.11 \
  -m script.subvideo_review.server --project-root "/home/liuyang/文档/TensileAgent-Finetune" \
  serve --port 8765 > /tmp/subvideo-review.log 2>&1 < /dev/null &
echo $! > /tmp/subvideo-review.pid
sleep 2; cat /tmp/subvideo-review.pid'
```

参数顺序要求：`--project-root`、`--manifest`、`--records`、`--max-media-mib` 是全局参数，必须写在 `serve` 子命令之前；`--port` 属于 `serve`。默认记录文件是项目内 `data/subvideo-review/reviews.json`（按 `server.py:688–692` 参数解析核对，未现场复验）。

### 3.4 启动自检（训练机）

确认服务只监听回环地址：

```bash
ssh liuyang@100.70.83.68 'ss -ltnp | grep 8765'
```

期望只看到 `127.0.0.1:8765`。

在训练机上直接访问核心接口：

```bash
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/'
# 期望 200
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/api/bootstrap'
# 期望 200
```

取清单中任一片段 ID 并访问媒体：

```bash
ssh liuyang@100.70.83.68 'cd "/home/liuyang/文档/TensileAgent-Finetune" && /home/liuyang/miniconda3/envs/agent/bin/python3.11 -' <<'PY'
import json
print(json.load(open("data/sub_video/manifest.json"))["candidates"][0]["candidate_id"])
PY
```

清单结构 `manifest["candidates"][*]["candidate_id"]` 已按 `server.py` 解析逻辑核对，未现场复验。用取到的 ID 替换 `<candidate_id>`：

```bash
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765/media?candidate_id=<candidate_id>"'
# 期望 200；浏览器分段请求时为 206
```

查看启动日志：

```bash
ssh liuyang@100.70.83.68 'tail -n 5 /tmp/subvideo-review.log'
```

正常输出会打印工作台地址、只读清单路径与独立审核历史路径（按 `server.py:704–705` 代码核对，未现场复验）。

### 3.5 建立隧道（本机）

```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN        # 先确认本机 8765 空闲
ssh -o ExitOnForwardFailure=yes -f -N -L 8765:127.0.0.1:8765 liuyang@100.70.83.68
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/
```

本机浏览器打开 `http://127.0.0.1:8765`；`-f` 表示后台运行，`-N` 表示不执行远程命令。

端口约束（按 `server.py:573–580` 代码核对，未现场复验）：`server.py` 的 `valid_host` 只接受 `Host: 127.0.0.1:<服务端口>`（或 `localhost:<服务端口>`），不匹配返回 403「仅接受本机服务地址」。因此**本机转发端口必须与训练机 `serve --port` 相同**。若本机 8765 已被占用，两条处置路径：

1. 先释放本机 8765；
2. 或改训练机为 `serve --port 8766`，并用 `-L 8766:127.0.0.1:8766`（该做法按代码推导，本次未现场复验）。

**禁止**把本机其他端口转发到远端 8765，例如 `-L 8766:127.0.0.1:8765`。

若改用 8766，必须**全部**同步替换以下位置；漏一处可能出现「浏览器打得开但保存不了」或诊断结论错位：

| 位置 | 原值 | 替换为 |
| --- | --- | --- |
| 3.3 启动服务 | `serve --port 8765` | `serve --port 8766` |
| 3.4 监听检查 | `ss -ltnp \| grep 8765` | `ss -ltnp \| grep 8766`（期望只看到 `127.0.0.1:8766`） |
| 3.4 自检 curl | `http://127.0.0.1:8765/...` | `http://127.0.0.1:8766/...` |
| 3.5 本机端口占用检查 | `lsof -nP -iTCP:8765 -sTCP:LISTEN` | `lsof -nP -iTCP:8766 -sTCP:LISTEN` |
| 3.5 SSH 隧道 | `-L 8765:127.0.0.1:8765` | `-L 8766:127.0.0.1:8766` |
| 3.5 隧道自检 curl | `http://127.0.0.1:8765/` | `http://127.0.0.1:8766/` |
| 3.5 浏览器地址 | `http://127.0.0.1:8765` | `http://127.0.0.1:8766` |
| 3.7 本机诊断 | `lsof -nP -iTCP:8765 -sTCP:LISTEN` | `lsof -nP -iTCP:8766 -sTCP:LISTEN` |
| 3.7 训练机诊断 | `curl http://127.0.0.1:8765/` | `curl http://127.0.0.1:8766/` |
| 3.8 停隧道 | `lsof -nP -iTCP:8765 -sTCP:LISTEN` | `lsof -nP -iTCP:8766 -sTCP:LISTEN` |

切换前必须先停掉旧服务（本机执行，作用于训练机进程）：

```bash
ssh liuyang@100.70.83.68 'kill $(cat /tmp/subvideo-review.pid) && rm -f /tmp/subvideo-review.pid'
```

不要在本机直接执行 `kill $(cat /tmp/subvideo-review.pid)`，PID 文件在训练机。

然后确认训练机与本机目标端口都空闲（本机 `lsof -nP -iTCP:<端口> -sTCP:LISTEN`、训练机 `ss -ltnp | grep <端口>`），再重新启动；不要把旧 PID 文件当成本次进程。

### 3.6 本机审查操作要点

- 逐片确认 11 项后点「确认完成，进入下一个」，页面会自动进入下一候选并尝试播放；若浏览器阻止自动播放，按页面提示手动点击播放。筛选末位不触发跳转。
- 每个标签选项下方显示源视频对应标注，只作参考，不写入审核值；确认时 11 项必须填满，未判断请明确选择「无法判断」。
- 左侧列表可折叠；宽屏下标签区自身滚动，视频保持在视口内。
- 「确认」只表示该片段得到人工决定，不等于数据发布。

### 3.7 常见故障与处置

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 页面样式/布局是旧的，按钮仍是「一次确认全部」 | 浏览器缓存，或训练机上的静态文件仍是旧快照。**注意：** `server.py` 对 `/`、`/index.html`、`/app.js`、`/style.css` 均经 `respond()` 返回并带 `Cache-Control: no-store`（按 `server.py:582–595` 核对，未现场复验），不存在服务端未禁止缓存的原因。 | 在本机浏览器按 ⌘+Shift+R 强制刷新；仍不对则用 `sha256sum` 比对训练机与本机 `script/subvideo_review/static/` 下同名文件，不一致时按逐文件同步补齐。 |
| 打开页面空白或连不上 | SSH 隧道断了 | 重新执行 3.5 节；先用本机 `lsof -nP -iTCP:8765 -sTCP:LISTEN` 与训练机上的 `curl http://127.0.0.1:8765/` 判断是隧道问题还是服务问题。 |
| 页面提示「媒体无法播放」 | 候选媒体不存在或片段摘要不符 | 核对 `--project-root` 是否指向训练机项目根、`data/sub_video/videos/` 下是否有该文件；禁止靠重新生成来「修复」。 |
| 保存时报 409 | 清单、划分、标签规则或核验记录在服务运行期间被改动。`server.py` 实际返回的文案包括（按 `server.py:394–397` 核对，未现场复验）：「生成清单在服务启动后已变化；请先记录未保存输入并重启。已保存且身份未变的审核记录会保留」、「数据划分在服务启动后已变化；请重启并重新核对」、「标签规则在服务启动后已变化；请重启并重新核对」、「核验记录在服务启动后已变化；问题提示需重新匹配，请重启并重新核对」。 | 停止服务，按 3.2 节核对输入身份后重启；禁止绕过校验。 |
| 启动报 Python 版本或语法错误 | 使用了训练机系统 `python3`（3.10） | 改用 `/home/liuyang/miniconda3/envs/agent/bin/python3.11`。 |
| 「标签组合待复核」筛选不可用 | 训练机缺少 `data/sub_video/audit.json`（见第 2 节） | 不要据此判断没有待复核问题；如需该提示，须先确认 `data/sub_video/audit.json` 的来源与授权后再补入，不在审查期间临时生成。 |

### 3.8 收尾

本机命令均在项目根执行；`<PID>` 与 `<端口>` 需替换为实际值，`kill` 前先确认该 PID 确是本次 SSH 隧道或审查服务进程。

```bash
# 1. 先停止页面操作，再停止训练机服务
ssh liuyang@100.70.83.68 'kill $(cat /tmp/subvideo-review.pid) && rm -f /tmp/subvideo-review.pid'

# 2. 确认训练机服务已停；看到 "8765 已无监听" 再执行下一步
ssh liuyang@100.70.83.68 'ss -ltnp | grep 8765 || echo "8765 已无监听"'

# 3. 回传审核记录到本机
scp liuyang@100.70.83.68:'/home/liuyang/文档/TensileAgent-Finetune/data/subvideo-review/reviews.json' \
  ./data/subvideo-review/reviews.json

# 4. 核对两端记录文件 hash
ssh liuyang@100.70.83.68 'cd "/home/liuyang/文档/TensileAgent-Finetune" && sha256sum data/subvideo-review/reviews.json'
sha256sum data/subvideo-review/reviews.json

# 5. 停止本机 SSH 隧道（先取 PID，再 kill）
lsof -nP -iTCP:8765 -sTCP:LISTEN        # 取本机隧道 PID
kill <PID>
```

若第 2 步仍看到 `127.0.0.1:8765` 监听，先确认进程是否退出（必要时再停一次），否则不要在服务仍可能写入时执行 `scp`。

`reviews.json` 受 Git 跟踪，审核后应提交；页面「导出审核记录」得到的 jsonl 只作交换，禁止覆盖 `reviews.json`。

## 4. 两机同步规则

本机命令均在项目根执行；`<TS>` 需替换为实际时间戳。

- 只同步代码与文档（如 `script/subvideo_review/**`、`docs/**`），逐文件 `rsync`，禁止加 `--delete`，禁止整目录覆盖。示例（以本文档为例，路径按实际文件替换）：

```bash
rsync -av docs/training-machine-review-runbook.md \
  liuyang@100.70.83.68:'/home/liuyang/文档/TensileAgent-Finetune/docs/training-machine-review-runbook.md'
```

- **禁止从本机向训练机写入或覆盖 `data/` 下任何文件**，包括 `data/sub_video/manifest.json`、`data/sub_video/videos/`、`data/splits/` 等；媒体产物留训练机。
- **禁止把训练机上的媒体文件回传到本机**，`data/sub_video/videos/` 等媒体产物继续留在训练机。
- **唯一允许的回传方向是训练机 → 本机**：`data/subvideo-review/reviews.json`（审核记录，见 3.8）。清单如需回传本机并提交，属 `docs/TODO.md` 第 4 节 DATA-HANDOFF 的要求，须先核对清单身份再回传，本文不把它固化为每轮固定步骤。
- **禁止修改 `script/subvideo_review/server.py`**：它决定身份摘要的计算。改动参与 `review_subject_sha256` 的输入或计算方式，可能导致已存记录被判定为其他身份而隔离；改动 `revision_sha256` 的计算方式会让记录完整性校验失败、拒绝覆盖。确需修改时须单独评估影响并另案处理。仅改注释或不参与身份计算的代码不会改变身份，但本流程仍不允许顺手改动该文件。
- 同步前后必须双向 `sha256sum` 核对；覆盖前在训练机建 `.sync-backup-<时间戳>/` 备份并复制待覆盖文件进备份目录。示例（以本文档为例，路径按实际文件替换）：

```bash
# 在训练机上建备份目录，并把待覆盖的现有版本复制进去
TS=$(date +%Y%m%d%H%M%S)
ssh liuyang@100.70.83.68 "cd '/home/liuyang/文档/TensileAgent-Finetune' && mkdir -p '.sync-backup-$TS/docs' && cp 'docs/training-machine-review-runbook.md' '.sync-backup-$TS/docs/'"

# 本机执行覆盖同步（示例文件为本文档，路径按实际文件替换）
rsync -av docs/training-machine-review-runbook.md \
  liuyang@100.70.83.68:'/home/liuyang/文档/TensileAgent-Finetune/docs/training-machine-review-runbook.md'

# 回滚：把备份复制回原位（把 <TS> 换成实际时间戳）
ssh liuyang@100.70.83.68 "cd '/home/liuyang/文档/TensileAgent-Finetune' && cp '.sync-backup-<TS>/docs/training-machine-review-runbook.md' 'docs/training-machine-review-runbook.md'"
```

- 训练机不是 git 仓库，本机提交的 Git 历史无法在训练机复现；需要追溯时以本机仓库为准。

## 5. 与既有文档的关系

工具启动、导出与记录说明见 `script/subvideo_review/README.md`；审核与评价衔接口径见 `docs/subvideo-review-workflow.md`；数据迁移位置与待办状态见 `docs/TODO.md`（第 4 节 DATA-HANDOFF、第 6 节 SUBVIDEO-HUMAN-REVIEW）。本文只负责「跨机怎么跑起来、怎么收尾、同步边界在哪」。数据迁移决定（媒体留训练机、记录回传、回环服务 + SSH 隧道）来自 `docs/TODO.md` 第 4 节，本轮已按该方案在训练机真机跑通。本轮跨机跑通产生的少量审核记录只用于验证链路，不构成 `docs/TODO.md` 第 6 节 SUBVIDEO-HUMAN-REVIEW 的 B0/B1/B2/B3 批次进度；批次与进度以该节和独立审核记录为准。

## 6. 失效条件

当训练机入口/路径、解释器路径、端口、审查服务参数、记录文件结构、同步方式任一发生变化时，须同步更新本文并重新核对。本文所述为一次性工作流记录，不构成对生成、训练或数据发布的授权。
