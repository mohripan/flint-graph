FROM python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

# Operator preparation only; application jobs never install or fetch dependencies.
# Final image ID binds the actually resolved distribution packages as well.
RUN apt-get update && apt-get install -y --no-install-recommends libfontconfig1 && rm -rf /var/lib/apt/lists/*
COPY --chmod=0555 godot /opt/godot
COPY --chmod=0444 web_nothreads_debug.zip web_nothreads_release.zip /opt/templates/
RUN chmod 0555 /opt/templates
COPY --chmod=0444 build_child.py runtime-files.json /opt/

ARG TOOLCHAIN_SHA256
LABEL io.flintgraph.narrative.toolchain.sha256=$TOOLCHAIN_SHA256
ENV HOME=/scratch/home XDG_CONFIG_HOME=/scratch/home/config XDG_DATA_HOME=/scratch/home/data XDG_CACHE_HOME=/scratch/home/cache TMPDIR=/scratch/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 10001:10001
ENTRYPOINT ["python", "/opt/build_child.py"]
