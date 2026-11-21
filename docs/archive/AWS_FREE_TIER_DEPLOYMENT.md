# Axon AWS Free-Tier VM Deployment Strategy

This guide is the lowest-cost AWS deployment path for this repo.

The goal is not "cloud native". The goal is to keep the system running on a single free-tier eligible VM without accidentally adding paid AWS services.

## Recommended Shape

Use one EC2 instance and keep everything on that machine:

- EC2 only: no ECS, no EKS, no RDS, no NAT Gateway, no Application Load Balancer, no ECR requirement
- Ubuntu LTS on a free-tier eligible instance type for your account
- SQLite for the default database
- `systemd` for process supervision
- optional Nginx on the same VM if you want public web access
- Streamlit dashboard only when you need it, not as an always-on service

For this repo, the best default EC2 choice is `t3.micro` in `ap-south-1` (Mumbai):

- `t3.micro` is the best low-risk default because it keeps x86_64 compatibility with Python packages in this repo
- `t4g.micro` can be slightly cheaper or more efficient in some accounts, but ARM package compatibility is the wrong risk to take for a live-trading first deployment
- Mumbai region code is `ap-south-1`

This repo already supports SQLite by default in [src/axon_aone/db.py](src/axon_aone/db.py), which makes it a better fit for a micro instance than the Azure Docker plus PostgreSQL deployment.

## Why This Is The Right AWS Strategy

The Azure deployment in this repo builds multiple containers and runs PostgreSQL alongside the app. That is reasonable on a larger VM, but it is not the right baseline for a cost-free EC2 deployment.

On a free-tier micro VM, the practical constraints are:

- low RAM
- burst-limited CPU
- limited disk allowance
- easy accidental charges from extra AWS services

Because of that, the safest design is:

- scheduler always on
- web UI optional
- dashboard on demand
- SQLite by default
- direct `venv` install instead of Docker

## Cost Guardrails

Stay inside the actual free-tier allowances shown in AWS Billing for your account. AWS free offers change over time and may differ by account type.

To avoid surprise charges, do not add:

- RDS
- NAT Gateway
- Application Load Balancer
- Route 53 hosted zones unless you explicitly want a domain
- CloudWatch log shipping at high volume
- extra unattached EBS volumes
- idle Elastic IPs not attached to a running instance

Keep the deployment to:

- one EC2 instance
- one root EBS volume sized conservatively
- one security group
- SSH access restricted to your IP

## Recommended Modes

### Mode A: Safest Free-Tier Setup

Use this first.

- `run_trader.py --schedule` in mock mode
- SQLite database
- no public web UI
- SSH tunnel for occasional access if needed

This is the best choice for paper trading, validation, and continuous soak testing.

### Mode B: Lean Live Setup

Use this only after Mode A is stable.

- scheduler always on
- live Angel One credentials provided through environment file
- web UI enabled only when needed
- web bound to `127.0.0.1` and proxied through Nginx if you need browser access
- Streamlit dashboard started manually when you want analytics

This keeps the persistent footprint small enough for a micro instance.

## AWS Console Build Plan

1. Launch one Ubuntu LTS EC2 instance using a free-tier eligible instance family for your account.
2. Keep the root disk small and within your free storage allowance.
3. Create one security group:
   - allow `22/tcp` only from your office or home IP
   - allow `80/tcp` only if you enable the web UI behind Nginx
   - do not expose `5000` or `8501` directly to the internet
4. Do not create a load balancer.
5. Do not create RDS.
6. Do not create a NAT Gateway.

## Mumbai Recommendation

If your users and broker workflow are India-based, Mumbai is the right first region to try.

- region: `ap-south-1`
- default instance: `t3.micro`
- root volume: `12 GiB gp3`
- public access: Nginx on `80` and optionally `443`
- internal app ports: keep Flask on `127.0.0.1:5000` and Streamlit on `127.0.0.1:8501`

This repo now includes a launcher for that setup at [deploy-aws-ec2-mumbai.ps1](deploy-aws-ec2-mumbai.ps1).

For full laptop-to-VM deployment over SSH without relying on git access from the instance, use [deploy-aws-ec2-mumbai-from-laptop.ps1](deploy-aws-ec2-mumbai-from-laptop.ps1). It launches the VM, packages the current workspace, uploads it over `scp`, and runs the bootstrap script remotely.

For a Docker-based EC2 deployment using this repo's `Dockerfile`, use [deploy-aws-ec2-mumbai-docker-from-laptop.ps1](deploy-aws-ec2-mumbai-docker-from-laptop.ps1). It launches the VM, uploads the current workspace, builds the image on the host, and runs a single app container with:

- persistent SQLite storage using a Docker volume mounted to `/app/data`
- web UI published on port `80`
- dashboard published on port `8501` by default (restricted to your current public IP unless overridden)

Example:

```powershell
.\deploy-aws-ec2-mumbai-docker-from-laptop.ps1 `
   -CreateKeyPairIfMissing
```

To keep dashboard private and access it only through SSH tunnel:

```powershell
.\deploy-aws-ec2-mumbai-docker-from-laptop.ps1 `
   -DisablePublicDashboard
```

