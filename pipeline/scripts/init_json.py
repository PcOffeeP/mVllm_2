import os
import json
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="基于划分文件初始化训练集的 JSON 标注文件")
    # Define global project root relative to this script
    # Script is in pipeline/scripts/, so root is three levels up (mVllm/)
    project_root = Path(__file__).resolve().parent.parent.parent
    parser.add_argument("--split-file", "-s", type=Path, required=True, 
                       help="划分文件路径 (例如: splits/kfold_5_fold_0.json)")
    parser.add_argument("--batch-name", "-b", type=str, default=None, 
                       help="批次名称 (默认使用split文件名)")
    parser.add_argument("--template", type=Path, 
                       default=project_root / "pipeline" / "templates" / "template.json", 
                       help="模板 JSON 文件路径")
    parser.add_argument("--output-dir", type=Path, 
                       default=project_root / "pipeline" / "batches", 
                       help="批次输出基目录")
    
    args = parser.parse_args()
    
    # 验证 split 文件是否存在
    if not args.split_file.exists():
        print(f"错误: 划分文件不存在: {args.split_file}")
        return
    
    # 读取 split 文件
    try:
        with open(args.split_file, 'r', encoding='utf-8') as f:
            split_data = json.load(f)
    except Exception as e:
        print(f"错误: 无法读取划分文件: {e}")
        return
    
    # 获取训练集视频列表
    if "train" not in split_data:
        print(f"错误: 划分文件中缺少 'train' 键")
        return
    
    train_videos = split_data["train"]
    print(f"从划分文件读取到 {len(train_videos)} 个训练集视频")
    
    # 确定 batch name
    if args.batch_name is None:
        # 使用 split 文件名（不含扩展名）作为 batch name
        batch_name = args.split_file.stem
    else:
        batch_name = args.batch_name
    
    # 读取模板
    if not args.template.exists():
        print(f"错误: 模板文件不存在: {args.template}")
        return

    try:
        with open(args.template, 'r', encoding='utf-8') as f:
            template_content = f.read()
            # 验证 JSON
            template_data_base = json.loads(template_content)
    except Exception as e:
        print(f"错误: 无法读取或解析模板: {e}")
        return

    # 创建输出目录
    batch_dir = args.output_dir / batch_name
    raw_dir = batch_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"初始化批次 '{batch_name}' 到 {raw_dir}")

    count = 0
    for video_path in train_videos:
        # 从视频路径中提取文件名（不含扩展名）作为 JSON 文件名
        video_name = Path(video_path).stem
        json_filename = f"{video_name}.json"
        json_filepath = raw_dir / json_filename
        
        if json_filepath.exists():
            print(f"跳过: {json_filename} (文件已存在)")
            continue
        
        # 复制模板数据
        data = json.loads(template_content)
        
        # 更新视频路径
        # 假设模板中至少有一个 item 且有 videos 字段
        for item in data:
            if "videos" in item and len(item["videos"]) > 0:
                # 确保填入的是相对于项目根目录的相对路径
                # 如果输入已经是相对于项目根的相对路径，relpath 会处理好它
                    # 提取视频文件名，统一映射到 data/videos/ 目录下
                    video_filename = os.path.basename(video_path)
                    final_path = f"videos/{video_filename}"
                    item["videos"][0] = final_path
        
        with open(json_filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"创建: {json_filename}")
        count += 1
        
    print(f"\n完成! 在 {raw_dir} 中生成了 {count} 个文件")

if __name__ == "__main__":
    main()
