FROM registry.access.redhat.com/ubi9/ubi
LABEL maintainer="rioliu@redhat.com"

# Declare variables
ENV PY_VER=3.12
ENV PY_BIN=python${PY_VER}

# Install Python and required system packages
RUN yum --disableplugin=subscription-manager install -y --allowerasing \
        ${PY_BIN} \
        ${PY_BIN}-devel \
        krb5* \
        git \
        gcc \
        tar \
        gzip \
        curl && \
    yum clean all

# Install uv (fast Python package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install system-wide Python packages not in pyproject.toml
RUN uv pip install --python ${PY_BIN} --system python-bugzilla pip-system-certs

# Install OpenShift CLI (oc) based on architecture
ARG TARGETARCH
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
    oc version --client

# Install OAR CLI
WORKDIR /usr/src/release-tests
COPY . .
RUN uv pip install --python ${PY_BIN} --system . && \
    oar --help && \
    oarctl --help

# Install RH IT Root Certificate
RUN curl -fsSLo /etc/pki/ca-trust/source/anchors/Current-IT-Root-CAs.pem https://certs.corp.redhat.com/certs/Current-IT-Root-CAs.pem && \
    update-ca-trust extract

CMD [ "/bin/bash" ]
