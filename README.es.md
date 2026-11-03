<div align="center">

<img src="docs/brand/icon-rounded.png" width="112" alt="Logo de Theyso">

# Theyso

**Controla Claude Code u OpenCode de tu PC desde el celular — con cualquier modelo, sin servidores intermedios y sin depender de una suscripción.**

[English](README.md) · [Arquitectura](docs/ARCHITECTURE.md) · [Seguridad](SECURITY.md) · [Protocolo](docs/PROTOCOL.md) · [Roadmap](docs/ROADMAP.md)

<video src="https://github.com/s7ex-j/theyso/raw/main/docs/brand/demo.mp4" controls muted width="760"></video>

<sub>▶ Resumen de 48 segundos — si el reproductor no carga, <a href="https://github.com/s7ex-j/theyso/raw/main/docs/brand/demo.mp4">abre el clip</a>.</sub>

</div>

> Tu celular, tu PC y una línea directa entre ellos: por tu propia red privada
> y sin pasar por el servidor de nadie más.

## ¿Por qué otro más?

Ya existen formas de usar Claude Code desde el celular: el **Remote Control** oficial de Anthropic y apps comunitarias como **Happy**, **Termopus** o **Claude Remote**. Theyso apunta a un hueco concreto:

- **Modelos alternativos como ciudadanos de primera clase.** El Remote Control oficial exige iniciar sesión con claude.ai (Pro/Max) y no acepta API keys. Theyso funciona con cualquier endpoint compatible con Anthropic (9Router, LiteLLM, OpenRouter, DeepSeek…) mediante **perfiles** que eliges al abrir cada sesión.
- **OpenCode además de Claude Code** (experimental), con la misma interfaz y las mismas políticas.
- **Sin relay.** El tráfico va solo del celular a tu PC, cifrado por WireGuard (Tailscale) y con autenticación mutua Ed25519 encima.
- **Analítica de uso que entiende los modelos gratis.** Distingue el gasto real del «equivalente a precio de lista» cuando usas un router; muestra tokens por modelo, herramientas más usadas y cuánto tardas en aprobar.
- **Respuestas en vivo**: el texto aparece mientras el agente escribe (nunca media palabra, así nunca medio secreto).
- **Dictado sin conexión**: hablas, se transcribe en el celular y solo llena la caja; tú presionas enviar.
- **Pantalla privada**: sin capturas, miniatura en blanco en «apps recientes», bloqueo con huella.
- **Mantiene la PC despierta solo mientras haya una sesión abierta y esté enchufada.**
- **Ligero**: el servidor usa ~55 MB de RAM en reposo; la app no corre en segundo plano.
- **Motor de políticas.** Bloquea `rm -rf ~` antes de que llegue a ti, y pide tu huella para `git push --force`, `sudo` o escrituras fuera del proyecto.

## Inicio rápido

**En la PC** (Python 3.11+, [Tailscale](https://tailscale.com) instalado y con sesión iniciada):

```bash
pipx install "git+https://github.com/s7ex-j/theyso#subdirectory=server"
theyso init                # config.toml, clave del servidor y secrets.env (tus API keys)
# edita [workspaces].allowed y tus [profiles.*]
theyso doctor              # revisa Tailscale, agentes y permisos de archivos
theyso serve               # escucha SOLO en tu IP de Tailscale
theyso pair                # (en otra terminal) muestra el QR
theyso service install     # opcional: que arranque solo al iniciar sesión
```

**En el celular:** instala Tailscale con la misma cuenta, compila la app (`cd app && python tool/setup.py`, ver [app/README.md](app/README.md)) o descarga el APK de la última ejecución de GitHub Actions, toca **Vincular PC**, escanea, compara el código de 6 dígitos y aprueba en la PC.

## Seguridad, en resumen

- Solo escucha en loopback o en IPs de Tailscale; `0.0.0.0` exige activarlo explícitamente.
- Vinculación: secreto de 256 bits en un QR que dura 2 minutos, prueba HMAC atada a la clave del celular, código de 6 dígitos verificado por una persona, uso único, se quema tras 5 intentos fallidos.
- Cada conexión: desafío-respuesta Ed25519 mutuo con nonces nuevos; el celular fija (pin) la clave de la PC.
- `bypassPermissions` está prohibido por validación de configuración. Los permisos sin respuesta se **deniegan** tras un tiempo.
- Las credenciales (API keys, tokens, claves privadas, valores de `.env`) se enmascaran antes de salir de la PC.
- Botón de pánico en el celular y `theyso panic` en la PC; `theyso revoke` corta al instante la conexión de un dispositivo.
- Registro de auditoría solo-anexar (los prompts se guardan como hash por defecto).

Detalles: [SECURITY.md](SECURITY.md) y [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md).

## Sobre los routers de terceros

Theyso solo pasa al agente las variables de entorno que **tú** configuras; no incluye rotación de cuentas, ni reutilización de tokens de suscripción, ni nada para saltarse los límites de un proveedor. Algunos routers ofrecen funciones de ese tipo que pueden incumplir los términos del proveedor original: esa decisión y su riesgo son tuyos.

## Licencia

MIT © Jharol André Vilca Ramos
