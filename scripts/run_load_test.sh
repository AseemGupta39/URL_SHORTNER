#!/bin/bash
# Load test script - runs 1K concurrent requests and saves results

set -e

# Configuration
BASE_URL="${BASE_URL:-http://localhost:8001}"
CONCURRENT="${CONCURRENT:-1000}"
OUTPUT_DIR="test_results/$(date +%Y%m%d_%H%M%S)"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=========================================="
echo "Load Test Runner"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  Base URL: $BASE_URL"
echo "  Concurrent requests: $CONCURRENT"
echo "  Output directory: $OUTPUT_DIR"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Step 1: Warmup request
echo -e "${YELLOW}[1/4] Running warmup request...${NC}"
curl -X POST "$BASE_URL/v1/shorten" \
  -H "Content-Type: application/json" \
  -d '{"original_url": "https://example.com/warmup"}' \
  -s -o /dev/null
echo -e "${GREEN}✓ Warmup complete${NC}"
sleep 2
echo ""

# Step 2: Start log collection
echo -e "${YELLOW}[2/4] Starting log collection...${NC}"
docker-compose logs --tail=0 -f shorten > "$OUTPUT_DIR/shorten.log" 2>&1 &
LOG_PID=$!
echo -e "${GREEN}✓ Logging to: $OUTPUT_DIR/shorten.log${NC}"
sleep 1
echo ""

# Step 3: Run load test
echo -e "${YELLOW}[3/4] Running load test ($CONCURRENT concurrent requests)...${NC}"
START_TIME=$(date +%s)

# Generate URLs file
URLS_FILE="$OUTPUT_DIR/urls.txt"
for i in $(seq 1 $CONCURRENT); do
  echo "$BASE_URL/v1/shorten" >> "$URLS_FILE"
done

# Run parallel requests using xargs
cat "$URLS_FILE" | xargs -P $CONCURRENT -I {} curl -X POST {} \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://example.com/resource/$(uuidgen)\"}" \
  -s -o /dev/null -w "%{http_code}\n" 2>&1 | tee "$OUTPUT_DIR/response_codes.txt" > /dev/null

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo -e "${GREEN}✓ Load test complete (${DURATION}s)${NC}"
echo ""

# Step 4: Stop log collection and analyze
echo -e "${YELLOW}[4/4] Stopping log collection and analyzing...${NC}"
sleep 5
kill $LOG_PID 2>/dev/null || true
echo -e "${GREEN}✓ Logs saved${NC}"
echo ""

# Quick stats
TOTAL_REQUESTS=$(wc -l < "$OUTPUT_DIR/response_codes.txt")
SUCCESS_REQUESTS=$(grep -c "200" "$OUTPUT_DIR/response_codes.txt" || echo "0")
FAILED_REQUESTS=$((TOTAL_REQUESTS - SUCCESS_REQUESTS))

echo "=========================================="
echo -e "${BLUE}Quick Results${NC}"
echo "=========================================="
echo "Total requests: $TOTAL_REQUESTS"
echo "Successful (200): $SUCCESS_REQUESTS"
echo "Failed: $FAILED_REQUESTS"
echo "Duration: ${DURATION}s"
echo ""
echo "Run analysis script for detailed breakdown:"
echo "  ./scripts/analyze_results.sh $OUTPUT_DIR"
echo ""