Before launching, configure AWS CLI credentials interactively with [start-aws-configure.ps1](start-aws-configure.ps1). Use the default flow for access keys or `-UseSso` if your AWS account uses IAM Identity Center / SSO.

If you do not want to save a `.pem` key at all, use the SSO plus SSM path instead:

- [deploy-aws-ec2-mumbai-sso.ps1](deploy-aws-ec2-mumbai-sso.ps1) launches a keyless EC2 instance with an SSM-managed IAM role
- [deploy-aws-ec2-mumbai-from-laptop-sso.ps1](deploy-aws-ec2-mumbai-from-laptop-sso.ps1) packages the local repo, uploads it to a temporary S3 object, and bootstraps the VM through AWS Systems Manager Run Command

This path removes SSH key management entirely. It relies on:

- AWS SSO for CLI authentication
- Systems Manager for remote command execution
- a temporary S3 object for transferring the deployment bundle

Example usage from Windows PowerShell after installing AWS CLI:

```powershell
.\deploy-aws-ec2-mumbai.ps1 `
   -KeyPairName axon-mumbai-key `
   -CreateKeyPairIfMissing `
   -OpenHttps
```

If your repository is reachable by `git clone`, you can also pass it for first-boot bootstrap:

```powershell
.\deploy-aws-ec2-mumbai.ps1 `
   -KeyPairName axon-mumbai-key `
   -CreateKeyPairIfMissing `
   -RepoUrl https://github.com/<owner>/<repo>.git `
   -RepoBranch main `
   -OpenHttps
```

I could not verify instance launch from this workspace because AWS CLI is not installed here, but `ap-south-1` is the correct Mumbai region identifier and the script is built to target it by default.

## VM Layout

Recommended on-instance layout:

- app directory: `/opt/axon`
- virtualenv: `/opt/axon/.venv`
- env file: `/etc/axon/axon.env`
- scheduler service: `axon-scheduler.service`
- optional web service: `axon-web.service`
- optional reverse proxy: Nginx on port `80`

## Runtime Recommendations

For free-tier stability:

- keep the database on SQLite first
- do not run PostgreSQL unless you later move off micro sizing
- do not keep Streamlit running all day
- add swap on the VM to reduce OOM risk
- keep market-scan batch size conservative
- start in paper mode before live mode

Suggested environment values for a micro VM:

```env
AXON_DATABASE_URL=sqlite:////opt/axon/axon.db
AXON_TRADE_MODE=PAPER
AXON_MARKET_SCAN_BATCH_SIZE=10
WEB_USERNAME=admin
WEB_PASSWORD=change-this-before-public-access
```

For live mode, add:

```env
ANGEL_ONE_API_KEY=...
ANGEL_ONE_CLIENT_ID=...
ANGEL_ONE_PIN=...
ANGEL_ONE_TOTP_SECRET=...
```

## Deployment Steps On The VM

From the instance:

```bash
sudo apt-get update
sudo apt-get install -y git
sudo mkdir -p /opt
cd /opt
sudo git clone <your-repo-url> axon
sudo chown -R $USER:$USER /opt/axon
cd /opt/axon
bash scripts/bootstrap-aws-free-tier.sh
```

The bootstrap script will:

- install system packages
- create a Python virtual environment
- install dependencies
- create `/etc/axon/axon.env` if it does not exist
- create a `systemd` scheduler service
- create an optional `systemd` web service
- optionally configure Nginx

## Service Operations

Scheduler:

```bash
sudo systemctl status axon-scheduler
sudo journalctl -u axon-scheduler -f
sudo systemctl restart axon-scheduler
```

Optional web UI:

```bash
sudo systemctl enable --now axon-web
sudo systemctl status axon-web
sudo journalctl -u axon-web -f
```

Manual dashboard when needed:

```bash
cd /opt/axon
source .venv/bin/activate
streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501
```

## Security Baseline

Minimum acceptable baseline:

- do not expose SSH to the whole internet
- do not expose Flask directly on `0.0.0.0:5000`
- use `WEB_USERNAME` and `WEB_PASSWORD`
- keep broker credentials only in `/etc/axon/axon.env`
- set file permissions on the env file to owner-read only
- prefer SSH tunneling or a reverse proxy over opening internal ports

## Operational Tradeoffs

What you gain:

- effectively zero infrastructure cost when inside free-tier allowance
- simpler failure surface
- faster deployment and rollback
- less AWS billing risk

What you give up:

- no managed database
- no horizontal scaling
- limited RAM headroom
- dashboard should be on demand, not permanent

That is the right trade for this stage of the project.

## When To Move Beyond Free Tier

Upgrade the architecture when any of these become true:

- you want PostgreSQL always on
- you want dashboard, web, and scheduler always on together
- you need better observability than local logs and `journalctl`
- you want safer public internet exposure with TLS and a domain
- you need automated backups and higher availability

At that point, move to a paid VM shape first. Do not jump straight to multiple managed AWS services unless you actually need them.