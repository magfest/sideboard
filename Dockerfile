FROM python:3.10-slim-bullseye AS builder
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.sideboard ="1.1"
EXPOSE 8282
WORKDIR /app/sideboard

# libcap-dev and gcc is required for python-prctl (for viewing names of python threads in system tools like htop)
# TODO: need to install npm and nodejs for building static js / gradle stuff

RUN apt-get update \
    && apt-get install -y  \
    libcap-dev gcc \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install virtualenv \
    && virtualenv --always-copy /app/env/ \
    && /app/env/bin/pip3 install paver

# use for production configs. no volume mounting of code/etc
FROM builder as production
COPY . /app/sideboard/

RUN cd /app/sideboard/ &&  \
    /app/env/bin/paver install_deps --env_path=/app/env/

CMD /bin/bash /app/sideboard/run_server.sh

FROM builder as dev

# use for dev builds. developers: you should mount your local sideboard/ directory (with plugins/etc) in /app/sideboard/
# then, the startup command will run the paver dependency installations on container startup (instead of image build)

CMD /bin/bash /app/sideboard/run_dev_server.sh