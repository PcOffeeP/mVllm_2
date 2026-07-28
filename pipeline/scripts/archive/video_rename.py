import os
import shutil
import random
from typing import List, Dict

def batch_rename_videos(
    directory: str,
    mode: str = "sequential",
    prefix: str = "video",
    suffix: str = "",
    old_text: str = "",
    new_text: str = "",
    custom_format: str = "",
    start_index: int = 1,
    padding: int = 3,
    preview: bool = False,
    file_extensions: List[str] = [".mp4"]
) -> Dict[str, List[str]]:
    """
    批量重命名视频文件
    
    Args:
        directory: 视频文件所在目录
        mode: 重命名模式
            - sequential: 按序号重命名 (prefix_001.mp4)
            - add_prefix: 添加前缀
            - add_suffix: 添加后缀（在文件名和扩展名之间）
            - replace: 替换文本
            - custom: 自定义格式
            - random: 随机打乱顺序后按序号重命名
        prefix: 前缀（sequential或add_prefix模式）
        suffix: 后缀（add_suffix模式）
        old_text: 要替换的文本（replace模式）
        new_text: 替换后的文本（replace模式）
        custom_format: 自定义格式（custom模式），支持{index}, {original}, {ext}变量
        start_index: 起始序号
        padding: 序号位数补零
        preview: 是否预览模式（不实际重命名）
        file_extensions: 要处理的文件扩展名列表
    
    Returns:
        重命名结果：{"success": ["old_name -> new_name"], "failed": ["file_name"]}
    """
    if not os.path.isdir(directory):
        raise ValueError(f"目录不存在: {directory}")
    
    # 获取所有符合条件的视频文件
    video_files = []
    for file_name in os.listdir(directory):
        if any(file_name.lower().endswith(ext) for ext in file_extensions):
            video_files.append(file_name)
    
    # 根据模式决定是否打乱顺序
    if mode == "random":
        random.shuffle(video_files)
    else:
        # 按字母顺序排序
        video_files.sort()
    
    success_list = []
    failed_list = []
    
    print(f"找到 {len(video_files)} 个视频文件\n")
    
    for index, file_name in enumerate(video_files, start=start_index):
        old_path = os.path.join(directory, file_name)
        base_name, ext = os.path.splitext(file_name)
        
        try:
            # 根据不同模式生成新文件名
            if mode == "sequential":
                new_base_name = f"{prefix}_{index:0{padding}d}"
            elif mode == "add_prefix":
                new_base_name = f"{prefix}{base_name}"
            elif mode == "add_suffix":
                new_base_name = f"{base_name}{suffix}"
            elif mode == "replace":
                new_base_name = base_name.replace(old_text, new_text)
            elif mode == "custom":
                new_base_name = custom_format.format(
                    index=index,
                    original=base_name,
                    ext=ext[1:]  # 不带点的扩展名
                )
            elif mode == "random":
                new_base_name = f"{prefix}_{index:0{padding}d}"
            else:
                raise ValueError(f"不支持的重命名模式: {mode}")
            
            new_file_name = f"{new_base_name}{ext}"
            new_path = os.path.join(directory, new_file_name)
            
            # 处理文件名冲突
            counter = 1
            while os.path.exists(new_path) and new_path != old_path:
                if mode == "sequential":
                    new_base_name = f"{prefix}_{index:0{padding}d}_{counter}"
                else:
                    new_base_name = f"{new_base_name}_{counter}"
                new_file_name = f"{new_base_name}{ext}"
                new_path = os.path.join(directory, new_file_name)
                counter += 1
            
            # 预览或执行重命名
            if preview:
                result = f"{file_name} -> {new_file_name}"
                success_list.append(result)
                print(f"预览: {result}")
            else:
                if old_path != new_path:
                    shutil.move(old_path, new_path)
                    result = f"{file_name} -> {new_file_name}"
                    success_list.append(result)
                    print(f"已重命名: {result}")
                else:
                    result = f"{file_name} (无变化)"
                    success_list.append(result)
                    print(f"跳过: {result}")
                    
        except Exception as e:
            failed_list.append(file_name)
            print(f"重命名失败 {file_name}: {str(e)}")
    
    print(f"\n重命名完成!")
    print(f"成功: {len(success_list)} 个文件")
    print(f"失败: {len(failed_list)} 个文件")
    
    return {"success": success_list, "failed": failed_list}



batch_rename_videos(
    directory="data/01_videos",
    mode="random",
    prefix="train",
    suffix="",
    old_text="",
    new_text="",
    custom_format="",
    start_index=1,
    padding=3,
    preview=False,
    file_extensions=[".mp4"]
)