FROM qdrant/qdrant:v1.19.2
# Keep the official binary/SBOM and apply available OS security patches.
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
