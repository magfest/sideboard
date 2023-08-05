FROM python:3.11.4 as build
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.sideboard ="1.0"
WORKDIR /app

# required for python-prctl
RUN apt-get update && apt-get install -y libcap-dev && rm -rf /var/lib/apt/lists/*

RUN pip3 install virtualenv \
  && virtualenv --always-copy /app/env \
	&& /app/env/bin/pip3 install paver

ADD requirements.txt requirements.txt
ADD test_requirements.txt test_requirements.txt
ADD setup.py setup.py
ADD sideboard/_version.py sideboard/_version.py
ADD pavement.py pavement.py

RUN /app/env/bin/paver install_deps
ADD . /app/

FROM python:3.11.4-slim as test
WORKDIR /app
COPY --from=build /app /app
RUN /app/env/bin/pip install mock pytest
CMD /app/env/bin/python3 -m pytest

FROM python:3.11.4-slim as release
WORKDIR /app
COPY --from=build /app /app
CMD /app/env/bin/python3 /app/sideboard/run_server.py
EXPOSE 8282