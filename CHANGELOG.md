# Changelog

## [0.1.2] — sin publicar

### Seguridad
- Auditoría completa (Bandit, Semgrep con reglas propias, detect-secrets, pip-audit): 0 hallazgos abiertos. Ver `docs/AUDIT.md`.
- **max_sessions**: tope de sesiones simultáneas para evitar agotar la RAM de la PC (hallazgo M-1).
- 16 pruebas de ataque activas en `tests/test_attack_simulation.py` + workflow `security.yml` en CI.
- `.secrets.baseline` para detect-secrets.

### Cambiado
- El proyecto se llama ahora **Theyso** (antes «Tether»). Comando `theyso`, `~/.config/theyso`, esquema `theyso://`, contextos `theyso-*-v1` (los QR anteriores dejan de valer).

Formato: [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) · Versionado: [SemVer](https://semver.org/lang/es/).

## [0.1.1] — sin publicar

### Cambiado
- (Histórico) El proyecto pasó por los nombres «Chasqui» y «Tether» antes de quedar en **Theyso** (v0.1.2).

### Añadido
- `keep_awake`: evita la suspensión solo con sesiones abiertas y cargador conectado.
- `theyso service install|uninstall` y lectura de `secrets.env`; `serve --log-file`.
- Texto en streaming, efímero y sin fugas de medias palabras.
- App: ajustes, pantalla privada (`FLAG_SECURE`), vibración y alertas de permisos, dictado offline,
  logo, ícono, splash, paleta violeta → cian, `tool/setup.py`.

### Corregido
- Al reabrir un chat el historial aparecía vacío.
- Un celular sin bloqueo de pantalla quedaba fuera de la app.
- Los errores de una sesión no llegaban al chat.

## [0.1.0] — sin publicar

### Añadido
- Servidor `theyso` (Python): API pública sobre Tailscale y API admin en loopback.
- Vinculación por QR con secreto de un solo uso, prueba HMAC y código de verificación de 6 dígitos.
- Autenticación mutua Ed25519 por conexión.
- Adaptadores: Claude Code (Agent SDK) y OpenCode (experimental).
- Perfiles de proveedor/modelo con secretos desde variables de entorno.
- Política de herramientas, hook PreToolUse, confirmación fuerte para riesgo alto.
- Redacción de secretos, auditoría JSONL, botón de pánico, revocación.
- Métricas de uso en SQLite con base de costo explícita; exportación CSV.
- App Flutter: vinculación, chat, herramientas, diffs, permisos, panel de uso.
