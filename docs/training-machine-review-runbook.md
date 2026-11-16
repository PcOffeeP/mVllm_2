# 训练机生成 + 本机 SSH 审查运行手册

本手册说明如何在训练机生成子视频并启动审查服务，再在本机通过 SSH 隧道逐片审核并带回记录。

## 1. 角色分工与安全边界
- **训练机**：作为媒体生成与留存的主场所，执行子视频生成；运行审查服务。
- **本机**：通过 SSH 本地端口转发在浏览器审查片段；维护代码与文档；将审核记录带回并按项目 Git 纪律提交。本机媒体副本须按第 5.1 节从训练机单向同步并全量哈希核对后才用于审查。

审查服务只监听训练机回环地址 `127.0.0.1`，不对外暴露；本机通过 SSH 本地端口转发访问，禁止公网映射或反向代理。

## 2. 开始之前

满足以下条件后再启动服务：

- SSH 可达训练机：`liuyang@100.70.83.68`。直接用主机名 `dell-Precision-3660` 会以错误用户名登录失败，必须显式写用户名。
- 训练机项目工作区：`~/文档/TensileAgent-Finetune`（绝对路径 `/home/liuyang/文档/TensileAgent-Finetune`）。该目录不是 git 仓库，不要在上面执行 `git pull`；同步靠逐文件传输 + `sha256` 比对。
- Python 3.11：`pyproject.toml` 要求 `>=3.11,<3.12`；系统 `python3` 未必是 3.11，启动服务用绝对路径解释器 `/home/liuyang/miniconda3/envs/agent/bin/python3.11`。
- 本机可建立 SSH 隧道，且待转发端口当前空闲。
- 审查期间不重新生成子视频，不新增或替换 `data/sub_video/audit.json`；服务启动后会校验清单、七份划分文件、`docs/label.md` 标签规则摘要（以及 `data/sub_video/audit.json` 若存在），运行中任一被改动会导致保存被拒。

先核对两端输入身份：

```bash
# 输入身份核对：训练机
ssh liuyang@100.70.83.68 'cd "/home/liuyang/文档/TensileAgent-Finetune" && sha256sum data/sub_video/manifest.json data/splits/three-fold/*.json docs/label.md'

# 输入身份核对：本机（项目根执行，不加 ssh）
sha256sum data/sub_video/manifest.json data/splits/three-fold/*.json docs/label.md
```

按相对路径逐行比对 `sha256` 输出；任一行不一致就先定位差异，再决定是否启动服务。

## 3. 一轮审查的完整步骤

### 3.1 生成

在训练机执行子视频生成，产物留在训练机。入口与授权边界见 `script/subvideo_generation/generate.py` 与 `docs/subvideo-current-logic.md`，本文不复述生成规则。

### 3.2 启动服务

```bash
# 启动审查服务（训练机）
ssh liuyang@100.70.83.68 '
cd "/home/liuyang/文档/TensileAgent-Finetune" || exit 1
setsid nohup /home/liuyang/miniconda3/envs/agent/bin/python3.11 \
  -m script.subvideo_review.server \
  --project-root "/home/liuyang/文档/TensileAgent-Finetune" \
  serve --port 8765 > /tmp/subvideo-review.log 2>&1 < /dev/null &
echo $! > /tmp/subvideo-review.pid
sleep 2; cat /tmp/subvideo-review.pid'
```

参数顺序要求：`--project-root`、`--manifest`、`--records`、`--max-media-mib` 是全局参数，必须写在 `serve` 之前；`--port` 属于 `serve` 子命令。默认记录文件是 `data/subvideo-review/reviews.json`。

### 3.3 自检

```bash
# 启动自检（训练机）
ssh liuyang@100.70.83.68 'ss -ltnp | grep 8765'
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/'
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/api/bootstrap'
ssh liuyang@100.70.83.68 'curl -sS http://127.0.0.1:8765/api/bootstrap' | grep -oE '"candidate_id":[ ]*"[^"]*"' | head -n 1
ssh liuyang@100.70.83.68 'tail -n 5 /tmp/subvideo-review.log'
```

`ss` 只应看到 `127.0.0.1:8765`；两个 `curl` 期望返回 200；第三条取一个候选 ID 替换下面命令中的 `<candidate_id>`，媒体接口期望 200（浏览器分段请求为 206）；日志会打印工作台地址、只读清单路径与独立审核历史路径。

```bash
# 媒体自检（训练机）
ssh liuyang@100.70.83.68 'curl -sS -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:8765/media?candidate_id=<candidate_id>"'
```

### 3.4 建隧道

```bash
# 建隧道（本机）
lsof -nP -iTCP:8765 -sTCP:LISTEN
ssh -o ExitOnForwardFailure=yes -f -N -L 8765:127.0.0.1:8765 liuyang@100.70.83.68
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/
```

