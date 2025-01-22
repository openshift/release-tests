#FROM registry.access.redhat.com/ubi8/python-39
FROM python:3.12-alpine
LABEL maintainer="rioliu@redhat.com"
RUN apk update && apk add --no-cache bash
WORKDIR /usr/src/release-tests
COPY . .
RUN pip3 install --upgrade pip && pip3 install cffi
RUN pip3 install -e ./prow
