FROM python:3.13-slim
LABEL org.opencontainers.image.title="MCP SAP GUI protocol/discovery image" \
      org.opencontainers.image.description="Discovery and protocol checks only; SAP GUI operations require a native Windows desktop"
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home mcp
USER mcp
ENTRYPOINT ["mcp-sap-gui"]
