#!/bin/bash

# Docker setup script for news aggregation service
set -e

echo "🐳 Setting up Docker environment for News Aggregation Service"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    print_error "Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p logs
mkdir -p data/redis
mkdir -p data/meilisearch

# Ensure database file exists
if [ ! -f "database.db" ]; then
    print_warning "Database file not found. Creating empty database..."
    touch database.db
fi

# Build and start services
print_status "Building Docker images..."
docker-compose build

print_status "Starting services..."
docker-compose up -d

# Wait for services to be healthy
print_status "Waiting for services to be ready..."
sleep 10

# Check service health
print_status "Checking service health..."

# Check Redis
if docker-compose exec redis redis-cli ping > /dev/null 2>&1; then
    print_status "✅ Redis is healthy"
else
    print_error "❌ Redis is not responding"
fi

# Check MeiliSearch
if curl -f http://localhost:7700/health > /dev/null 2>&1; then
    print_status "✅ MeiliSearch is healthy"
else
    print_error "❌ MeiliSearch is not responding"
fi

# Check API
if curl -f http://localhost:8000/api/v1/health/ > /dev/null 2>&1; then
    print_status "✅ API is healthy"
else
    print_error "❌ API is not responding"
fi

# Run database migrations
print_status "Running database migrations..."
docker-compose exec api alembic upgrade head

# Initialize database with seed data
print_status "Initializing database..."
docker-compose exec api python -c "
import sys
sys.path.append('/app')
from src.db.operations import initialize_db
initialize_db()
"

print_status "🎉 Docker setup complete!"
print_status "Services available at:"
print_status "  - API: http://localhost:8000"
print_status "  - API Docs: http://localhost:8000/docs"
print_status "  - MeiliSearch: http://localhost:7700"
print_status "  - Redis: localhost:6379"

print_status "To view logs: docker-compose logs -f [service-name]"
print_status "To stop services: docker-compose down"
print_status "To restart services: docker-compose restart"
