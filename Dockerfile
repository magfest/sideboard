FROM python:3.12.3-slim as build
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.sideboard ="1.0"
WORKDIR /app

ADD requirements.txt requirements.txt
RUN --mount=type=cache,target=/root/.cache \
    pip install -r requirements.txt

FROM build as test
ADD test_requirements.txt test_requirements.txt
RUN --mount=type=cache,target=/root/.cache \
    pip install -r test_requirements.txt
CMD python -m pytest
ADD . /app/

FROM build as release
CMD python /app/sideboard/run_server.py
EXPOSE 80
ADD . /app/