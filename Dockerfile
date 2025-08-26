FROM ubi9/ubi
LABEL maintainer="rioliu@redhat.com"

# declare variables
ENV PY_VER 3.12
ENV PY_BIN python${PY_VER}
ENV PIP_BIN pip${PY_VER}

# Install required packages
RUN yum update -y && \
    yum install -y ${PY_BIN} ${PY_BIN}-devel ${PY_BIN}-pip krb5* git gcc tar gzip && \
    ${PY_BIN} -m pip install --upgrade pip && \
    ${PIP_BIN} install python-bugzilla pip-system-certs

# Use the built-in TARGETARCH variable
ARG TARGETARCH

# Determine the correct file name based on architecture
RUN case ${TARGETARCH} in \
        amd64) FILE_NAME="openshift-client-linux.tar.gz" ;; \
        arm64) FILE_NAME="openshift-client-linux-arm64.tar.gz" ;; \
        *) echo "Unsupported architecture: ${TARGETARCH}"; exit 1 ;; \
    esac && \
    curl -LO "https://mirror.openshift.com/pub/openshift-v4/clients/ocp/latest/${FILE_NAME}" && \
    tar -xzf ${FILE_NAME} && \
    chmod +x oc && \
    mv oc /usr/local/bin/ && \
    rm ${FILE_NAME} && \
    oc version

# Install OAR CLI
WORKDIR /usr/src/release-tests
COPY . .
RUN ${PIP_BIN} install --ignore-installed -e .

CMD [ "/bin/bash" ]
