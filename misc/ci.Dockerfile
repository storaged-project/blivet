# latest fedora image for running some of our tests in GH actions

FROM registry.fedoraproject.org/fedora:latest

RUN set -e; \
  dnf install -y ansible python3-pip git which dnf-plugins-core; \
  git clone --depth 1 https://github.com/storaged-project/ci.git; \
  git clone --depth 1 https://github.com/storaged-project/blivet-gui.git;

WORKDIR /
