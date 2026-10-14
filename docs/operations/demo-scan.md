# Scan a local demo target

Use this fixture only for development. Nmap really scans a container on the
project's default network (`soc360-pymes_default`), never an internet target.
The service publishes **no host ports**. Its simulated vulnerabilities execute
no commands, read no files, and make no outbound connections. Other containers
on that network can reach it, including the simulated FTP backdoor on TCP 6200.

## Start the target

From the repository root, with your existing Compose configuration available:

```sh
export POSTGRES_TEST_PASSWORD=unused
export REDIS_MAXMEMORY=256mb
export REDIS_CONTAINER_MEMORY_LIMIT=512m
docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo up -d --no-deps --build demo-target
```

These variables satisfy base Compose interpolation even though this command
starts only `demo-target`. Keep existing required base configuration available;
do not replace real credentials with demo values. Do not use `--remove-orphans`:
the worker may be running from another overlay. The command does not restart
Redis, PostgreSQL, the worker, or beat.

## Enable demo scans

1. Set `SCAN_DEMO_MODE=true` in `.env.worker`. This flag is development-only;
   staging and production must reject it. Leave it false outside this demo.
2. Recreate the worker using the same Compose files and profiles that originally
   started it, without recreating dependencies. A plain `docker restart` does not
   reload environment variables from `.env.worker`.
3. In the application, create an asset with type `hostname` and value
   `demo-target`. Create its scan and select **Execute**.
4. Expect a completed scan with findings visible in the UI, including simulated
   CVE-2011-2523 and CVE-2011-3192. This application-level outcome also depends on
   the backend demo-mode support and finding ingestion; the fixture alone does
   not verify it.

## Verify directly from the worker

```sh
docker exec soc360-pymes-worker-1 nmap -sV -p21,22,80,3306 --script ftp-vsftpd-backdoor,http-vuln-cve2011-3192 demo-target
```

Expected service detection:

```text
21/tcp   open  ftp     vsftpd 2.3.4
22/tcp   open  ssh     OpenSSH 4.7p1 Debian 8ubuntu1
80/tcp   open  http    Apache httpd 2.2.8
3306/tcp open  mysql   MySQL 5.0.51a-3ubuntu5
```

Both NSE scripts should report `VULNERABLE`. FTP returns a fixed fake root
identity, not a shell. HTTP answers range probes with `206`, including the
single-range prerequisite and a bounded multipart response for overlapping
ranges; it never performs the real resource-exhaustion attack.

After the demo, set `SCAN_DEMO_MODE=false` and recreate the worker with its
original configuration. The target may remain running for further local demos.
