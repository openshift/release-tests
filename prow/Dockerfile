FROM python:3.12
LABEL maintainer="rioliu@redhat.com"
WORKDIR /usr/src/release-tests
COPY . .
RUN pip3 install --upgrade pip && pip3 install cffi
RUN pip3 install -e ./prow
