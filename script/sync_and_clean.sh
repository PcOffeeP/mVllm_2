#!/usr/bin/env bash
# 同步主线并安全清理已合并的 work/* worktree 与本地分支。
#
# 四重安全锁（全部满足才会清理，否则自动跳过）：
#   1. 仅处理 work/* 分支（绝不触碰 feat/tensileagent-finetune、main 或其他分支）
#   2. 必须已完全合并进 github/feat/tensileagent-finetune（merge-base --is-ancestor）
#   3. 对应 worktree 必须完全干净（无未提交修改、无未跟踪文件）
#   4. 绝不删除当前命令运行所在的 worktree
#
# 用法：
#   bash script/sync_and_clean.sh            # 执行同步与安全清理
#   bash script/sync_and_clean.sh --dry-run  # 仅预演并打印将要执行的动作

set -euo pipefail

REMOTE="github"
MAIN_BRANCH="feat/tensileagent-finetune"
MAIN_REF="${REMOTE}/${MAIN_BRANCH}"
DRY_RUN=false

if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=true
elif [ "${1:-}" != "" ]; then
  echo "用法: $0 [--dry-run]" >&2
  exit 2
fi

CURRENT_TOPLEVEL="$(git rev-parse --show-toplevel)"
CURRENT_REALPATH="$(cd "$CURRENT_TOPLEVEL" && pwd -P)"

echo "==> 1/4 拉取远程最新状态并清理已删远程引用 (${REMOTE})..."
git fetch --prune "$REMOTE"

if ! git rev-parse --verify --quiet "$MAIN_REF" >/dev/null; then
  echo "❌ 找不到远端主线引用 ${MAIN_REF}，已中止。" >&2
  exit 1
fi

# 解析 git worktree list --porcelain，定位主工作区和所有 work/* worktree
MAIN_WT=""
WORK_WT_PATHS=()
WORK_WT_BRANCHES=()

wt_path=""
wt_branch=""
flush_worktree() {
  if [ -n "$wt_path" ] && [ -n "$wt_branch" ]; then
    if [ "$wt_branch" = "$MAIN_BRANCH" ]; then
      MAIN_WT="$wt_path"
    elif [[ "$wt_branch" == work/* ]]; then
      WORK_WT_PATHS+=("$wt_path")
      WORK_WT_BRANCHES+=("$wt_branch")
    fi
  fi
  wt_path=""
  wt_branch=""
}

while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "worktree "*)
      wt_path="${line#worktree }"
      ;;
    "branch refs/heads/"*)
      wt_branch="${line#branch refs/heads/}"
      ;;
    "")
      flush_worktree
      ;;
  esac
done < <(git worktree list --porcelain; echo "")

echo "==> 2/4 同步主工作区 (${MAIN_BRANCH})..."
if [ -n "$MAIN_WT" ] && [ -d "$MAIN_WT" ]; then
  if [ -z "$(git -C "$MAIN_WT" status --porcelain)" ]; then
    if $DRY_RUN; then
      echo "  [dry-run] 将同步主工作区: git -C \"$MAIN_WT\" pull --ff-only ${REMOTE} ${MAIN_BRANCH}"
    else
      git -C "$MAIN_WT" pull --ff-only "$REMOTE" "$MAIN_BRANCH"
    fi
  else
    echo "  ⚠️ 跳过主工作区同步（存在未提交改动）: $MAIN_WT"
  fi
else
  echo "  ℹ️ 未检测到检出 ${MAIN_BRANCH} 的工作区，跳过 pull。"
fi

echo "==> 3/4 扫描并安全清理已合并的 work/* worktree..."
removed_wt_count=0
skipped_wt_count=0

for i in "${!WORK_WT_PATHS[@]}"; do
  p="${WORK_WT_PATHS[$i]}"
  b="${WORK_WT_BRANCHES[$i]}"

  if [ ! -d "$p" ]; then
    echo "  ℹ️ 目录已不存在，稍后将由 worktree prune 清理: $p ($b)"
    continue
  fi

  p_real="$(cd "$p" && pwd -P)"
  if [ "$p_real" = "$CURRENT_REALPATH" ]; then
    echo "  ⏭️ 跳过当前所在工作区: $p ($b)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if ! git merge-base --is-ancestor "refs/heads/${b}" "$MAIN_REF" 2>/dev/null; then
    echo "  ⏭️ 跳过未合并分支: $b ($p)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if [ -n "$(git -C "$p" status --porcelain)" ]; then
    echo "  ⏭️ 跳过含未提交改动的工作区: $b ($p)"
    skipped_wt_count=$((skipped_wt_count + 1))
    continue
  fi

  if $DRY_RUN; then
    echo "  [dry-run] 将删除已合并且干净的 worktree: $p ($b)"
  else
    git worktree remove "$p"
    echo "  🧹 已删除 worktree: $p ($b)"
  fi
  removed_wt_count=$((removed_wt_count + 1))
done

if ! $DRY_RUN; then
  git worktree prune
fi

echo "==> 4/4 扫描并安全清理已合并且未检出的本地 work/* 分支..."
removed_br_count=0
skipped_br_count=0

# 重新收集当前仍被任意 worktree 检出的分支集合
ACTIVE_BRANCHES=""
while IFS= read -r line; do
  case "$line" in
    "branch refs/heads/"*)
      ACTIVE_BRANCHES+="${line#branch refs/heads/}"$'\n'
      ;;
  esac
done < <(git worktree list --porcelain)

while IFS= read -r b; do
  [ -z "$b" ] && continue

  if printf '%s' "$ACTIVE_BRANCHES" | grep -Fxq "$b"; then
    echo "  ⏭️ 跳过仍被 worktree 占用的分支: $b"
    skipped_br_count=$((skipped_br_count + 1))
    continue
  fi

  if ! git merge-base --is-ancestor "refs/heads/${b}" "$MAIN_REF" 2>/dev/null; then
    echo "  ⏭️ 跳过未合并分支: $b"
    skipped_br_count=$((skipped_br_count + 1))
    continue
  fi

  if $DRY_RUN; then
    echo "  [dry-run] 将删除已合并本地分支: $b"
  else
    git branch -d "$b"
    echo "  🧹 已删除本地分支: $b"
  fi
  removed_br_count=$((removed_br_count + 1))
done < <(git for-each-ref --format='%(refname:short)' 'refs/heads/work/*')

echo ""
echo "✅ 完成：清理 worktree ${removed_wt_count} 个（跳过 ${skipped_wt_count}），清理本地分支 ${removed_br_count} 个（跳过 ${skipped_br_count}）。"
