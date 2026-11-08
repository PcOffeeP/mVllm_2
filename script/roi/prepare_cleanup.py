#!/usr/bin/env python3
"""Preview duplicate ROI media; optionally normalize manifest references."""
from __future__ import annotations

import json
import subprocess
import sys

from core import RoiError
from roi import parser, workspace


def main(argv=None) -> int:
    arguments=parser()
    arguments.description="预览 ROI 重复文件与引用更新；不删除、不移动、不编码视频"
    arguments.add_argument("--apply",action="store_true",
                           help="仅将可核验的同内容历史引用关联到 videos，默认只读预览")
    args=arguments.parse_args(argv)
    if args.scan or args.batch:
        arguments.error("清理准备不接受 --scan 或 --batch；此操作不会编码视频")
    try:
        result=workspace(args).prepare_cleanup(apply=args.apply)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
