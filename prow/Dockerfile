#FROM registry.access.redhat.com/ubi8/python-39
FROM python:3.10
LABEL maintainer="jiazha@redhat.com"
WORKDIR /usr/src/release-tests
COPY . .
RUN pip3 install --upgrade pip && pip3 install cffi
RUN pip3 install -e ./prow
ENTRYPOINT ["job"]
