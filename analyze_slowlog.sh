#!/bin/bash
# Analyze Redis SLOWLOG after load test

echo "=========================================="
echo "Redis SLOWLOG Analysis"
echo "=========================================="
echo ""

# Get slowlog entries
SLOWLOG_OUTPUT=$(redis-cli -h 172.17.0.1 SLOWLOG GET 1000)

# Count SET and RPUSH operations
SET_COUNT=$(echo "$SLOWLOG_OUTPUT" | grep -c '"SET"')
RPUSH_COUNT=$(echo "$SLOWLOG_OUTPUT" | grep -c '"RPUSH"')

echo "Operation Counts:"
echo "  SET operations:   $SET_COUNT"
echo "  RPUSH operations: $RPUSH_COUNT"
echo ""

# Extract execution times (in microseconds) and convert to milliseconds
echo "Analyzing execution times..."
redis-cli -h 172.17.0.1 SLOWLOG GET 1000 | \
  awk '/1) "SET"/{getline; getline; print $1/1000}' | \
  awk '{
    sum += $1
    if (NR == 1 || $1 < min) min = $1
    if ($1 > max) max = $1
    values[NR] = $1
    count++
  }
  END {
    if (count > 0) {
      avg = sum/count
      print ""
      print "SET Operations (Redis server-side timing):"
      print "  Count:    " count
      print "  Average:  " avg " ms"
      print "  Min:      " min " ms"
      print "  Max:      " max " ms"
    }
  }'

redis-cli -h 172.17.0.1 SLOWLOG GET 1000 | \
  awk '/1) "RPUSH"/{getline; getline; print $1/1000}' | \
  awk '{
    sum += $1
    if (NR == 1 || $1 < min) min = $1
    if ($1 > max) max = $1
    values[NR] = $1
    count++
  }
  END {
    if (count > 0) {
      avg = sum/count
      print ""
      print "RPUSH Operations (Redis server-side timing):"
      print "  Count:    " count
      print "  Average:  " avg " ms"
      print "  Min:      " min " ms"
      print "  Max:      " max " ms"
    }
  }'

echo ""
echo "=========================================="
echo ""
echo "Compare these timings with your application logs:"
echo "  - If SLOWLOG times are LOW (<1ms) but app times are HIGH (>70ms):"
echo "    → Bottleneck is NETWORK/CONNECTION POOL"
echo ""
echo "  - If SLOWLOG times are HIGH (>50ms):"
echo "    → Bottleneck is REDIS itself (unlikely)"
echo ""
