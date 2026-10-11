# Candidate base resolved from the public registry on 2026-10-11.
# This recipe becomes a verified environment only after build + GPU self-test.
FROM pytorch/pytorch@sha256:417bd75df6365104c283ea4c1651fb3530d9eb5a4c2fafa51943cff2a94e6385
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN conda create --name conda_env --clone base --offline -y \
    && /opt/conda/envs/conda_env/bin/python -m pip uninstall -y torchvision torchaudio
COPY requirements-gpu.txt /opt/b2-tools/requirements-gpu.txt
RUN /opt/conda/envs/conda_env/bin/python -m pip install --no-cache-dir -r /opt/b2-tools/requirements-gpu.txt \
    && /opt/conda/envs/conda_env/bin/python -m pip check
COPY tools/ /opt/b2-tools/
COPY participant/ /root/participant/
ENV B2_OFFICIAL_MODEL_CONFIG=/root/participant/weights/inference_config.base.json \
    PYTHONPATH=/root/participant/src \
    HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN /opt/conda/envs/conda_env/bin/python /opt/b2-tools/prepare_bundle.py verify /root/participant \
    && mkdir -p /opt/b2-evidence \
    && /opt/conda/envs/conda_env/bin/python -m pip freeze > /opt/b2-evidence/requirements.actual.txt \
    && conda list --name conda_env --explicit > /opt/b2-evidence/conda.actual.txt
WORKDIR /root/participant
ENTRYPOINT ["bash", "/root/participant/start.sh"]
