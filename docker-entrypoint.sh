#!/usr/bin/env sh
set -e

# Assume the user wants to run marathon-acme if the first argument...
# * starts with '-', i.e. is a marathon-acme CLI option, or
# * is an existing directory, i.e. is the path to the storage directory
if [ "${1#-}" != "$1" ] || [ -d "$1" ]; then
	set -- marathon-acme "$@"
fi

# If a user has been provided to run as, add the user switch to the command
if [ -n "$MARATHON_ACME_USER" ] && [ "$1" == 'marathon-acme' ]; then
  set -- su-exec "$MARATHON_ACME_USER" "$@"
fi

# No init system -- marathon-acme is a single process
exec "$@"
