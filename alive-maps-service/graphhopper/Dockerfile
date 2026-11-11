# GraphHopper из официального релизного jar — без «магических» образов:
# видно, какая версия и какой конфиг запускаются.
FROM eclipse-temurin:21-jre

ARG GH_VERSION=11.1
ENV GH_VERSION=${GH_VERSION}

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /app \
 && curl -fsSL -o /app/graphhopper.jar \
    "https://github.com/graphhopper/graphhopper/releases/download/${GH_VERSION}/graphhopper-web-${GH_VERSION}.jar"

WORKDIR /app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8989
ENTRYPOINT ["/app/entrypoint.sh"]
# аргументы командной строки подхватываются из docker-compose: server /app/config.yml
CMD ["server", "/app/config.yml"]
