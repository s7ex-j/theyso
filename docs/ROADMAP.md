# Roadmap e ideas

Leyenda: ✅ hecho en v0.1 · 🎯 próximo · 💡 idea abierta (se aceptan PRs)
**★** = algo que, hasta donde sabemos, ninguna alternativa ofrece hoy.

## v0.1 — base segura ✅

- ✅ Servidor Python con API pública (Tailscale) y API admin (loopback)
- ✅ Vinculación QR + código de 6 dígitos + aprobación en la PC
- ✅ Autenticación mutua Ed25519 en cada conexión, pinning de la clave del servidor
- ✅ Adaptador Claude Code (Agent SDK) y OpenCode (HTTP + SSE, experimental)
- ✅ Perfiles por proveedor/modelo; cambio de modelo en caliente
- ✅ Política de herramientas + hook `PreToolUse` + biometría para riesgo alto
- ✅ Redacción de secretos, auditoría, botón de pánico, revocación inmediata
- ✅ Reconexión con reproducción de eventos (`after_seq`)
- ✅ Métricas en SQLite con `cost_basis` honesto; pantalla de uso; exportación CSV
- ✅ App Flutter: chat, tarjetas de herramientas, diffs de edición, permisos, uso

## v0.1.2 — endurecimiento ✅

- ✅ Auditoría de seguridad: Bandit, Semgrep (reglas propias), detect-secrets, pip-audit → 0 hallazgos abiertos
- ✅ Tope de sesiones simultáneas (`max_sessions`) contra agotamiento de RAM
- ✅ 16 pruebas de ataque activas (`tests/test_attack_simulation.py`) + job `security.yml` en CI
- ✅ Reporte en [AUDIT.md](AUDIT.md)

## v0.1.1 — pulido ✅

- ✅ Renombre a **Theyso**, logo, ícono, splash y nueva paleta
- ✅ PC despierta solo con sesiones abiertas y cargador conectado (`keep_awake`)
- ✅ `theyso service install` (systemd / launchd / Programador de tareas) + `secrets.env`
- ✅ Respuestas en vivo (streaming seguro, con throttle)
- ✅ Pantalla de ajustes, pantalla privada, vibración al pedir permiso, alertas desde la lista
- ✅ Dictado offline en el celular (modo A de [VOICE.md](VOICE.md))
- ✅ `tool/setup.py`: genera y parchea las carpetas nativas en un paso

## v0.2 — día a día 🎯

- 🎯 **Notificaciones push sin Firebase**: publicar en un servidor [ntfy](https://ntfy.sh) propio
  (o en el del tailnet) cuando el agente pide permiso o termina. Sin cuentas de Google/Apple de por medio. ★
- 🎯 **Deshacer el último turno**: el Agent SDK ya expone checkpoints de archivos (`rewind_files`);
  un botón «↶ volver a antes de este mensaje» en el chat.
- 🎯 **Cola offline**: escribir prompts sin señal; se envían al reconectar, en orden.
- 🎯 **Macros por proyecto**: `.theyso/macros.toml` en el repo («corre tests», «revisa seguridad»…),
  que aparecen como chips en el chat.
- 🎯 **Adjuntar fotos**: captura de un bug o foto de la pizarra → imagen al agente.
- 🎯 **Voz, modo B**: whisper.cpp en la PC y lectura en voz alta de resúmenes; ver [VOICE.md](VOICE.md).
- 🎯 **i18n** es / en / pt con ARB.

## v0.3 — lo que nadie más hace 💡

- 💡 **Arena de modelos** ★ — el mismo prompt a 2–3 perfiles en paralelo, cada uno en su propio
  `git worktree`. Al final, tabla comparativa: tests que pasan, líneas cambiadas, tokens, costo,
  tiempo. Eliges el ganador desde el celular y se fusiona su worktree. Ideal para decidir si un
  modelo gratis vía router «alcanza» para tu proyecto, con datos y no con intuición.
- 💡 **Observatorio de agentes** ★ — exportación a Parquet + plantilla de Power BI / Looker Studio /
  notebook con métricas de productividad: tasa de denegación por herramienta, tiempo humano de
  aprobación, tokens por tarea, modelo que más resuelve, costo por commit. (La parte de datos del proyecto.)
- 💡 **Detección de fallback del router** ★ — comparar el modelo pedido con el que reporta la respuesta
  y avisar «9Router cambió de kr/… a glm-… en este turno».
- 💡 **Roles por dispositivo** ★ — `viewer` (solo ve), `operator` (aprueba riesgo bajo/medio),
  `owner` (todo). Útil para compartir una sesión con un compañero en modo lectura.
- 💡 **Cuarentena automática** — si el agente intenta 3 acciones denegadas seguidas, pausa la sesión
  y te avisa (posible inyección de prompts).
- 💡 **Git desde el celular** — diff acumulado, staging por bloques, commit, rama, PR con `gh`.
- 💡 **Vista previa en vivo** — abrir `localhost:3000` de la PC en el celular a través del túnel,
  con allowlist de puertos.
- 💡 **Más agentes** — Codex CLI, Gemini CLI, Aider (un adaptador cada uno).
- 💡 **Presupuestos avanzados** — topes por semana y por proyecto; alerta al 80 %.

## v1.0 — endurecimiento

- 💡 Clave del celular en hardware (StrongBox / Secure Enclave, P-256, no exportable) + attestation.
- 💡 Leer la identidad de Tailscale (`tailscale whois`) como segundo factor por conexión.
- 💡 Releases firmadas (Sigstore), SBOM, `pip-audit` y `osv-scanner` en CI, builds reproducibles.
- 💡 App de bandeja para la PC (QR en ventana, aprobar con un clic).
- 💡 Auditoría externa del protocolo.
