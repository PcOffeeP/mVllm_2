"""Lightweight binding assertions for subvideo_build_plan defaults."""

from pipeline.scripts import subvideo_build_plan as cli


def test_default_roi_media_dir_matches_canonical_path():
    """Script fallback ROI path matches the canonical data-root-relative path."""
    parser = cli.build_parser()
    args = parser.parse_args([])
    context = cli.data_context_from_arg(cli.PROJECT_ROOT, args.data_root)
    default_roi_media_dir = context.roi_videos / "roi-media-84ea2bd3a052"
    canonical = cli.CURRENT_DATA.roi_videos / "roi-media-84ea2bd3a052"
    assert default_roi_media_dir == canonical
