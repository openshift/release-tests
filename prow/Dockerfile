FROM python:3.12
LABEL maintainer="rioliu@redhat.com"

# Install uv (fast Python package installer)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /usr/src/release-tests

# Install cffi dependency
RUN uv pip install --system cffi

# Copy and install prow package
COPY prow ./prow
RUN uv pip install --system ./prow && \
    job --help && \
    jobctl --help
