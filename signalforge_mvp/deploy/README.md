# SignalForge — persistent deploy (Oracle Cloud Always-Free VM)

A stable, 24/7, HTTPS deployment for a resume-grade link your dashboard and the
mobile app can point at permanently. The stack is the same one you ran locally
(backend + Postgres + Redis + nginx) with **Caddy** in front for automatic
HTTPS.

**What you do** (I can't create accounts or enter card details): the Oracle
signup, the VM, and DNS. **What's prepared for you:** everything else — one
command brings the whole stack up with a real certificate.

---

## 1. Create the VM (Oracle Cloud, free)

1. Sign up at <https://cloud.oracle.com> (a card is required for identity
   verification only — Always-Free resources are never charged).
2. Create a Compute instance:
   - Image: **Ubuntu 22.04**.
   - Shape: **VM.Standard.A1.Flex** (Ampere ARM, always-free — 1–4 OCPU / 6–24 GB)
     or **VM.Standard.E2.1.Micro** (always-free x86). ARM is roomier.
   - Download the SSH key when prompted.
3. Note the instance's **public IP**.

## 2. Open the firewall (two layers — both matter)

Oracle blocks traffic at the cloud network **and** the Ubuntu image ships
iptables rules that drop inbound. Open **80** and **443** in both:

- **Cloud:** VCN → the instance's subnet → Security List → add Ingress rules
  (Source `0.0.0.0/0`, TCP, dest ports `80` and `443`).
- **On the VM** (after SSH, step 3):
  ```bash
  sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save
  ```

## 3. SSH in and install Docker

```bash
ssh -i /path/to/key ubuntu@<PUBLIC_IP>

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && exit   # then SSH back in
```

## 4. Point a domain at the VM (free HTTPS needs a name)

Create a free subdomain at <https://www.duckdns.org> and set its IP to your
VM's public IP — e.g. `signalforge-demo.duckdns.org`.

## 5. Deploy

```bash
git clone https://github.com/dharmppp21/Worthy-One.git
cd Worthy-One/signalforge_mvp

cp deploy/.env.vm.example deploy/.env
nano deploy/.env        # set SF_DOMAIN=<your>.duckdns.org (and keep/replace the API key)

bash deploy/up.sh
```

Caddy fetches a Let's Encrypt certificate on first run (~30s). Then:

- **Dashboard:** `https://<your>.duckdns.org`
- **API / OTLP base:** `https://<your>.duckdns.org/api`

## 6. Point the clients at it

- **Mobile app:** Settings → Base URL `https://<your>.duckdns.org/api`, or build
  with `EXPO_PUBLIC_SIGNALFORGE_URL=https://<your>.duckdns.org/api`.
- **Instrument any service (OTel):**
  ```
  OTEL_EXPORTER_OTLP_ENDPOINT=https://<your>.duckdns.org/api
  OTEL_EXPORTER_OTLP_HEADERS=x-api-key=sf-api-key-demo
  OTEL_SERVICE_NAME=your-service
  ```

## Operating it

```bash
cd Worthy-One/signalforge_mvp
# logs:     docker compose -f docker-compose.yml -f deploy/docker-compose.vm.yml logs -f backend caddy
# update:   git pull && bash deploy/up.sh
# stop:     docker compose -f docker-compose.yml -f deploy/docker-compose.vm.yml down
```

Data (Postgres, Redis, Caddy certs) lives in named Docker volumes and survives
restarts and `git pull`.

## Notes

- Only 80/443 should be open in the cloud firewall. The base compose also
  publishes 8000/8080 on the VM, but with those ports closed in the Security
  List they're reachable only from the VM itself; Caddy is the public door.
- `ENVIRONMENT=production` means auth **fails closed** — `SIGNALFORGE_API_KEYS`
  must be set (it is, via `deploy/.env`).
