# Seguridad

Theyso le da a un celular la capacidad de pedirle a un agente que ejecute comandos en tu PC.
Eso es, en la práctica, **ejecución remota de código por diseño**. Este documento explica cómo
se acota ese poder. El análisis completo de amenazas está en [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md), y el reporte de la auditoría (SAST, secretos, dependencias y 16 pruebas de ataque) en [docs/AUDIT.md](docs/AUDIT.md).

## Reportar una vulnerabilidad

No abras un issue público. Usa **GitHub → Security → Report a vulnerability** (aviso privado)
en este repositorio. Respuesta inicial en 72 h; publicamos el aviso con crédito cuando haya parche.

## Capas de defensa

| # | Capa | Qué evita | Dónde |
|---|------|-----------|-------|
| 1 | **Red**: solo loopback o IP de Tailscale | Que alguien en el mismo Wi-Fi llegue al puerto | `security/network.py` |
| 2 | **Host / Origin**: Host debe ser la IP o `*.ts.net`; cualquier `Origin` se rechaza | DNS rebinding y secuestro de WebSocket desde un navegador | `security/network.py`, `app.py` |
| 3 | **Vinculación QR + SAS** | Que alguien que fotografió el QR se vincule sin que lo notes | `security/pairing.py` |
| 4 | **Autenticación mutua Ed25519** en cada conexión | Suplantar al celular o a la PC; reproducir un handshake grabado | `security/handshake.py` |
| 5 | **Bloqueo por fallos** + límite de mensajes por minuto | Fuerza bruta e inundación | `security/ratelimit.py` |
| 6 | **Validación estricta** de cada mensaje (pydantic, campos extra prohibidos, tamaño máximo) | Entradas malformadas | `protocol.py` |
| 7 | **Carpetas permitidas** (con resolución de symlinks) | Abrir una sesión en `~` o `/` | `sessions.py` |
| 8 | **Política de herramientas**: denegar siempre / riesgo alto con biometría / preguntar / permitir lectura | `rm -rf ~`, leer `~/.ssh`, `git push --force` sin querer | `security/policy.py` |
| 9 | **Hook PreToolUse** que aplica las denegaciones a TODA llamada, aunque el CLI la autoapruebe | Saltarse la política por la configuración local del agente | `agents/claude_code.py` |
| 10 | **Redacción de secretos** en todo lo que sale hacia el celular | Filtrar API keys en un `cat .env` o un traceback | `security/redact.py` |
| 11 | **Sin bypass**: `bypassPermissions` / `dontAsk` rechazados al cargar la config | Modo «YOLO» accidental | `config.py` |
| 12 | **Timeout = denegar** | Que un permiso quede abierto indefinidamente | `sessions.py` |
| 13 | **Revocación inmediata y botón de pánico** | Celular perdido o sesión descontrolada | `app.py`, `cli.py` |
| 14 | **Auditoría** JSONL 0600, prompts como hash | Reconstruir qué pasó sin duplicar tu código | `security/audit.py` |
| 15 | **Archivos privados** (0600/0700, escritura atómica) | Otros usuarios de la PC leyendo claves | `security/fs.py` |
| 16 | **Streaming seguro**: el texto parcial se envía solo hasta el último espacio y pasa por la redacción | Que medio API key salga antes de poder reconocerla | `agents/base.py` (`safe_prefix`) |
| 17 | **Pantalla privada** en la app: `FLAG_SECURE` (Android) + cubierta al salir (iOS/Android) | Capturas, grabación de pantalla, miniaturas en «recientes» | `app/lib/core/privacy.dart` |
| 18 | **Dictado solo en el dispositivo** (`onDevice: true`) y solo llena la caja | Audio enviado a la nube; órdenes mal oídas ejecutadas | `app/lib/core/dictation.dart` |
| 20 | **Tope de sesiones** simultáneas | Agotar la RAM de la PC abriendo agentes sin fin | `sessions.py` (`max_sessions`) |
| 21 | **16 pruebas de ataque** en CI | Que un cambio reabra un hueco sin que nadie lo note | `tests/test_attack_simulation.py` |
| 19 | **API de administración** solo en 127.0.0.1, token rotado en cada arranque, sin `Origin` | Que el celular o un navegador aprueben vinculaciones | `app.py` |

## Lo que Theyso NO protege

- **Un agente con permisos legítimos puede hacer daño legítimo.** Si apruebas `npm install paquete-malicioso`, se instala. La política reduce errores; no sustituye tu criterio.
- **Inyección de prompts** desde archivos o páginas que el agente lee. Mitigación parcial: las acciones con efectos siguen requiriendo tu aprobación.
- **Una PC ya comprometida.** Quien tenga shell como tu usuario puede leer la clave del servidor y la API de administración.
- **Tu cuenta de Tailscale.** Protégela con 2FA y usa ACLs para que solo tu celular llegue al puerto de Theyso.

## Recomendaciones de despliegue

1. Activa 2FA en Tailscale y una ACL como:
   ```json
   { "acls": [{ "action": "accept", "src": ["tag:phone"], "dst": ["tag:dev-pc:8765"] }] }
   ```
2. Para TLS además de WireGuard: `tailscale serve --bg --https=443 http://127.0.0.1:8765`, pon `host = "127.0.0.1"` y `public_url = "wss://tu-pc.tu-tailnet.ts.net"`.
3. Mantén `audit_prompts = "hash"` salvo que necesites el texto completo.
4. Revisa `theyso audit` de vez en cuando y `theyso devices` cuando cambies de celular.
