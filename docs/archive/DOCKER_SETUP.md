# Axon Docker Setup Guide

This guide shows how to run the Axon trading system (scheduler, dashboard, and PostgreSQL) using Docker Compose.

## Prerequisites

- Docker and Docker Compose installed
- Angel One trading account credentials (for live trading)

## Quick Start

1. **Clone and navigate to the project:**
   ```bash
   cd Axon
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.docker .env
   # Edit .env with your Angel One credentials
   ```

3. **Start all services:**
   ```bash
   docker-compose up -d
   ```

4. **Check that services are running:**
   ```bash
   docker-compose ps
   ```

5. **View logs:**
   ```bash
   docker-compose logs -f
   ```

## Services

### PostgreSQL Database
- **Port:** 5432
- **Database:** axon
- **Username:** axon
- **Password:** axon_password
- **Volume:** Persistent data storage

### Trading Scheduler
- **Container:** axon-scheduler
- **Function:** Runs automated trading during market hours
- **Logs:** `./logs/scheduler/`

### Web Interface
- **URL:** http://localhost:5000
- **Container:** axon-web
- **Function:** Real-time trading terminal
- **Auth:** Configured via WEB_USERNAME/WEB_PASSWORD

### Analytics Dashboard
- **URL:** http://localhost:8501
- **Container:** axon-dashboard
- **Function:** Performance analytics and charts
- **Data:** Reads from PostgreSQL database

## Configuration

### Environment Variables (.env file)

```bash
# Angel One Credentials (required for live trading)
ANGEL_ONE_API_KEY=your_api_key
ANGEL_ONE_CLIENT_ID=your_client_id
ANGEL_ONE_PIN=your_pin
ANGEL_ONE_TOTP_SECRET=your_totp_secret

# Web Interface
WEB_USERNAME=admin
WEB_PASSWORD=changeme
```

### Trading Modes

- **Mock Mode:** Set empty credentials or run without `--angel-one`
- **Live Mode:** Provide valid Angel One credentials

## Docker Commands

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Rebuild and restart
docker-compose up -d --build

# View logs
docker-compose logs -f

# View logs for specific service
docker-compose logs -f scheduler

# Restart a specific service
docker-compose restart web

# Clean up (removes volumes too)
docker-compose down -v
```

## Database Access

To connect to PostgreSQL from host:
```bash
psql -h localhost -p 5432 -U axon -d axon
# Password: axon_password
```

## Troubleshooting

### Check service health:
```bash
docker-compose ps
```

### View service logs:
```bash
docker-compose logs scheduler
docker-compose logs web
docker-compose logs dashboard
```

### Database connection issues:
```bash
# Check if PostgreSQL is ready
docker-compose exec postgres pg_isready -U axon -d axon
```

### Reset everything:
```bash
docker-compose down -v
docker-compose up -d --build
```

## Security Notes

- Change default web credentials in production
- Use strong passwords for database access
- Consider using Docker secrets for sensitive credentials
- The setup exposes ports to localhost only by default

## Development

To modify the code and rebuild:
```bash
# Make changes to source code
docker-compose up -d --build
```

## Backup

Database data is persisted in Docker volume `axon-postgres-data`. To backup:
```bash
docker run --rm -v axon-postgres-data:/data -v $(pwd):/backup postgres:15 tar czf /backup/postgres-backup.tar.gz -C /data .
```