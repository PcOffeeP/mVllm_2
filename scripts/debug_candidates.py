"""诊断：检查为什么 build_full_subvideo() 可能返回 None。"""
import json
from pathlib import Path


def main():
    meta_path = Path("data/07_metadata/video_meta.json")
    if not meta_path.exists():
        print(f"❌ {meta_path} 不存在")
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    print(f"video_meta.json: {len(meta)} 条记录\n")

    # 检查前 10 条记录的关键字段和文件存在性
    print("=== 前 10 条记录检查 ===")
    exists_count = 0
    for i, rec in enumerate(meta[:10]):
        vid = rec["video_id"]
        vpath = rec.get("video_path", "N/A")
        vtype = rec.get("type", "N/A")
        hfc = rec.get("has_fracture_canonical", "MISSING")
        evt = rec.get("event_frame_original", "MISSING")
        dur = rec.get("duration", "MISSING")
        exists = Path(vpath).exists() if vpath != "N/A" else False
        if exists:
            exists_count += 1
        print(f"  {vid}: type={vtype} hfc={hfc} event_frame={evt} duration={dur} file_exists={exists}")
        print(f"         path={vpath}")

    print(f"\n前 10 条中文件存在的: {exists_count}/10")

    # 检查所有记录的 has_fracture_canonical 分布
    hfc_dist = {}
    for rec in meta:
        hfc = rec.get("has_fracture_canonical")
        key = str(hfc) if hfc is not None else "None"
        hfc_dist[key] = hfc_dist.get(key, 0) + 1
    print(f"\n=== has_fracture_canonical 分布 ===")
    for k, v in sorted(hfc_dist.items()):
        print(f"  {k}: {v}")

    # 检查所有记录的 type 分布
    type_dist = {}
    for rec in meta:
        t = rec.get("type", "MISSING")
        type_dist[t] = type_dist.get(t, 0) + 1
    print(f"\n=== type 分布 ===")
    for k, v in sorted(type_dist.items()):
        print(f"  {k}: {v}")

    # 检查所有视频文件的整体存在情况（仅统计前 50 条以节省时间）
    print(f"\n=== 视频文件存在性检查（全部 110 条）===")
    total = len(meta)
    exists_total = 0
    missing_samples = []
    for rec in meta:
        vpath = rec.get("video_path", "")
        if Path(vpath).exists():
            exists_total += 1
        else:
            if len(missing_samples) < 5:
                missing_samples.append(rec["video_id"])
    print(f"  存在: {exists_total}/{total}")
    print(f"  缺失: {total - exists_total}/{total}")
    if missing_samples:
        print(f"  缺失示例: {missing_samples}")


if __name__ == "__main__":
    main()
