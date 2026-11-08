#!/usr/bin/env python3
"""One entry point for interactive and unattended ROI work."""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from core import RoiError, Workspace


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description="视频 ROI：查看已有裁剪，有问题再调整")
    p.add_argument("--project-root",type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument("--videos-dir",type=Path,default=Path("data/videos"))
    p.add_argument("--output-dir",type=Path,default=Path("data/roi"))
    p.add_argument("--labels",type=Path,default=Path("data/annotation-table-full.csv"))
    p.add_argument("--decisions",type=Path,help="可选决定候选文件；省略时自动读取输出目录 imports 中的文件")
    p.add_argument("--existing-manifest",type=Path)
    p.add_argument("--existing-media-dir",type=Path)
    p.add_argument("--splits-dir",type=Path,help="可选：一个划分版本目录，含 test.json 和 fold_N_train/val.json")
    p.add_argument("--scan",action="store_true",help="仅核对输入并保存状态，不生成视频")
    p.add_argument("--batch",action="store_true",help="仅生成已保存画面范围的条目，其余保留待处理")
    return p


def workspace(args) -> Workspace:
    root=args.project_root.resolve()
    def resolve(value):
        return None if value is None else (value if value.is_absolute() else root/value)
    splits_dir=resolve(args.splits_dir)
    if splits_dir is None:
        split_root=root/"data/splits"
        candidates=[p for p in split_root.iterdir() if p.is_dir() and (p/"test.json").is_file()] if split_root.is_dir() else []
        if len(candidates)==1: splits_dir=candidates[0]
        elif len(candidates)>1:
            print("发现多个划分版本，未自动选择；需要保留划分时请指定 --splits-dir。",file=sys.stderr)
    return Workspace(resolve(args.videos_dir),resolve(args.output_dir),labels=resolve(args.labels),
        decisions=resolve(args.decisions),existing_manifest=resolve(args.existing_manifest),
        existing_media_dir=resolve(args.existing_media_dir),splits_dir=splits_dir)


def main(argv=None) -> int:
    args=parser().parse_args(argv)
    if not args.scan and not args.batch:
        try: import streamlit  # noqa: F401
        except ImportError:
            print("请先安装界面依赖：python3 -m pip install -r script/roi/requirements.txt",file=sys.stderr)
            return 1
        command=[sys.executable,"-m","streamlit","run",str(Path(__file__).with_name("app.py")),
            "--server.address","127.0.0.1","--server.headless","false","--",*(sys.argv[1:] if argv is None else argv)]
        return subprocess.call(command)
    try:
        work=workspace(args); result=work.refresh()
        if args.batch:
            errors=[]
            for row in result["videos"]:
                if row["status"] == "ready":
                    try: work.generate(row["video_id"])
                    except (RoiError,OSError,subprocess.SubprocessError) as exc:
                        errors.append({"video_id":row["video_id"],"error":str(exc)})
            result=work.refresh()
            if errors:
                from core import atomic_json, now
                atomic_json(work.output_dir/"batch-errors.json",{"generated_at":now(),"errors":errors})
                print(json.dumps({"errors":errors},ensure_ascii=False))
                return 1
        print(json.dumps({"total":result["total"],"summary":result["summary"],"complete":result["complete"],
                          "manifest":str(work.manifest_path)},ensure_ascii=False,indent=2))
        return 0 if args.scan or result["complete"] else 2
    except (RoiError,OSError,subprocess.SubprocessError) as exc:
        print(str(exc),file=sys.stderr); return 1


if __name__ == "__main__":
    raise SystemExit(main())
