# mVllm 已知问题与解决方案

## 一、环境依赖问题（已解决）
### 1.1 Python 版本（3.11 硬要求）
### 1.2 CUDA Runtime 缺失（conda install cuda-runtime=13.0）
### 1.3 torch/torchvision/torchaudio 版本对齐（cu124 索引）
### 1.4 V100S 不支持 flash-attn（SM 7.0 → 用 sdpa）
### 1.5 4090 驱动 535 不支持 torch 2.8.0（需升级到 550+）
### 1.6 torchaudio 单独对齐（torchaudio==2.8.0）
### 1.7 sentencepiece 缺失
### 1.8 DISABLE_VERSION_CHECK=1（transformers 5.7.0 vs LLaMA-Factory 版本检查）
### 1.9 DeepSpeed 在 LoRA 单卡场景不需要
### 1.10 bitsandbytes>=0.39.0（QLoRA 4-bit 量化依赖）

## 二、模型下载问题（已解决）
### 2.1 modelscope download 可能不完整（推荐 huggingface_hub snapshot_download）
### 2.2 HF 国内镜像（hf-mirror.com）
### 2.3 模型目录缺少 processor 代码（删除错误来源的 processing_minicpmv.py）

## 三、数据问题（已解决）
### 3.1 3-fold 划分策略（每 fold 只用自己的 train/val）
### 3.2 dataset_info.json 缺少 role_tag/content_tag（OpenAI 格式）
### 3.3 视频路径解析（media_dir: ../data）
### 3.4 训练/验证集分离（pipeline --split both）

## 四、LLaMA-Factory / mm_plugin.py 兼容性问题
### 4.1 target_sizes 键名不一致（存 target_sizes_videos，读 target_sizes）
- **现象**：TypeError: 'NoneType' object is not subscriptable
- **位置**：_build_v4_6_placeholder (mm_plugin.py:1513)
- **修复**：添加键名回退 + None 空值保护（已合并）
### 4.2 miniCPM-V-4.6 processor 不返回 image_sizes（切到 minicpm_v 模板时）
- **现象**：KeyError: 'image_sizes'
- **结论**：MiniCPMVPlugin 与 4.6 不兼容，必须用 minicpm_v_4_6 模板
### 4.3 processor videos 参数需带 text=''（已修复并还原）
### 4.4 视频处理 if 块嵌套问题（已修复并还原）

## 五、当前未解决问题
### 5.1 pixel_values 高度为 0（14×0），model forward 崩溃
- **现象**：RuntimeError: Calculated padded input size per channel: (14 x 0)
- **位置**：MiniCPM-V-4.6 vision_tower.embeddings.patch_embedding
- **状态**：未解决
- **根因分析**：LLaMA-Factory 0.9.6 的 MiniCPMV4_6Plugin 视频处理链路与 transformers 5.7.0 的 MiniCPM-V-4.6 processor 在 pixel_values 格式上不兼容。processor 返回的 pixel_values 经过 _get_mm_inputs → get_mm_inputs → collator 传递后，形状与模型期望的不一致
- **可能方案**：预抽帧为图片序列，绕过 video processor
