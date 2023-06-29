FROM ubuntu:focal

LABEL name="tdf2mzml"
LABEL version="0.1"
LABEL sdk_version="2.8.7"
LABEL author="Michael A. Freitas"
LABEL maintainer="mike.freitas@gmail.com"
LABEL dockerhub="mfreitas/tdf2mzml"

ENV LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/tdf2mzml

ADD pyproject.toml /tdf2mzml/pyproject.toml
ADD tdf2mzml /tdf2mzml/tdf2mzml

RUN apt-get update && apt-get install python3-pip procps -y \
    && rm -rf /var/lib/apt/lists/* \
    && pip3 install tdf2mzml/

ENTRYPOINT [ "tdf2mzml" ]







