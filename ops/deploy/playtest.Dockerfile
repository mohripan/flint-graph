# The Godot player compiled for the browser, which the Studio shows in a frame on its own address, so
# that what a story does cannot reach the signed-in site. It holds no secrets and calls no API: the
# Studio sends each revision to it as a message. PLAYTEST_PARENT_ORIGIN is the one site that may embed it,
# and it is written into the files at build time, so changing it means a new image.
FROM python@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build

ARG PLAYTEST_PARENT_ORIGIN
RUN test -n "$PLAYTEST_PARENT_ORIGIN"
RUN apt-get update && apt-get install -y --no-install-recommends libfontconfig1 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY runtimes/godot runtimes/godot
COPY ops/narrative/toolchain-linux.json ops/narrative/toolchain-linux.json
COPY ops/deploy/playtest_toolchain.py ops/deploy/playtest.nginx.conf ops/deploy/
COPY tools/narrative/build_preview.py tools/narrative/build_preview.py
RUN python ops/deploy/playtest_toolchain.py runtimes/godot/toolchain.json ops/narrative/toolchain-linux.json /toolchain
RUN python tools/narrative/build_preview.py \
        --engine /toolchain/engine/Godot_v4.7.2-stable_linux.x86_64 \
        --templates /toolchain/templates \
        --parent-origin "$PLAYTEST_PARENT_ORIGIN" \
        --output /out
# Smaller downloads, compressed once here rather than on a small server for every visitor.
RUN find /out/web -type f \( -name '*.wasm' -o -name '*.pck' -o -name '*.js' -o -name '*.html' -o -name '*.css' \) \
        -exec gzip -9 -k {} +
RUN sed "s#__PARENT_ORIGIN__#$PLAYTEST_PARENT_ORIGIN#" ops/deploy/playtest.nginx.conf > /out/default.conf

FROM nginx:1.29.3-alpine@sha256:b3c656d55d7ad751196f21b7fd2e8d4da9cb430e32f646adcf92441b72f82b14

COPY --from=build /out/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /out/web /usr/share/nginx/html
