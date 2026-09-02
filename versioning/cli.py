"""最小 data CLI：仅暴露 DVC pipeline 七阶段子命令。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from versioning.data_pipeline import (
    DataPipelineError,
    ReviewGateError,
    StageInputError,
    UnknownStageError,
    run_stage,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="versioning",
        description="可读版本控制 data pipeline CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    data_parser = subparsers.add_parser("data", help="运行数据 pipeline 阶段")
    data_parser.add_argument(
        "stage",
        help="pipeline 阶段名",
    )
    data_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="项目根目录（默认当前目录）",
    )
    data_parser.add_argument(
        "--batch",
        default="batch-001",
        help="数据批次名",
    )
    data_parser.add_argument(
        "--version",
        default=None,
        help="release_validate 时显式指定版本",
    )
    data_parser.add_argument(
        "--protocol",
        default="v4.1",
        help="release 时数据版本协议",
    )
    data_parser.add_argument(
        "--purpose",
        default="development",
        help="release 时数据用途",
    )
    data_parser.add_argument(
        "--results",
        type=Path,
        default=None,
        help="review_import 时显式指定审查结果 YAML 路径",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，返回退出码。"""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse 用法错误返回 2；按约定向上传递。
        return int(exc.code) if isinstance(exc.code, int) else 2

    if args.command != "data":
        parser.error(f"未知子命令: {args.command!r}")
        return 2

    if args.stage == "release_validate":
        # release_validate 只消费版本指针，不接受 batch（与阶段签名对齐）。
        kwargs: dict[str, object] = {}
        if args.version is not None:
            kwargs["version"] = args.version
    else:
        kwargs = {"batch": args.batch}
        if args.stage == "release":
            if args.version is None:
                print("error: data release 必须显式指定 --version", file=sys.stderr)
                return 2
            kwargs["version"] = args.version
            kwargs["protocol"] = args.protocol
            kwargs["purpose"] = args.purpose
        if args.stage == "review_import" and args.results is not None:
            kwargs["results_path"] = args.results

    try:
        run_stage(args.root, args.stage, **kwargs)
    except UnknownStageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except StageInputError as exc:
        print(f"error: 输入缺失/为空 - {exc}", file=sys.stderr)
        return 1
    except ReviewGateError as exc:
        print(f"error: 审查关卡阻断 - {exc}", file=sys.stderr)
        return 1
    except DataPipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: 阶段执行失败 - {exc}", file=sys.stderr)
        return 1

    return 0
