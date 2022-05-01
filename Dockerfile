# FROM python:3.9.7-alpine3.14
FROM ubuntu:20.04

# copy requirements file
ADD requirements.txt /app/requirements.txt

ENV TZ=Europe/London
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN set -ex \
    && apt-get update \
    && apt-get install -y libpq-dev gcc build-essential python3.9-dev python3.9 python3.9-venv \
    && python3.9 -m venv /env \
    && /env/bin/pip install --upgrade pip \
    && /env/bin/pip install --no-cache-dir -r /app/requirements.txt
#    && runDeps="$(scanelf --needed --nobanner --recursive /env \
#        | awk '{ gsub(/,/, "\nso:", $2); print "so:" $2 }' \
#        | sort -u \
#        | xargs -r apk info --installed \
#        | sort -u)" \
#    && apt-get install rundeps $runDeps \
#    && apk del .build-deps \
#    && rm -rf /root/.cache

ADD . /app
WORKDIR /app/solbolt

# RUN useradd -rm -d /home/ubuntu -s /bin/bash -g nogroup -G sudo -u 1001 nouser

# RUN chown nouser:nogroup "celerybeat-schedule.db"

RUN useradd -ms /bin/bash appuser
RUN chown -R appuser:appuser /app

USER appuser

ENV VIRTUAL_ENV /env
ENV PATH /env/bin:$PATH

EXPOSE 5000