浏览器打开 `http://127.0.0.1:8765`；`-f` 后台运行，`-N` 不执行远程命令。

服务只接受 `Host: 127.0.0.1:<服务端口>`（或 `localhost:<服务端口>`），因此**本机转发端口必须与训练机 `--port` 一致**。禁止跨端口转发，例如 `-L 8766:127.0.0.1:8765` 会被全部拒绝为 403。若确实要换端口，启动、自检、隧道、浏览器地址四处必须同步改，漏一处会出现「页面打得开但保存不了」或诊断错位。切端口前先停旧服务，PID 文件在训练机，不要在本机 `kill`。

### 3.5 审查操作

- 逐项确认 11 项后点「确认完成，进入下一个」。
- 确认后自动进入下一候选并尝试播放；浏览器可能阻止自动播放，按页面提示手动点击播放。筛选末位不触发跳转。
- 左侧候选列表可折叠；宽屏下标签区自身滚动，视频保持在视口内。

标签怎么判、两个说明字段怎么写，见第 4 节。

### 3.6 收尾

先取记录再停服务，不要在服务可能写入时复制。页面上先停止操作并确认无未保存内容，再执行：

```bash
# 收尾 1：回传审核记录（训练机 → 本机，项目根执行）
scp liuyang@100.70.83.68:'/home/liuyang/文档/TensileAgent-Finetune/data/subvideo-review/reviews.json' \
  ./data/subvideo-review/reviews.json

# 收尾 2：核对两端 sha256 一致
ssh liuyang@100.70.83.68 'cd "/home/liuyang/文档/TensileAgent-Finetune" && sha256sum data/subvideo-review/reviews.json'
sha256sum data/subvideo-review/reviews.json

# 收尾 3：停训练机服务并确认端口释放
ssh liuyang@100.70.83.68 'kill $(cat /tmp/subvideo-review.pid) && rm -f /tmp/subvideo-review.pid'
ssh liuyang@100.70.83.68 'ss -ltnp | grep 8765 || echo "8765 已无监听"'

# 收尾 4：关闭本机隧道（<PID> 换成上面 lsof 查到的隧道进程号）
lsof -nP -iTCP:8765 -sTCP:LISTEN
kill <PID>
```

若端口仍在监听，先确认进程是否真的退出，再执行回传。最后在本机按项目 Git 纪律提交 `reviews.json`（受 Git 跟踪）。

## 4. 审查时的判断与填写

- 五类标签共 11 项必须全部填满才能确认；未判断要显式选「无法判断」，空白不等于「否」。
- 源标签只作参考，不写入审核值；候选标签预填只是草稿，须逐项核对或修改后再确认。

两个说明字段的填写规则：

- **审核备注**（可选）：写画面证据，便于日后复核。例如：`断口在标距中段偏右，颈缩明显，1.6s 处瞬间分离，两侧夹持无滑移。`
- **决定依据**（三种情况必填）：退回、记录疑问、修改已确认结论（非草稿）时必须填写；首次确认与保存草稿可留空。写「这次操作和默认/上次不一样的依据」。例如：`上一轮把界面分离判为否；重看 0.8–1.2s 可见界面明显分离，改判为是。`

## 5. 代码与文档的同步规则

代码与文档同步，以及允许回传的媒体和审核记录，按下面的边界执行：

- 逐文件 `rsync`，禁止 `--delete`，禁止整目录覆盖。
- **禁止从本机向训练机写入或覆盖 `data/` 下任何文件**。
- 媒体回传按第 5.1 节执行：训练机 → 本机单向、仅待审批次媒体目录、全量哈希核对。
- 审核记录（`data/subvideo-review/reviews.json`）允许从训练机回传本机，按第 3.6 节执行；除此之外，`data/` 下非媒体文件禁止从训练机覆盖本机。
- 覆盖前在训练机建 `.sync-backup-<时间戳>/` 备份，把待覆盖文件复制进去。
- **不要修改 `script/subvideo_review/server.py`**：它参与审核记录的身份摘要（`review_subject_sha256`、`revision_sha256`），改动会让已有记录被判定为其他身份或完整性校验失败。确需改动须单独评估、另案处理，本流程不允许顺手改。
- 页面「导出审核记录」得到的 jsonl 只作交换，禁止覆盖 `reviews.json`。
- 训练机不是 git 仓库，追溯以本机仓库为准。

同步示例（以本文档为例，路径按实际文件替换）：

