# PR-Guard test sandbox.
#
# Build from the repository root:
#   docker build -t prguard-sandbox:node20 backend/sandbox
#
# The runner overrides the user, root filesystem, network and resource limits at
# container creation. The image itself only needs Node, npm and a writable /workspace
# mount owned by the non-root sandbox user.
FROM node:20-bookworm-slim

RUN groupadd --gid 10001 sandbox \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/sandbox \
       --shell /usr/sbin/nologin sandbox \
    && mkdir -p /workspace \
    && chown sandbox:sandbox /workspace

WORKDIR /workspace
USER 10001:10001

ENV CI=1 \
    HOME=/tmp \
    NPM_CONFIG_CACHE=/tmp/npm \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    NO_COLOR=1

CMD ["node", "--version"]
