#!/bin/sh
# Fix data-volume ownership, then run the app as an unprivileged user.
#
# The volume carries the DuckDB file, the encrypted WHOOP token, the auth
# database and the logs. A volume created by an earlier root-running image
# stays root-owned, so simply switching the image to USER would leave the app
# unable to write to its own data -- surfacing as a permission error on the
# first login rather than at startup. Fixing ownership here handles both a
# fresh volume and one that predates the change.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    chown -R thaalam:thaalam "$DATA_DIR"
    # exec so the app becomes PID 1 and receives stop signals directly.
    exec gosu thaalam "$@"
fi

# Already unprivileged (a host may pin the user); nothing to drop.
exec "$@"
