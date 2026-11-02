# rfauto 容器镜像（G7，2026-09-18；2026-10-23 保鲜核对）
#
# 如实口径：本机无 docker CLI/守护，本地只做过【静态校验】（指令合法性、
# COPY 源存在性、JSON 数组形式 CMD 解析、基镜像与 requires-python 相容性
# ——校验脚本 runs/dockerfile_static_check.py）。真构建由公开仓同款文件的
# CI 通道背书：release/rfauto_public/.github/workflows/ci.yml "docker-build"
# job 每次 push/PR 真构建+容器冒烟（import/版本/CLI --help）。
# 本机拿到 docker 环境后复验：
#   docker build -t rfauto:local .
#   docker run --rm rfauto:local        # 入口冒烟：CMD 跑 rfauto --help
FROM python:3.12-slim

LABEL org.opencontainers.image.title="rfauto" \
      org.opencontainers.image.description="HFSS/ADS automated simulation tuning framework" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /app

# 打包元数据与源码；不 COPY 运行数据/本地环境（.dockerignore 已排除 runs/、
# .venv/、knowledge/ 等大目录，构建上下文只含安装所需最小集）
COPY pyproject.toml README.md ./
COPY src ./src

# 容器内常规安装（非 editable）；只装 pyproject 声明的核心依赖，
# EDA SDK（HFSS/ADS/openEMS/COMSOL 等）全部留在 extras，不进镜像
RUN pip install --no-cache-dir .

# 入口冒烟：容器默认跑 CLI --help，退出码 0 即镜像可启动、console script 就位
CMD ["rfauto", "--help"]
