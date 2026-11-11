# Маленький «инструментальный» образ для одноразовых шагов подготовки данных:
# скачать PBF, собрать зоны, скачать шрифты. Запускается через
#   docker compose --profile build run --rm tools ...
# Постоянно работать он не должен — это именно мастерская.
FROM python:3.12-slim

# libexpat/bz2/lzma нужны pyosmium в рантайме: без libexpat он падает с
# "libexpat.so.1: cannot open shared object file: No such file or directory"
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
      libexpat1 libbz2-1.0 zlib1g liblzma5 \
 && rm -rf /var/lib/apt/lists/*

# pyosmium читает OSM, shapely считает буферы и объединяет зоны
RUN pip install --no-cache-dir osmium==4.0.0 shapely==2.0.6

WORKDIR /scripts
CMD ["sh", "-c", "echo 'это мастерская: ./start.sh или make data zones fonts'"]
