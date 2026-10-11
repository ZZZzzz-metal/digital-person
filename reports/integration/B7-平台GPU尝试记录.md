# AI队：平台 GPU 尝试记录（固定来源摘录）

来源：A 提交 f2c1fbd5638ef58f3f23130dc6dad4831814d126，reports/model/gpu-evidence/gpu-revocation-evidence.txt；Git blob SHA1 9e55a3666f17dc2f87a4bebc8c12effcc3a3f200。本件由 B 从已公开的固定版本逐行摘录，只去掉与故障现象无关的账号、连接地址、实例/设备私有标识。下列行号对应源文件，不是 B 本轮重跑。B 没有重新登录该 A 实例或完成 GPU 训练。

```text
原记录第17行：2026-10-11 05:37:42 UTC  root open("/dev/nvidiactl") = OK; torch.cuda.is_available()=True; device_count=1
原记录第18行：2026-10-11 05:37:42 UTC  CUDA 2048x2048 fp32 matmul PASS: sum=-35980.6171875, 45.97 ms, sm_89, 23.52 GB
原记录第21行：2026-10-11 05:43:55 UTC  nvidia-smi 变为 "Failed to initialize NVML: Unknown Error"
原记录第22行：2026-10-11 05:43:55 UTC  root open("/dev/nvidiactl") = PermissionError [Errno 1] Operation not permitted
原记录第23行：2026-10-11 05:43-05:45   连续 6 次重试（每 15 秒），torch.cuda.is_available() 恒为 False、device_count 恒为 0
原记录第27行：Failed to initialize NVML: Unknown Error
原记录第36行：OPEN FAIL /dev/nvidiactl PermissionError PermissionError(1, 'Operation not permitted')
原记录第37行：OPEN FAIL /dev/nvidia5 PermissionError PermissionError(1, 'Operation not permitted')
原记录第38行：OPEN FAIL /dev/nvidia-uvm PermissionError PermissionError(1, 'Operation not permitted')
原记录第39行：OPEN FAIL /dev/nvidia-uvm-tools PermissionError PermissionError(1, 'Operation not permitted')
原记录第51行：cuda.device_count() : 0
```

A 原记录表明 2026-10-11 UTC05:37:42 已完成一次真实 CUDA 计算；之后 UTC05:43:55 开始设备打开被拒绝并且CUDA不可用。没有成功的 GPU 训练模型产物。具体平台调度/驱动/权限根因需要平台确认，本件不从现象推断计费余额，也不将零优化器更新写成零实例扣券。

CPU 训练过程另见 A4 报告、a4_training_short.json 及原始 steps 日志。B6 镜像 GPU 推理另见 B/evidence，不能将它写成 A 的平台 GPU 训练。本记录与本镜像基础模型版本分开。

