FROM python:3.6
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.sideboard ="1.0"
WORKDIR /app

# required for python-prctl
RUN apt-get update && apt-get install -y libcap-dev && rm -rf /var/lib/apt/lists/*

ADD . /app/
RUN pip3 install virtualenv \
  && virtualenv --always-copy /app/env \
	&& /app/env/bin/pip3 install paver
RUN /app/env/bin/paver install_deps

CMD /app/env/bin/python3 /app/sideboard/run_server.py
EXPOSE 8282
