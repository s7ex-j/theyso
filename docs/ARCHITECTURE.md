# Arquitectura

## Vista general

```mermaid
flowchart LR
  subgraph Phone["Celular (Flutter)"]
    UI[Chat · permisos · uso]
    KS[(Keystore / Keychain<br/>clave Ed25519)]
  end
  subgraph PC["Tu PC"]
    subgraph Srv["theyso serve"]
      PUB["API pública<br/>IP Tailscale :8765"]
      ADM["API admin<br/>127.0.0.1 :8766"]
      SEC["Seguridad<br/>handshake · política · redacción"]
      SM["SessionManager<br/>buffer de eventos"]
      MET[(usage.sqlite)]
      AUD[(audit.jsonl)]
    end
    CLI["theyso pair / revoke / panic"]
    CC["claude (Agent SDK)"]
    OC["opencode serve<br/>127.0.0.1:random"]
    ROUTER["9Router / LiteLLM / OpenRouter…"]
  end
  UI <-- "WebSocket JSON<br/>sobre WireGuard" --> PUB
  CLI --> ADM
  PUB --> SEC --> SM
  SM --> CC --> ROUTER
  SM --> OC
  SM --> MET
  SEC --> AUD
```

## Decisiones clave

### 1. Agent SDK en lugar de pseudoterminal

La idea inicial era controlar la TUI de Claude Code con `node-pty`/`pexpect` y "limpiar"
los caracteres de control. Se descartó porque:

- la TUI se redibuja (spinners, cajas, menús) y el parseo se rompe con cada versión;
- los diálogos de permiso son texto, no datos: no hay forma robusta de saber qué herramienta y qué argumentos se están pidiendo;
- el Agent SDK ofrece exactamente lo que necesitamos: mensajes tipados, un callback `can_use_tool`, hooks `PreToolUse`, `interrupt()`, `set_model()`, reanudar sesiones y checkpoints de archivos.

El SDK lanza el mismo binario `claude`, así que `ANTHROPIC_BASE_URL` y demás variables de entorno funcionan igual que en la terminal.

### 2. Adaptadores por agente

`agents/base.py` define una interfaz mínima (`start`, `send`, `interrupt`, `set_model`, `close`) y un
formato de eventos normalizado (`text`, `thinking`, `tool_use`, `tool_result`, `status`, `result`, `notice`, `error`).
La app no sabe qué agente hay detrás. Añadir Codex CLI o Gemini CLI = un archivo nuevo.

### 3. Sin relay, Tailscale como transporte

Un relay (como usan Happy o Termopus) resuelve NAT pero introduce un tercero. Tailscale resuelve NAT con
conexiones directas WireGuard entre tus propios dispositivos, gratis para uso personal.
Theyso no confía *solo* en Tailscale: añade autenticación mutua a nivel de aplicación.

### 4. Dos APIs en el mismo proceso

| | Pública | Admin |
|---|---|---|
| Escucha en | IP de Tailscale | 127.0.0.1 |
| Autenticación | firma Ed25519 del dispositivo | token local (archivo 0600, rotado al arrancar) |
| Para | el celular | el CLI `theyso` en la PC |
| Puede aprobar vinculaciones | **no** | sí |

### 5. Eventos numerados y reproducción

Cada evento de una sesión lleva `seq`. El servidor guarda los últimos N (por defecto 1000) en un buffer
circular. Al reconectar, la app envía `session.attach {after_seq}` y recibe solo lo que perdió.
Las solicitudes de permiso pendientes se reenvían siempre.

### 6. Costos honestos con routers

Claude Code calcula `total_cost_usd` con los precios de lista de Anthropic *según el nombre del modelo*,
aunque la petición haya ido a un modelo gratis vía router. Theyso etiqueta cada turno con una
`cost_basis` (`reported`, `profile_price`, `list_equivalent`) para no mezclar gasto real con "ahorro".

## Flujo de un turno con permiso

```mermaid
sequenceDiagram
  participant P as Celular
  participant S as theyso
  participant A as Claude Code
  P->>S: prompt {sid, text}
  S->>A: client.query(text)
  A-->>S: AssistantMessage(tool_use Bash "git push --force")
  S-->>P: event tool_use
  A->>S: PreToolUse hook
  S->>S: política: ¿denegar siempre? → no
  A->>S: can_use_tool("Bash", {...})
  S->>S: política → ask, riesgo ALTO
  S-->>P: permission.request {risk: high, requires_strong_auth}
  P->>P: biometría
  P->>S: permission.reply {allow, confirmed_strong: true}
  S->>A: PermissionResultAllow
  A-->>S: ToolResultBlock
  S-->>P: event tool_result (redactado)
  A-->>S: ResultMessage (tokens, costo)
  S->>S: métricas + auditoría
  S-->>P: event result
```

## Persistencia en la PC (`~/.config/theyso/`, 0700)

| Archivo | Contenido | Sensible |
|---|---|---|
| `config.toml` | configuración (sin secretos) | bajo |
| `server_key.pem` | identidad Ed25519 del servidor | **alto** |
| `devices.json` | claves **públicas** de celulares vinculados | medio |
| `admin.token` | token de la API local (existe solo mientras corre) | alto |
| `audit.jsonl` | eventos de seguridad | medio |
| `usage.sqlite` | métricas de uso | bajo |
