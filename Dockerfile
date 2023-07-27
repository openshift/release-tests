FROM python:3.10
LABEL maintainer="jiazha@redhat.com"
WORKDIR /usr/src/release-tests
COPY . .
RUN pip3 install -e .
ENTRYPOINT ["oar"]
