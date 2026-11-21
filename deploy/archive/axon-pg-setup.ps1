$log = "$env:TEMP\axon-pg-setup.log"
$ErrorActionPreference = 'Continue'

function Log { param($m) $ts = Get-Date -Format 'HH:mm:ss'; "$ts $m" | Tee-Object -FilePath $log -Append | Write-Host }

Log "=== Axon PostgreSQL Local Setup ==="

# 1. Switch to the default Docker context (uses docker_engine pipe which is present)
docker context use default 2>&1 | ForEach-Object { Log "CTX: $_" }
Log "context-switch exit=$LASTEXITCODE"

# 2. Verify daemon responds
$ping = docker version --format '{{.Server.Version}}' 2>&1
Log "docker-server-version: $ping  exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: Docker daemon did not respond. Make sure Docker Desktop engine is running."
    exit 1
}

# 3. Create network (ignore error if it already exists)
$net = docker network create axon-network 2>&1
Log "network: $net  exit=$LASTEXITCODE"

# 4. Create PostgreSQL data volume
$vol = docker volume create axon-postgres-data 2>&1
Log "volume: $vol  exit=$LASTEXITCODE"

# 5. Remove any existing axon-postgres container
docker rm -f axon-postgres 2>&1 | ForEach-Object { Log "rm: $_" }

# 6. Start PostgreSQL 15 container
$run = docker run -d `
    --name axon-postgres `
    --restart unless-stopped `
    --network axon-network `
    -p 5432:5432 `
    -e POSTGRES_DB=axon `
    -e POSTGRES_USER=axon `
    -e POSTGRES_PASSWORD=axon_password `
    -v axon-postgres-data:/var/lib/postgresql/data `
    postgres:15 2>&1
Log "docker-run: $run  exit=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) {
    Log "ERROR: Failed to start axon-postgres container"
    docker logs axon-postgres 2>&1 | ForEach-Object { Log "LOG: $_" }
    exit 1
}

# 7. Wait for pg_isready (up to 60 seconds)
$ready = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 2
    docker exec axon-postgres pg_isready -U axon -d axon 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        Log "pg_isready: READY after ${i} attempts"
        break
    }
    Log "pg_isready: attempt $i/30 - not ready yet"
}

if (-not $ready) {
    Log "ERROR: PostgreSQL did not become ready in 60 seconds"
    docker logs axon-postgres 2>&1 | ForEach-Object { Log "PGLOG: $_" }
    exit 1
}

# 8. Verify connection
$q = docker exec axon-postgres psql -U axon -d axon -c "SELECT version();" 2>&1 | Out-String
Log "pg-query: $q"

# 9. Show running container status
$status = docker ps --filter name=axon-postgres --format "{{.Names}} | {{.Image}} | {{.Status}} | {{.Ports}}" 2>&1
Log "container-status: $status"

Log "=== Setup complete ==="
Log "DATABASE_URL: postgresql+psycopg2://axon:axon_password@localhost:5432/axon"
