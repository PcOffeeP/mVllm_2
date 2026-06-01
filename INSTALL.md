# mVllm 环境安装指南

> Python 版本：**3.11**（官方 MiniCPM-V CookBook 要求）

---

## 前置：配置镜像源

开始安装前，先执行以下命令加速下载：

```bash
# pip 清华源
pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# conda 清华源
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/free/
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/
conda config --set show_channel_urls yes
```

---

## 方案一：V100S（云服务器）

> **关键限制**：V100S 的 SM 7.0 架构**不支持 Flash Attention 2**。训练 YAML 中 `flash_attn` 保持 `sdpa`。

```bash
# 1. Python 环境
conda create -n mvllm python=3.11 -y
conda activate mvllm

# 2. PyTorch 三件套（CUDA 12.4）
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  -f https://download.pytorch.org/whl/cu124

# 3. CUDA Runtime（V100S 驱动 580+ 缺 libcudart）
conda install -c conda-forge cuda-runtime=13.0 -y

# 4. 核心训练依赖（跳过 flash-attn，V100S 不支持）
pip install transformers==5.7.0 accelerate==1.13.0 peft==0.18.1 trl==0.24.0 \
  wandb ninja einops safetensors tokenizers sentencepiece

# 5. LLaMA-Factory
cd finetune/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt

# 6. 锁定 transformers 版本
pip install transformers==5.7.0

# 7. （可选）模型下载
pip install modelscope
export HF_ENDPOINT=https://hf-mirror.com
python -c "from transformers import AutoModel; AutoModel.from_pretrained('openbmb/MiniCPM-V-4_6', trust_remote_code=True)"
```

---

## 方案二：RTX 4090（本地桌面）

> **优势**：SM 8.9 架构原生支持 Flash Attention 2。安装完成后需修改训练 YAML 启用 `fa2`。

```bash
# 1. Python 环境
conda create -n mvllm python=3.11 -y
conda activate mvllm

# 2. PyTorch 三件套（CUDA 12.1）
pip install torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  -f https://download.pytorch.org/whl/cu121

# 3. 核心训练依赖（含 flash-attn）
pip install transformers==5.7.0 accelerate==1.13.0 peft==0.18.1 trl==0.24.0 \
  wandb ninja einops safetensors tokenizers sentencepiece
MAX_JOBS=32 pip install --no-build-isolation flash-attn==2.8.3

# 4. LLaMA-Factory
cd finetune/
pip install -e ".[metrics]"
pip install -r requirements/minicpm-v.txt

# 5. 锁定 transformers 版本
pip install transformers==5.7.0

# 6. （可选）模型下载
pip install modelscope
export HF_ENDPOINT=https://hf-mirror.com
python -c "from transformers import AutoModel; AutoModel.from_pretrained('openbmb/MiniCPM-V-4_6', trust_remote_code=True)"
```

> ⚠️ **4090 训练前必须修改 YAML**：将各 fold 配置文件中的 `flash_attn: sdpa` 改为 `flash_attn: fa2`，以启用 Flash Attention 2 加速。配置文件位于 `finetune/AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold*.yaml`。

---

## 模型下载（两种方式）

### 方式一：HuggingFace 镜像

```bash
export HF_ENDPOINT=https://hf-mirror.com
python -c "from transformers import AutoModel; AutoModel.from_pretrained('openbmb/MiniCPM-V-4_6', trust_remote_code=True)"
```

### 方式二：ModelScope

```bash
pip install modelscope
modelscope download --model openbmb/MiniCPM-V-4_6
```

---

## 训练启动

```bash
# 确保在 finetune/ 目录下
cd finetune/

# 环境变量
export DOWNSAMPLE_MODE=4x
export DISABLE_VERSION_CHECK=1

# 启动训练（以 Fold 0 为例）
llamafactory-cli train AAA-TS-Video/MiniCPM/config/minicpmv4_6_lora_sft_fold0.yaml
```

三个 fold 可串行执行，也可在不同 GPU 上并行。详细训练说明见 [README.md](./README.md) Phase 3。
