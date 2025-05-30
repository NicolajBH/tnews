# Terminal News - RSS Aggregation Service

A FastAPI-based news aggregation service with a terminal user interface, demonstrating modern backend development practices.

## Features

- **FastAPI REST API** with async/await support
- **Real-time news aggregation** from multiple RSS sources
- **Terminal User Interface** built with Textual
- **Background task processing** with Celery
- **Full-text search** powered by MeiliSearch
- **Redis caching** for performance optimization
- **Comprehensive monitoring** with health checks and metrics
- **Docker containerization** for easy deployment

## Tech Stack

### Backend Core
- **FastAPI** - Modern Python web framework
- **SQLModel** - Type-safe database ORM
- **Pydantic** - Data validation and serialization
- **Alembic** - Database migrations

### Infrastructure
- **Redis** - Caching and message broker
- **MeiliSearch** - Full-text search engine
- **Celery** - Distributed task processing
- **Docker** - Containerization
- **PostgreSQL** - Production database (SQLite for development)

### Monitoring & Performance
- **Prometheus** - Metrics collection
- **Structured logging** with correlation IDs
- **Health checks** and circuit breakers
- **Performance tracking** and optimization

## Quick Start with Docker

```bash
# Setup development environment
make setup

# Check service health
make health

# View logs
make logs

# Run tests
make test
```

## Services

- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **MeiliSearch**: http://localhost:7700
- **Redis**: localhost:6379

## Architecture

The application follows a microservices architecture with:

- **API Service** - Handles HTTP requests and responses
- **Celery Workers** - Process background tasks (RSS fetching)
- **Celery Beat** - Task scheduling
- **Redis** - Caching and message broker
- **MeiliSearch** - Search index and full-text search

## Development

### Local Development
```bash
# Start services
make up

# View API logs
make logs-api

# Access API container shell
make shell

# Run database migrations
make migrate
```

### Testing
```bash
# Run tests
make test

# Run tests with coverage
make test-coverage
```

## Production Deployment

```bash
# Build production images
make prod-build

# Start production services
make prod-up

# View production logs
make prod-logs
```

## Backend Development Concepts Demonstrated

This project showcases essential backend development skills:

- **Async Programming** - FastAPI with async/await
- **Database Design** - Proper schema design and migrations
- **Caching Strategies** - Redis for performance optimization
- **Background Processing** - Celery for long-running tasks
- **API Design** - RESTful APIs with proper status codes
- **Error Handling** - Comprehensive exception handling
- **Security** - Authentication, rate limiting, CORS
- **Testing** - Unit and integration tests
- **Monitoring** - Health checks, metrics, logging
- **Containerization** - Docker multi-service setup
- **Performance** - Connection pooling, circuit breakers

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run the test suite
6. Submit a pull request

## License

MIT License - see LICENSE file for details
