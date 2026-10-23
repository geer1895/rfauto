# rfauto 容器镜像
#
# 真构建通道：GitHub Actions "docker-build" job（.github/workflows/ci.yml）
# 每次 push/PR 用本文件真构建镜像，并在容器内冒烟（import / __version__ /
# 默认入口 rfauto --help，退出码 0 即通过）。
# 本机复验（需本机有 docker）：
#   docker build -t rfauto:local .
#   docker run --rm rfauto:local        # 入口冒烟：CMD 跑 rfauto --help
FROM python:3.12-slim

LABEL org.opencontainers.image.title="rfauto" \
      org.opencontainers.image.description="Automated RF/microwave simulation and tuning across HFSS, ADS, openEMS and more" \
      org.opencontainers.image.licenses="GPL-3.0-only"

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
