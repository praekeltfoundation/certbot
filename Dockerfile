# NOTE: This is a development Dockerfile for testing unreleased versions of
# marathon-acme
FROM praekeltfoundation/python3-base:alpine
MAINTAINER Praekelt.org <sre@praekelt.org>

# Copy in the source and install
COPY marathon_acme /marathon-acme/marathon_acme
COPY setup.py LICENSE /marathon-acme/
RUN pip install -e /marathon-acme/.

# Set up the entrypoint script
COPY docker-entrypoint.sh /scripts/marathon-acme-entrypoint.sh
CMD ["marathon-acme-entrypoint.sh"]

# Listening port and storage directory volume
EXPOSE 8000
VOLUME /var/lib/marathon-acme
WORKDIR /var/lib/marathon-acme
