FROM ubi9/ubi
LABEL maintainer="rioliu@redhat.com"
# declare variables
ENV PY_VER 3.11
ENV PY_BIN python${PY_VER}
ENV PIP_BIN pip${PY_VER}
# install required packages
RUN yum install -y ${PY_BIN} ${PY_BIN}-devel ${PY_BIN}-pip krb5* git gcc && ${PY_BIN} -m pip install --upgrade pip && ${PIP_BIN} install python-bugzilla pip-system-certs
# Install OAR CLI
WORKDIR /usr/src/release-tests
COPY . .
RUN ${PIP_BIN} install --ignore-installed -e .
CMD [ "/bin/bash" ]