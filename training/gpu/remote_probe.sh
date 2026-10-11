set +e
echo "=== 身份 ==="
whoami; hostname; uname -r
echo
echo "=== GPU 设备节点 ==="
ls -l /dev/nvidia* 2>&1
echo
echo "=== nvidia-smi ==="
nvidia-smi 2>&1 | head -20
echo
echo "=== nvidia-smi -L ==="
nvidia-smi -L 2>&1 | head
echo
echo "=== /proc/driver/nvidia/version ==="
cat /proc/driver/nvidia/version 2>&1 | head -3
echo
echo "=== 驱动库 ==="
ls /usr/lib/x86_64-linux-gnu/libnvidia-ml.so* 2>&1 | head
ls /usr/lib64/libnvidia-ml.so* 2>&1 | head
echo
echo "=== conda 环境 ==="
conda env list 2>&1
echo "CONDA_DEFAULT_ENV=[$CONDA_DEFAULT_ENV]"
for env in /opt/conda /opt/conda/envs/conda_env; do
  if [ -x "$env/bin/python" ]; then
    echo "--- $env ---"
    "$env/bin/python" -V 2>&1
    "$env/bin/python" - <<'PYEOF' 2>&1 | tail -8
try:
    import torch
    print("torch", torch.__version__)
    print("cuda_available", torch.cuda.is_available())
    print("device_count", torch.cuda.device_count())
    print("cuda_version", torch.version.cuda)
    if torch.cuda.is_available():
        print("device_name", torch.cuda.get_device_name(0))
except Exception as exc:
    print("torch 探测失败:", type(exc).__name__, exc)
PYEOF
    "$env/bin/pip" list 2>/dev/null | grep -Ei "^(torch|transformers|peft|accelerate|datasets|trl|vllm|bitsandbytes|safetensors|tokenizers|numpy|sentencepiece) "
  fi
done
echo
echo "=== 磁盘 ==="
df -h / /root /tmp /mnt/storage 2>&1
echo
echo "=== CPU / 内存 ==="
nproc; free -g 2>/dev/null | head -3
echo
echo "=== /mnt/storage ==="
ls -la /mnt/storage 2>&1 | head -20
echo
echo "=== /root ==="
ls -la /root 2>&1 | head -20
echo
echo "=== 官方数据是否已在容器 ==="
find / -maxdepth 5 \( -name 'train_public.jsonl' -o -name 'val_public.jsonl' \) 2>/dev/null | head
echo
echo "=== nvcc ==="
which nvcc 2>&1; nvcc --version 2>&1 | tail -2
echo
echo "=== 联网情况（决定能否自己装包/取数据） ==="
timeout 10 curl -sS -o /dev/null -w "pypi:%{http_code}\n" https://pypi.org/simple/ 2>&1
timeout 10 curl -sS -o /dev/null -w "huggingface:%{http_code}\n" https://huggingface.co 2>&1
timeout 10 curl -sS -o /dev/null -w "github:%{http_code}\n" https://github.com 2>&1
echo "DONE"