#!/bin/sh
set -eu
cat > /tmp/sentinel.conf <<CONF
port 26379
sentinel resolve-hostnames yes
sentinel announce-hostnames yes
sentinel monitor mymaster redis-primary 6379 2
sentinel down-after-milliseconds mymaster 2000
sentinel failover-timeout mymaster 10000
CONF
exec redis-sentinel /tmp/sentinel.conf
