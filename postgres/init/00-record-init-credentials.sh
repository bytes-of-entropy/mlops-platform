#!/bin/sh
# Records which credentials this data directory was initialised with, so a later mismatch can be
# reported before a start rather than diagnosed after one.
#
# This runs exactly once: the entrypoint executes docker-entrypoint-initdb.d only while creating an
# empty data directory, which is the same moment -- and the only moment -- POSTGRES_USER and
# POSTGRES_PASSWORD have any effect. Everything after that reads the role stored here, not the
# variables in the environment, which is why editing .env against a kept volume changes nothing and
# says nothing.
#
# A salted digest rather than the values: this file lives inside a volume this repository invites
# reviewers to keep, and a credential pair readable back out of it would be a worse problem than
# the one being solved. The salt is generated here so it never exists outside the volume.
#
# Kept byte-compatible with preflight.credentials.fingerprint -- same join, same order, no trailing
# newline. A test runs this script and compares the two, because two implementations of one digest
# agree until the day they do not.

salt=$(od -An -tx1 -N16 /dev/urandom | tr -d ' \n')
digest=$(printf '%s' "${salt}:${POSTGRES_USER}:${POSTGRES_PASSWORD}" | sha256sum | cut -d' ' -f1)

if [ -n "${salt}" ] && [ -n "${digest}" ]; then
  printf '%s:%s' "${salt}" "${digest}" >"${PGDATA}/.init-credentials"
  chmod 600 "${PGDATA}/.init-credentials"
fi
