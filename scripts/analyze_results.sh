#!/bin/bash
# Analysis script - calculates detailed performance statistics

set -e

if [ -z "$1" ]; then
    echo "Usage: ./scripts/analyze_results.sh <test_results_directory>"
    exit 1
fi

RESULTS_DIR="$1"
LOG_FILE="$RESULTS_DIR/shorten.log"
REPORT_FILE="$RESULTS_DIR/analysis_report.md"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=========================================="
echo "Performance Analysis"
echo "=========================================="
echo ""
echo "Analyzing: $LOG_FILE"
echo "Report: $REPORT_FILE"
echo ""

# Start report
cat > "$REPORT_FILE" << 'EOF'
# Redis Performance Test Results

## Test Configuration
EOF

echo "- Test Directory: \`$RESULTS_DIR\`" >> "$REPORT_FILE"
echo "- Timestamp: $(date)" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Analyze request timing
echo -e "${YELLOW}Analyzing request timing...${NC}"
echo "## Overall Request Performance" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"

grep "⏱️  REQUEST TIMING | POST /v1/shorten" "$LOG_FILE" | \
sed 's/.*total=\([0-9.]*\)ms.*handler=\([0-9.]*\)ms.*/\1 \2/' | \
awk '{
  total += $1;
  handler += $2;
  middleware += ($1 - $2);
  count++;

  if (NR == 1 || $1 < min_total) min_total = $1;
  if ($1 > max_total) max_total = $1;
}
END {
  avg_total = total/count;
  avg_handler = handler/count;
  avg_middleware = middleware/count;

  print "Request Count:      " count;
  print "";
  print "Total Time:";
  print "  Average:          " avg_total " ms";
  print "  Min:              " min_total " ms";
  print "  Max:              " max_total " ms";
  print "";
  print "Handler Time:";
  print "  Average:          " avg_handler " ms";
  print "  Percentage:       " (avg_handler/avg_total)*100 "%";
  print "";
  print "Middleware Time:";
  print "  Average:          " avg_middleware " ms";
  print "  Percentage:       " (avg_middleware/avg_total)*100 "%";
}' >> "$REPORT_FILE"

echo "\`\`\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo -e "${GREEN}✓ Request timing analyzed${NC}"

# Analyze Redis SET operations
echo -e "${YELLOW}Analyzing Redis SET operations...${NC}"
echo "## Redis SET Performance" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"

grep "redis_set=" "$LOG_FILE" | \
sed 's/.*serialize=\([0-9.]*\)ms.*redis_set=\([0-9.]*\)ms.*/\1 \2/' | \
awk '{
  serialize += $1;
  redis_set += $2;
  count++;

  if (NR == 1 || $2 < min_redis) min_redis = $2;
  if ($2 > max_redis) max_redis = $2;
}
END {
  avg_serialize = serialize/count;
  avg_redis = redis_set/count;

  print "Operation Count:    " count;
  print "";
  print "Serialization:";
  print "  Average:          " avg_serialize " ms";
  print "";
  print "Redis SET:";
  print "  Average:          " avg_redis " ms";
  print "  Min:              " min_redis " ms";
  print "  Max:              " max_redis " ms";
}' >> "$REPORT_FILE"

echo "\`\`\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo -e "${GREEN}✓ Redis SET analyzed${NC}"

# Analyze Redis RPUSH operations
echo -e "${YELLOW}Analyzing Redis RPUSH operations...${NC}"
echo "## Redis RPUSH Performance" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"

grep "redis_rpush=" "$LOG_FILE" | \
sed 's/.*serialize=\([0-9.]*\)ms.*redis_rpush=\([0-9.]*\)ms.*/\1 \2/' | \
awk '{
  serialize += $1;
  redis_rpush += $2;
  count++;

  if (NR == 1 || $2 < min_redis) min_redis = $2;
  if ($2 > max_redis) max_redis = $2;
}
END {
  avg_serialize = serialize/count;
  avg_redis = redis_rpush/count;

  print "Operation Count:    " count;
  print "";
  print "Serialization:";
  print "  Average:          " avg_serialize " ms";
  print "";
  print "Redis RPUSH:";
  print "  Average:          " avg_redis " ms";
  print "  Min:              " min_redis " ms";
  print "  Max:              " max_redis " ms";
}' >> "$REPORT_FILE"

echo "\`\`\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo -e "${GREEN}✓ Redis RPUSH analyzed${NC}"

# Performance comparison
echo "## Performance Breakdown" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"

grep "⏱️  REQUEST TIMING | POST /v1/shorten" "$LOG_FILE" | \
sed 's/.*total=\([0-9.]*\)ms.*handler=\([0-9.]*\)ms.*/\1 \2/' | \
awk 'BEGIN {
  redis_set_sum = 0;
  redis_rpush_sum = 0;
}
{
  total += $1;
  handler += $2;
  count++;
}
END {
  # Read Redis times from other analysis
  redis_combined = 0;  # Placeholder, will be calculated separately

  avg_total = total/count;
  avg_handler = handler/count;
  avg_middleware = (total-handler)/count;

  print "Average Request Breakdown:";
  print "├─ Total:           " avg_total " ms (100%)";
  print "│";
  print "├─ Middleware:      " avg_middleware " ms (" (avg_middleware/avg_total)*100 "%)";
  print "│";
  print "└─ Handler:         " avg_handler " ms (" (avg_handler/avg_total)*100 "%)";
}' >> "$REPORT_FILE"

echo "\`\`\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Success/failure summary
echo "## Request Success Rate" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"
echo "\`\`\`" >> "$REPORT_FILE"

if [ -f "$RESULTS_DIR/response_codes.txt" ]; then
    TOTAL=$(wc -l < "$RESULTS_DIR/response_codes.txt")
    SUCCESS=$(grep -c "200" "$RESULTS_DIR/response_codes.txt" || echo "0")
    FAILED=$((TOTAL - SUCCESS))
    SUCCESS_RATE=$(awk "BEGIN {print ($SUCCESS / $TOTAL) * 100}")

    echo "Total Requests:     $TOTAL" >> "$REPORT_FILE"
    echo "Successful (200):   $SUCCESS" >> "$REPORT_FILE"
    echo "Failed:             $FAILED" >> "$REPORT_FILE"
    echo "Success Rate:       $SUCCESS_RATE%" >> "$REPORT_FILE"
else
    echo "Response codes file not found" >> "$REPORT_FILE"
fi

echo "\`\`\`" >> "$REPORT_FILE"
echo "" >> "$REPORT_FILE"

# Display report
echo ""
echo "=========================================="
echo -e "${BLUE}Analysis Complete!${NC}"
echo "=========================================="
echo ""
cat "$REPORT_FILE"
echo ""
echo -e "${GREEN}Full report saved to: $REPORT_FILE${NC}"
echo ""
