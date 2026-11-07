#!/bin/bash

export PATH="$PATH:/opt/homebrew/bin:/usr/local/bin"

show_error() {
    printf '\n%s\n' "$1" >&2
    if [[ -t 0 ]]; then
        read -r -p '按回车关闭此窗口。'
    fi
}

if ! script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"; then
    show_error '无法找到标注工具所在的目录。'
    exit 1
fi

python_bin=""
for candidate in "$(command -v python3)" /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    if [[ -x "$candidate" ]] && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        python_bin="$candidate"
        break
    fi
done
if [[ -z "$python_bin" ]]; then
    show_error '需要 Python 3.10 或更新版本。'
    exit 1
fi

"$python_bin" "$script_dir/review_run_annotation.py" "$@"
status=$?
if [[ "$status" -ne 0 && "$status" -ne 130 ]]; then
    show_error '标注工具未能正常启动或已退出，请查看上方原因。'
fi
exit "$status"