```bash
TS=$(date +%Y%m%d%H%M%S)
ssh liuyang@100.70.83.68 "cd '/home/liuyang/文档/TensileAgent-Finetune' && mkdir -p '.sync-backup-$TS/docs' && cp 'docs/training-machine-review-runbook.md' '.sync-backup-$TS/docs/'"
rsync -av docs/training-machine-review-runbook.md \
  liuyang@100.70.83.68:'/home/liuyang/文档/TensileAgent-Finetune/docs/training-machine-review-runbook.md'
```

回滚时把 `.sync-backup-<时间戳>/...` 复制回原位。

### 5.1 审查前媒体同步（训练机 → 本机）

- **方向与范围**：只允许训练机 → 本机单向同步，严禁本机 → 训练机。只同步待审批次的媒体目录：当前为 `data/sub_video/videos/`；后续批次以该批次 `manifest.json` 中 `output_path` 的父目录为准。不包含 `data/` 下其它文件，包括清单、划分、标注、ROI 和审核记录；审核记录按第 3.6 节另行回传。
- **方式**：逐文件 `rsync`，禁止 `--delete` 和整目录覆盖；训练机端只读，不写、不删；本机只增不删，不覆盖已有文件。逐个选取清单中的媒体文件，在本机项目根执行（占位路径替换为该批次实际文件）：

  ```bash
  rsync -av --ignore-existing 'liuyang@100.70.83.68:/home/liuyang/文档/TensileAgent-Finetune/data/sub_video/videos/<文件名>.mp4' 'data/sub_video/videos/<文件名>.mp4'
  ```

- **校验（必做）**：同步后对本批次 `manifest.json` 中每条候选的媒体文件计算 `sha256sum`，与该条 `output.sha256` 全量逐条比对，不得抽样；统计条数、存在数、缺失数、一致数、不一致数。任一缺失或不一致即停，先定位差异，不得带着差异开审。
- **留痕**：将核对结论（条数、一致数、清单 sha256、批次日期）记一行进 `docs/TODO.md` 对应任务项。
- **首次执行记录**：本步骤已实际验证过一次：Mac 侧 `data/sub_video/videos` 现有 1,621 个 `.mp4`（186M），逐条 sha256 与清单 `output.sha256` 一致（1621/1621）。
- **口径**：媒体位置按 DF-048 执行：Mac 侧 `data/sub_video/videos` 为经哈希核对的副本，可直接用于本机审查；训练机仍为二次生成与媒体留存场所。本小节只规定同步操作规则，不改变 DEC-003 第 10 条与 DF-048 的口径。
- **失效条件**：同步范围或校验方式变化时须更新本节，见第 8 节。

## 6. 故障处置

| 现象 | 原因 | 处置 |
| --- | --- | --- |
| 页面连不上 | 隧道断开或服务未启动 | 先用本机 `lsof -nP -iTCP:8765 -sTCP:LISTEN` 与训练机 `curl http://127.0.0.1:8765/` 区分是隧道问题还是服务问题，再重新建隧道或重启服务。 |
| 页面是旧样式或旧文案 | 浏览器缓存，或两端静态文件不一致 | 在本机浏览器按 ⌘+Shift+R 强制刷新；仍不对则比对训练机与本机 `script/subvideo_review/static/` 同名文件并逐文件补齐。服务端已带 `no-store`，不是缓存头的问题。 |
| 视频无法播放 | 候选媒体不存在或 `--project-root` 指向错误 | 核对 `--project-root` 与 `data/sub_video/videos/` 下文件是否存在；不要靠重新生成来「修复」。 |
| 保存被拒（409） | 输入身份在运行期间变化 | 停服务，按第 2 节重新核对身份后重启；禁止绕过校验。已保存且身份未变的记录会保留。 |
| 启动报 Python 版本或语法错误 | 使用了训练机系统 `python3` | 改用 `/home/liuyang/miniconda3/envs/agent/bin/python3.11`。 |
| 端口占用 | 本机或训练机已有进程监听目标端口 | 本机用 `lsof`、训练机用 `ss` 分别查清是哪一端占用；按第 3.4 节的端口规则处理。 |
| 「标签组合待复核」筛选不可用 | 缺少 `data/sub_video/audit.json` | 该提示在缺少对应核验记录文件时不可用，不代表没有待复核问题；需要时先确认来源与授权再补入，不要在审查期间临时生成。 |

## 7. 限制与纪律

- 本文是操作指引，不构成生成、训练或数据发布授权；「确认」只表示该片段得到人工决定，不等于数据发布。
- 不修改原标注、划分、清单或视频；服务停止后页面不可用，未保存内容不进入记录。

## 8. 变更处理（失效条件）

当训练机入口/路径、解释器路径、端口、服务参数、记录文件结构、同步方式任一发生变化时，须同步更新本文并重新核对；改动后先重新核对两端输入身份。同步范围或校验方式发生变化时，须同步更新「审查前媒体同步」一节。
