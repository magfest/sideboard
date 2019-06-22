FROM python:3.4.5
MAINTAINER RAMS Project "code@magfest.org"
LABEL version.sideboard ="1.0"
WORKDIR /app

# This is actually the least bad way to compose two Dockerfile tech stacks right now.
# The following is copied and pasted from the Node Dockerfile at
# https://github.com/nodejs/docker-node/blob/28425ed95cebaea2ff589c1516d79c60181983b2/7.4/Dockerfile
# Update this comment and change the entire copypasta section to upgrade Node version

#########################################
# START NODEJS DOCKERFILE COPYPASTA     #
# https://github.com/nodejs/docker-node #
#########################################
RUN groupadd --gid 1000 node \
  && useradd --uid 1000 --gid node --shell /bin/bash --create-home node

# gpg keys listed at https://github.com/nodejs/node#release-team
RUN set -ex \
  && for key in \
4ED778F539E3634C779C87C6D7062848A1AB005C \
B9E2F5981AA6E0CD28160D9FF13993A75599653C \
94AE36675C464D64BAFA68DD7434390BDBE9B9C5 \
B9AE9905FFD7803F25714661B63B535A4C206CA9 \
77984A986EBC2AA786BC0F66B01FBB92821C587A \
71DCFD284A79C3B38668286BC97EC7A07EDE3FC1 \
FD3A5288F042B6850C66B31F09FE44734EB7990E \
8FCCA13FEF1D0C2E91008E09770F7A9A5AE15600 \
C4F0DFFF4E8C1A8236409D08E73BC641CC11F4C8 \
DD8F2338BAE7501E3DD5AC78C273792F7D83545D \
A48C2BEE680E841632CD4E44F07496B3EB3C1762 \
  ; do \
    gpg --keyserver pool.sks-keyservers.net --recv-keys DD8F2338BAE7501E3DD5AC78C273792F7D83545D || \
    gpg --keyserver pgp.mit.edu --recv-keys "$key" || \
    gpg --keyserver keyserver.pgp.com --recv-keys "$key" ; \
  done

ENV NPM_CONFIG_LOGLEVEL info
ENV NODE_VERSION 7.10.0

RUN curl -SLO "https://nodejs.org/dist/v$NODE_VERSION/node-v$NODE_VERSION-linux-x64.tar.xz" \
  && curl -SLO "https://nodejs.org/dist/v$NODE_VERSION/SHASUMS256.txt.asc" \
  && gpg --batch --decrypt --output SHASUMS256.txt SHASUMS256.txt.asc \
  && grep " node-v$NODE_VERSION-linux-x64.tar.xz\$" SHASUMS256.txt | sha256sum -c - \
  && tar -xJf "node-v$NODE_VERSION-linux-x64.tar.xz" -C /usr/local --strip-components=1 \
  && rm "node-v$NODE_VERSION-linux-x64.tar.xz" SHASUMS256.txt.asc SHASUMS256.txt \
  && ln -s /usr/local/bin/node /usr/local/bin/nodejs
###################################
# END NODEJS DOCKERFILE COPYPASTA #
###################################

# required for python-prctl
RUN apt-get update && apt-get install -y libcap-dev && rm -rf /var/lib/apt/lists/*

ADD . /app/
RUN pip3 install virtualenv \
  && virtualenv --always-copy /app/env \
	&& /app/env/bin/pip3 install paver
RUN /app/env/bin/paver install_deps

CMD /app/env/bin/python3 /app/sideboard/run_server.py
EXPOSE 8282
