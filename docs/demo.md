# Demo Vulnerable Target — Operator Guide

> **⚠️ IMPORTANTE**: Este es un target **SIMULADO**. No contiene software vulnerable real, exploits, ni servicios productivos. Sus banners y respuestas son completamente falsos y predecibles. Está diseñado exclusivamente para demos, walkthroughs y presentaciones a clientes.

## ¿Qué es?

Un contenedor Docker aislado que expone puertos 22 (SSH), 80 (HTTP), 21 (FTP) y 3306 (MySQL) con banners falsos y predecibles, para que los escaneos Nmap de F2 produzcan resultados consistentes durante demostraciones.

## Cómo habilitarlo

El target está **apagado por defecto** y solo se activa con el perfil `demo`:

```bash
# Arrancar el target (Compose también levanta servicios sin perfil, como Redis)
docker compose --profile demo up -d

# Arrancar con todos los servicios (dev + demo)
docker compose --profile dev --profile demo up -d
```

## Verificar que funciona

El script de verificación automatizada comprueba que todo está correcto:

```bash
bash tests/verify_demo_target.sh
```

Este script valida:
1. Que el target **NO** arranca sin `--profile demo`
2. Que el target **SÍ** arranca con `--profile demo`
3. Que los puertos 22, 80, 21, 3306 responden con los banners esperados
4. Que **NO** hay puertos expuestos al host
5. Que el contenedor tiene etiquetas de seguridad (`demo=true`, `simulated=true`)

## Salida esperada de un escaneo Nmap

Cuando se ejecuta Nmap desde F2 (conectado a `soc360-pymes_demo_network`), el resultado será similar a:

```
PORT    STATE SERVICE VERSION
21/tcp  open  ftp     vsFTPd 3.0.5 [DEMO-SIMULATED]
22/tcp  open  ssh     OpenSSH 9.6p1 (Ubuntu) [DEMO-SIMULATED]
80/tcp  open  http    Apache httpd 2.4.62 (Unix) [DEMO-SIMULATED]
3306/tcp open mysql   MySQL 5.7.44-log Community Server [DEMO-SIMULATED]
```

> Los banners siempre incluyen el sufijo `[DEMO-SIMULATED]` para que no haya confusión con servicios reales.

## Cómo apagarlo

```bash
# Apagar solo el perfil demo
docker compose --profile demo down

# Apagar todo
docker compose down
```

## Validación de seguridad (pre-presentación)

Antes de una presentación o walkthrough con un cliente, verificá:

| Check | Comando | Resultado esperado |
|-------|---------|-------------------|
| Solo arranca con perfil | `docker compose up -d` → `docker compose ps` | `vulnerable-target` NO aparece |
| Sin puertos host | `docker compose port vulnerable-target 22` | `:0` (expuesto pero no publicado) |
| Banners correctos | `bash tests/verify_demo_target.sh` | 11/11 PASSED |
| Etiquetas de seguridad | `docker inspect soc360_demo_vulnerable_target \| grep -i demo` | `demo=true`, `simulated=true` |

## Arquitectura

```
┌─────────────────────────────────────────────┐
│  Host                                       │
│  ┌───────────────────────────────────────┐  │
│  │  soc360-pymes_demo_network (bridge)   │  │
│  │                                       │  │
│  │  ┌──────────────────────────┐           │  │
│  │  │ vulnerable-target         │           │  │
│  │  │ ports: 22, 80, 21, 3306   │           │  │
│  │  │ (internal only)           │           │  │
│  │  └──────────────────────────┘           │  │
│  │                                       │  │
│  │  ┌─────────────────────┐              │  │
│  │  │ F2 scanner          │              │  │
│  │  │ (same network)      │              │  │
│  │  └─────────────────────┘              │  │
│  └───────────────────────────────────────┘  │
│                                             │
│  ❌ No host port mapping                    │
│  ❌ No external access                      │
└─────────────────────────────────────────────┘
```

## Preguntas frecuentes

**¿Puedo exponer el target al host para debuggear?**
Sí, pero no por defecto. Si necesitás acceso desde el host para debug, agregá temporalmente un `ports:` mapping en `docker-compose.yml` y **acordate de quitarlo antes de hacer commit**. El perfil `demo` está diseñado para ser seguro out-of-the-box.

**¿Los banners son reales?**
No. Son archivos de texto estáticos (`docker/vulnerable-target/banners/*.banner`) que se sirven vía netcat. No hay Apache, OpenSSH, ni vsFTPd reales ejecutándose.

**¿Puedo usar esto en producción?**
**NO.** Este target es exclusivamente para demostraciones. No representa un entorno real y no debe usarse para pruebas de seguridad reales. Si llegara a aparecer en un entorno productivo, el guard rail de perfil (`profiles: [demo]`) impide que arranque accidentalmente.

**¿Qué pasa si alguien hace un escaneo agresivo?**
Como los servicios son emulados (netcat sirviendo archivos de texto), no hay riesgo de derribar servicios reales ni de explotar vulnerabilidades. En el peor caso, netcat se reinicia automáticamente (está en un loop `while true`).

## Archivos relevantes

| Archivo | Propósito |
|---------|-----------|
| `docker/vulnerable-target/Dockerfile` | Imagen Alpine con netcat-openbsd |
| `docker/vulnerable-target/entrypoint.sh` | Script que levanta los listeners |
| `docker/vulnerable-target/banners/*.banner` | Banners falsos servidos por netcat |
| `docker-compose.yml` (servicio `vulnerable-target`) | Definición del servicio + perfil `demo` |
| `tests/verify_demo_target.sh` | Suite de verificación automatizada |
| `docs/demo.md` | Este documento |
