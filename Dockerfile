FROM python:3.12-slim

LABEL name="tdf2mzml"
LABEL version="0.5.0"
LABEL sdk_version="2.8.7"
LABEL author="Michael A. Freitas"
LABEL maintainer="mike.freitas@gmail.com"
LABEL dockerhub="mfreitas/tdf2mzml"

WORKDIR /app

# libbaf2sql_c.so depends on libgomp (OpenMP runtime)
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 procps \
    && rm -rf /var/lib/apt/lists/*

# Copy only what's needed for installation (no test data, no SDK sources)
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir . \
    && rm -rf /app/src /app/pyproject.toml

# Set LD_LIBRARY_PATH to the installed SDK libs location so the Bruker
# shared libraries (libtimsdata.so, libbaf2sql_c.so) can find dependencies.
RUN echo $(python -c "import tdf2mzml; print(tdf2mzml.__file__)" | xargs dirname)/libs > /etc/ld.so.conf.d/tdf2mzml.conf \
    && ldconfig

ENTRYPOINT ["tdf2mzml"]
