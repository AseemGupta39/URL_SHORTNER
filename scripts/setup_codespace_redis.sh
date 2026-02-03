#!/bin/bash
# Setup script for GitHub Codespace Redis testing
# This script installs and configures Redis on the Codespace host

set -e

echo "=========================================="
echo "Redis Localhost Performance Test Setup"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Step 1: Install Redis
echo -e "${YELLOW}[1/4] Installing Redis on host...${NC}"
if command -v redis-cli &> /dev/null; then
    echo -e "${GREEN}✓ Redis already installed${NC}"
else
    sudo apt update -qq 2>&1 | grep -v "GPG error\|not signed" || true
    sudo apt install -y redis-server 2>&1 | grep -v "GPG error\|not signed" || true
    echo -e "${GREEN}✓ Redis installed${NC}"
fi
echo ""

# Step 2: Configure Redis to accept Docker connections
echo -e "${YELLOW}[2/4] Configuring Redis for Docker bridge...${NC}"
sudo sed -i 's/^bind .*/bind 127.0.0.1 172.17.0.1/' /etc/redis/redis.conf
sudo systemctl restart redis
sleep 2
echo -e "${GREEN}✓ Redis configured${NC}"
echo ""

# Step 3: Verify Redis
echo -e "${YELLOW}[3/4] Verifying Redis connectivity...${NC}"
if redis-cli ping | grep -q PONG; then
    echo -e "${GREEN}✓ Redis on localhost: OK${NC}"
else
    echo -e "${RED}✗ Redis on localhost: FAILED${NC}"
    exit 1
fi

if timeout 2 redis-cli -h 172.17.0.1 ping 2>/dev/null | grep -q PONG; then
    echo -e "${GREEN}✓ Redis on Docker bridge (172.17.0.1): OK${NC}"
else
    echo -e "${RED}✗ Redis on Docker bridge: FAILED${NC}"
    echo "Trying to restart Redis..."
    sudo systemctl restart redis
    sleep 2
    if timeout 2 redis-cli -h 172.17.0.1 ping 2>/dev/null | grep -q PONG; then
        echo -e "${GREEN}✓ Redis on Docker bridge: OK (after restart)${NC}"
    else
        echo -e "${RED}✗ Still failing. Check firewall/network settings${NC}"
        exit 1
    fi
fi
echo ""

# Step 4: Rebuild Docker services
echo -e "${YELLOW}[4/4] Rebuilding Docker services...${NC}"
docker-compose down 2>/dev/null || true
docker-compose build shorten batch_processor
echo -e "${GREEN}✓ Services rebuilt${NC}"
echo ""

# Summary
echo "=========================================="
echo -e "${GREEN}Setup Complete!${NC}"
echo "=========================================="
echo ""
echo "Redis is now running on the host machine."
echo "Docker services will connect to: redis://172.17.0.1:6379"
echo ""
echo "Next steps:"
echo "  1. Start services: docker-compose up -d"
echo "  2. Wait for services to be healthy (30 seconds)"
echo "  3. Run test: ./scripts/run_load_test.sh"
echo ""
