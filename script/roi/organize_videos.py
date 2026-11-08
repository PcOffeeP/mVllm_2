#!/usr/bin/env python3
"""Copy current ROI results into one directory and preserve their identities."""
from __future__ import annotations

import json
import subprocess
import sys

from core import RoiError
from roi import parser, workspace


def main(argv=None) -> int:
    arguments=parser()
    arguments.description="将当前完整 ROI 清单的结果复制并关联到 data/roi/videos/<视频ID>.mp4"
    args=arguments.parse_args(argv)
    if args.scan or args.batch:
        arguments.error("整理目录不接受 --scan 或 --batch；此操作不会编码视频")
    try:
        work=workspace(args)
        result=work.organize_videos()
        print(json.dumps({"total":result["total"],"summary":result["summary"],
                          "complete":result["complete"],"videos_dir":str(work.organized_videos_dir),
                          "manifest":str(work.manifest_path)},ensure_ascii=False,indent=2))
        return 0
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())
