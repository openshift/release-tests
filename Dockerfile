FROM python:3.11
LABEL maintainer="jiazha@redhat.com"
WORKDIR /usr/src/release-tests
COPY . .
RUN pip3 install --ignore-installed -e .
ENTRYPOINT ["oar"]
