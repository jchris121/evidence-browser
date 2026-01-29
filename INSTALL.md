# Evidence Browser Installation Guide

## Quick Start

```bash
git clone https://github.com/jchris121/tina-evidence-browser.git
cd tina-evidence-browser
./install.sh
```

The installer will prompt you to choose between SQLite or PostgreSQL.

## Database Options

### Option 1: SQLite (Default)
- **Best for:** Single-node deployments, quick setup
- **Pros:** Zero configuration, no external dependencies
- **Cons:** Single-node only, slower for large datasets

### Option 2: PostgreSQL
- **Best for:** Multi-node deployments, production use
- **Pros:** Multi-node access, better performance, scalable
- **Cons:** Requires PostgreSQL/Supabase setup

## Installation

### 1. Clone Repository

```bash
git clone https://github.com/jchris121/tina-evidence-browser.git
cd tina-evidence-browser
```

### 2. Run Installer

```bash
chmod +x install.sh
./install.sh
```

The installer will:
1. Ask which database backend to use (SQLite or PostgreSQL)
2. Install Python dependencies
3. Set up the database schema
4. Create a systemd service (optional)
5. Start the server

### 3. Configure Data Sources

Edit the paths in `db.py` to point to your evidence data:

```python
CELLEBRITE_DIR = Path.home() / "path/to/cellebrite-parsed"
AXIOM_DIR = Path.home() / "path/to/axiom-extracts"
```

### 4. Access the App

Open your browser to: `http://localhost:8888`

Default credentials: `admin` / `qV3GkcNbaHcWGUrDbDalpw`

**⚠️ Change the default password immediately via the Admin portal.**

## PostgreSQL Setup

If you chose PostgreSQL, you'll need a running PostgreSQL instance.

### Option A: Supabase (Recommended)

```bash
# Install Supabase CLI
brew install supabase/tap/supabase  # macOS
# or
npm install -g supabase             # Node.js

# Initialize and start
supabase init
supabase start
```

Connection string: `postgresql://postgres:postgres@127.0.0.1:54322/postgres`

### Option B: Standard PostgreSQL

```bash
# Install PostgreSQL
sudo apt install postgresql postgresql-contrib  # Ubuntu/Debian
brew install postgresql@14                      # macOS

# Create database
createdb evidence_browser

# Update connection in db.py
POSTGRES_CONN = "postgresql://user:password@localhost:5432/evidence_browser"
```

## Configuration

### Environment Variables

```bash
export EVIDENCE_DB_TYPE=postgres  # or sqlite
export POSTGRES_CONN="postgresql://user:pass@host:port/db"
export SERVER_PORT=8888
```

### Server Options

```bash
# Development (auto-reload)
python3 -m uvicorn server:app --reload --port 8888

# Production
python3 -m uvicorn server:app --host 0.0.0.0 --port 8888

# Background (systemd recommended)
nohup python3 -m uvicorn server:app --host 0.0.0.0 --port 8888 > /tmp/evidence-server.log 2>&1 &
```

## Systemd Service (Linux)

```bash
sudo cp evidence-browser.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable evidence-browser
sudo systemctl start evidence-browser
```

## Multi-Node Setup

For multi-node deployments (DGX + Mac + others):

1. **Use PostgreSQL** on a shared node (always-on server)
2. **Configure connection** on each node to point to the shared database
3. **Sync data sources** via shared network storage or regular sync scripts

Example:
```bash
# Node 1 (DGX) - Database host
POSTGRES_CONN="postgresql://postgres:postgres@127.0.0.1:54322/postgres"

# Node 2 (Mac) - Remote connection
POSTGRES_CONN="postgresql://postgres:postgres@100.75.77.21:54322/postgres"
```

## Data Ingestion

### Initial Index

```bash
# Automatically indexes on first run
python3 -c "from db import db; db.full_index()"
```

### Refresh After Updates

```bash
# Manual refresh
curl -X POST http://localhost:8888/api/refresh

# Or via Python
python3 -c "from db import db; db.refresh()"
```

### File Watcher (Auto-refresh)

The server includes a background file watcher that checks for changes every 30 seconds. No manual refresh needed in most cases.

## Troubleshooting

### Port Already in Use

```bash
# Kill existing server
pkill -f "uvicorn server:app"

# Or use a different port
python3 -m uvicorn server:app --port 8889
```

### Database Connection Issues

```bash
# Test PostgreSQL connection
psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -c "SELECT 1;"

# Check if Supabase is running
docker ps | grep supabase
```

### Performance Issues

- **SQLite:** Consider switching to PostgreSQL for >100K records
- **PostgreSQL:** Ensure indexes are created (automatically done on setup)
- **File watcher:** Disable if CPU usage is high: set `db.start_watcher(interval=0)`

## Security

1. **Change default admin password** immediately
2. **Use Tailscale or VPN** for remote access (don't expose port 8888 to internet)
3. **Enable HTTPS** via reverse proxy (nginx/Caddy) for production
4. **Backup database** regularly:
   ```bash
   # SQLite
   cp evidence.db evidence.db.backup
   
   # PostgreSQL
   pg_dump -h localhost -U postgres evidence_browser > backup.sql
   ```

## API Documentation

Once running, API docs available at:
- Swagger UI: `http://localhost:8888/docs`
- ReDoc: `http://localhost:8888/redoc`

## Support

- GitHub Issues: https://github.com/jchris121/tina-evidence-browser/issues
- Documentation: https://github.com/jchris121/tina-evidence-browser/wiki
