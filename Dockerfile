FROM python:3.12.3-slim as build
WORKDIR /app
ENV PYTHONPATH=/app:/app/plugins/*/

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