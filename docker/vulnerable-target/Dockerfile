# =============================================================================
# Demo Vulnerable Target for SOC360 Pymes
# =============================================================================
# SAFETY: This image serves STATIC, FAKE, CLEARLY-LABELED service banners.
# It does NOT contain any real vulnerable software, exploitable services, or
# production workloads. It is gated behind the 'demo' Docker Compose profile
# and attaches only to an internal demo network.
# =============================================================================

FROM alpine:3.20

LABEL org.soc360.demo="true" \
      org.soc360.component="vulnerable-target" \
      org.soc360.simulated="true" \
      description="Demo-only simulated vulnerable target for Nmap scan walkthroughs"

# netcat-openbsd: used by entrypoint.sh to bind ports and serve banner files
RUN apk add --no-cache netcat-openbsd

# Banner files — static, fake service responses returned to connecting scanners
COPY banners/ /banners/

# Entrypoint script — binds ports and manages banner listeners
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Demo ports: 22 (SSH), 80 (HTTP), 21 (FTP), 3306(MySQL)
EXPOSE 22 80 21 3306

# Non-root for safety (even though there's nothing exploitable here)
RUN addgroup -S demo && adduser -S demo -G demo
USER demo

ENTRYPOINT ["/entrypoint.sh"]
