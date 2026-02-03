#!/bin/bash
# Script to configure and check Redis SLOWLOG

echo "=========================================="
echo "Redis SLOWLOG Configuration & Analysis"
echo "=========================================="
echo ""

# Configure slowlog to capture all commands (0 microseconds threshold)
echo "Configuring SLOWLOG..."
redis-cli -h 172.17.0.1 CONFIG SET slowlog-log-slower-than 0
redis-cli -h 172.17.0.1 CONFIG SET slowlog-max-len 1000

echo "✓ SLOWLOG configured to capture all commands (max 1000 entries)"
echo ""

# Show current stats
echo "Current Redis stats:"
redis-cli -h 172.17.0.1 INFO stats | grep -E "total_commands_processed|instantaneous_ops_per_sec"
echo ""

echo "Current connections:"
redis-cli -h 172.17.0.1 INFO clients | grep connected_clients
echo ""

echo "=========================================="
echo "Run your load test, then use these commands:"
echo "=========================================="
echo ""
echo "# View slowlog summary:"
echo "redis-cli -h 172.17.0.1 SLOWLOG GET 100"
echo ""
echo "# Analyze slowlog (after load test):"
echo "./analyze_slowlog.sh"
echo ""
