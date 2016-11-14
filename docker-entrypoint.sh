#!/usr/bin/env sh

# Options can be set using environment variables:
# MARATHON_ACME_ACME:     --acme
# MARATHON_ACME_MARATHON: --marathon
# MARATHON_ACME_LBS:      --lb
# MARATHON_ACME_GROUP:    --group

# The following options are hard-coded:
# --listen:    0.0.0.0:8000
# storage-dir: /var/lib/marathon-acme

exec marathon-acme \
  ${MARATHON_ACME_ACME:+--acme "$MARATHON_ACME_ACME"} \
  ${MARATHON_ACME_MARATHON:+--marathon "$MARATHON_ACME_MARATHON"} \
  ${MARATHON_ACME_LBS:+--lb $MARATHON_ACME_LBS} \
  ${MARATHON_ACME_GROUP:+--group "$MARATHON_ACME_GROUP"} \
  ${MARATHON_ACME_LOG_LEVEL:+--log-level "$MARATHON_ACME_LOG_LEVEL"} \
  --listen 0.0.0.0:8000 \
  /var/lib/marathon-acme \
  "$@"
