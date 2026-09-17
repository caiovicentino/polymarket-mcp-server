#!/bin/bash
# Test Docker Setup
# Validates Docker infrastructure without requiring credentials

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }
print_info() { echo -e "${BLUE}ℹ${NC} $1"; }
print_test() { echo -e "${YELLOW}➜${NC} $1"; }

echo -e "${BLUE}"
cat << "EOF"
╔════════════════════════════════════════════╗
║   Docker Infrastructure Test Suite        ║
╚════════════════════════════════════════════╝
EOF
echo -e "${NC}"

# Test counter
TESTS_PASSED=0
TESTS_FAILED=0

# Test function
run_test() {
    local test_name="$1"
    local test_command="$2"

    print_test "Testing: $test_name"

    if eval "$test_command" > /dev/null 2>&1; then
        print_success "$test_name"
        ((TESTS_PASSED++))
        return 0
    else
        print_error "$test_name"
        ((TESTS_FAILED++))
        return 1
    fi
}

# File existence tests
echo ""
print_info "Checking Docker files..."
run_test "Dockerfile exists" "[ -f Dockerfile ]"
run_test "docker-compose.yml exists" "[ -f docker-compose.yml ]"
run_test ".dockerignore exists" "[ -f .dockerignore ]"
run_test "docker-start.sh exists" "[ -f docker-start.sh ]"
run_test "docker-start.sh is executable" "[ -x docker-start.sh ]"
run_test ".env.example exists" "[ -f .env.example ]"

# Docker installation tests
echo ""
print_info "Checking Docker installation..."
run_test "Docker is installed" "command -v docker"
run_test "Docker daemon is running" "docker info"
run_test "Docker Compose is available" "docker compose version"

# Docker build test
echo ""
print_info "Testing Docker build..."

# Create temporary .env for testing
cat > .env.test << EOF
POLYGON_PRIVATE_KEY=0x0000000000000000000000000000000000000000000000000000000000000000
POLYGON_ADDRESS=0x0000000000000000000000000000000000000000
DEMO_MODE=true
LOG_LEVEL=INFO
POLYMARKET_CHAIN_ID=137
MAX_ORDER_SIZE_USD=1000
MAX_TOTAL_EXPOSURE_USD=10000
REQUIRE_CONFIRMATION_ABOVE_USD=100
EOF

print_test "Building Docker image (this may take a minute)..."
if docker build -t polymarket-mcp:test . > /tmp/docker-build.log 2>&1; then
    print_success "Docker build succeeded"
    ((TESTS_PASSED++))

    # Test image properties
    echo ""
    print_info "Checking image properties..."

    # Get image size
    IMAGE_SIZE=$(docker images polymarket-mcp:test --format "{{.Size}}")
    print_info "Image size: $IMAGE_SIZE"

    # Check image layers
    LAYERS=$(docker history polymarket-mcp:test --quiet | wc -l)
    print_info "Image layers: $LAYERS"

    # Test image can run
    print_test "Testing image can start..."
    if timeout 10s docker run --rm --env-file .env.test polymarket-mcp:test python -c "from polymarket_mcp.config import load_config; print('OK')" > /tmp/docker-run.log 2>&1; then
        print_success "Image runs successfully"
        ((TESTS_PASSED++))
    else
        print_error "Image failed to run"
        echo "Check /tmp/docker-run.log for details"
        ((TESTS_FAILED++))
    fi

else
    print_error "Docker build failed"
    echo "Check /tmp/docker-build.log for details"
    ((TESTS_FAILED++))
fi

# Kubernetes files test
echo ""
print_info "Checking Kubernetes files..."
run_test "k8s directory exists" "[ -d k8s ]"
run_test "k8s/deployment.yaml exists" "[ -f k8s/deployment.yaml ]"
run_test "k8s/service.yaml exists" "[ -f k8s/service.yaml ]"
run_test "k8s/configmap.yaml exists" "[ -f k8s/configmap.yaml ]"
run_test "k8s/secret.yaml.template exists" "[ -f k8s/secret.yaml.template ]"

# YAML validation (if kubectl available)
if command -v kubectl > /dev/null 2>&1; then
    echo ""
    print_info "Validating Kubernetes YAML..."
    run_test "deployment.yaml is valid" "kubectl apply --dry-run=client -f k8s/deployment.yaml"
    run_test "service.yaml is valid" "kubectl apply --dry-run=client -f k8s/service.yaml"
    run_test "configmap.yaml is valid" "kubectl apply --dry-run=client -f k8s/configmap.yaml"
fi

# GitHub Actions workflow test
echo ""
print_info "Checking CI/CD files..."
run_test ".github/workflows directory exists" "[ -d .github/workflows ]"
run_test "docker-publish.yml exists" "[ -f .github/workflows/docker-publish.yml ]"

# Documentation test
echo ""
print_info "Checking documentation..."
run_test "DOCKER.md exists" "[ -f DOCKER.md ]"
run_test "k8s/README.md exists" "[ -f k8s/README.md ]"

# docker-compose validation
echo ""
print_info "Validating docker-compose.yml..."
if docker compose config > /dev/null 2>&1; then
    print_success "docker-compose.yml is valid"
    ((TESTS_PASSED++))
else
    print_error "docker-compose.yml has errors"
    ((TESTS_FAILED++))
fi

# Clean up
echo ""
print_info "Cleaning up test artifacts..."
rm -f .env.test
docker rmi polymarket-mcp:test > /dev/null 2>&1 || true
print_success "Cleanup complete"

# Summary
echo ""
echo -e "${BLUE}═════════════════════════════════════════════${NC}"
echo -e "${GREEN}Tests passed: $TESTS_PASSED${NC}"
echo -e "${RED}Tests failed: $TESTS_FAILED${NC}"
echo -e "${BLUE}═════════════════════════════════════════════${NC}"

if [ $TESTS_FAILED -eq 0 ]; then
    echo ""
    print_success "All tests passed! Docker infrastructure is ready."
    echo ""
    print_info "Next steps:"
    echo "  1. Copy .env.example to .env and add your credentials"
    echo "  2. Run: ./docker-start.sh"
    echo "  3. Or run: docker compose up"
    exit 0
else
    echo ""
    print_error "Some tests failed. Please review the output above."
    exit 1
fi
