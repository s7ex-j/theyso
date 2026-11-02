# Protocolo v1

WebSocket en `/v1/ws`, tramas de texto JSON, una por mensaje. Toda trama tiene `type`.
Los mensajes del cliente se validan estrictamente: tipos desconocidos o campos extra → `error`.
Tamaño máximo por defecto: 256 KiB. Límite por defecto: 120 mensajes/minuto por conexión.

Codificación binaria: **base64url sin relleno** (`b64u`).

## 1. Handshake (obligatorio, primer intercambio)

| Dirección | Trama |
|---|---|
| → | `{"type":"auth.hello","v":1,"device_id":"dev_…","client_nonce":b64u(32 bytes)}` |
| ← | `{"type":"auth.challenge","v":1,"server_nonce":b64u(32),"signature":b64u(sig_s)}` |
| → | `{"type":"auth.response","signature":b64u(sig_c)}` |
| ← | `{"type":"auth.ok", server_name, server_version, protocol, profiles[], workspaces[], sessions[], limits{}}` |

```
T     = "theyso-auth-v1" | device_id | client_nonce | server_nonce | server_pub   ("|" = 0x7C)
sig_s = Ed25519_sign(server_key, "server|" ‖ T)
sig_c = Ed25519_sign(device_key, "client|" ‖ T)
```

El cliente **debe** verificar `sig_s` con la clave fijada en la vinculación antes de enviar `sig_c`.
Fallo → `{"type":"error","code":"auth_failed"}` y cierre `4401`. Varias fallas desde una IP → cierre `4429`.

## 2. Cliente → servidor

| `type` | Campos | Respuesta |
|---|---|---|
| `ping` | — | `pong` |
| `session.list` | — | `session.list.result {sessions, workspaces}` |
| `session.create` | `profile`, `workspace`, `title?`, `resume_agent_session?` | `session.created {session}` + `session.attached` |
| `session.attach` | `sid`, `after_seq` | `session.attached` + eventos con `seq > after_seq` + permisos pendientes |
| `session.detach` | `sid` | — |
| `session.close` | `sid` | `session.closed` |
| `prompt` | `sid`, `text` | eventos |
| `interrupt` | `sid` | eventos `status` |
| `model.set` | `sid`, `model \| null` | evento `notice` |
| `permission.reply` | `sid`, `request_id`, `decision: allow\|deny`, `message?`, `confirmed_strong` | evento `permission_resolved` |
| `usage.query` | `days` | `usage.result` |
| `panic` | — | `panic.ok {sessions_closed}` |

Todos aceptan un `id` opcional que el servidor devuelve en la respuesta o en el `error` (`ref`).

## 3. Servidor → cliente

### Eventos de sesión

```json
{"type":"event","sid":"s_…","seq":42,"ts":1761500000.1,"kind":"tool_use",
 "data":{"tool_use_id":"toolu_…","tool":"Bash","input":{"command":"pytest -q"}}}
```

| `kind` | `data` |
|---|---|
| `user` | `text`, `device_id` |
| `partial` | `stream_id`, `text` — respuesta a medio escribir. **Efímero**: sin `seq`, no se guarda ni se reproduce; el `text` final lo reemplaza. Se envía como mucho ~7 veces por segundo y solo hasta el último espacio (nunca media palabra). |
| `text` | `text` (markdown), `model?`, `part_id?` (si viene, reemplaza el contenido de esa parte) |
| `thinking` | `text`, `part_id?` |
| `tool_use` | `tool_use_id`, `tool`, `input` |
| `tool_result` | `tool_use_id`, `output` (recortado a 20 000 caracteres), `is_error`, `truncated` |
| `status` | `state`: `idle \| running \| waiting_permission \| error` |
| `result` | `ok`, `model`, `input_tokens`, `output_tokens`, `cost_usd?`, `duration_ms?` |
| `permission_resolved` | `request_id`, `allow`, `by`: `phone \| policy \| timeout \| system` |
| `notice` | `text`, … |
| `error` | `text` |

Cualquier `data` puede incluir `redactions: n` si se enmascararon secretos.

### Solicitud de permiso (no numerada, se reenvía en cada attach mientras esté abierta)

```json
{"type":"permission.request","sid":"s_…","request_id":"perm_…","tool":"Bash",
 "input":{"command":"git push origin main --force"},"risk":"high",
 "reason":"Command matches a high-risk rule","requires_strong_auth":true,"created":1761500000.0}
```

Si `requires_strong_auth` es `true`, el servidor rechaza un `allow` sin `confirmed_strong: true`
(`error.code = "forbidden"`). Sin respuesta en `permission_timeout_s` → denegado.

### Errores

`{"type":"error","code":"…","message":"…","ref":"<id del cliente>","sid":"<si el mensaje era de una sesión>"}`

| code | Significado |
|---|---|
| `auth_failed` | handshake inválido |
| `locked_out` | demasiados fallos desde tu IP |
| `rate_limited` | demasiados mensajes |
| `bad_request` | mensaje inválido |
| `not_found` | sesión/perfil/permiso inexistente |
| `forbidden` | carpeta no permitida, o falta confirmación fuerte |
| `agent_error` | el agente no arrancó o falló |
| `budget_exceeded` | se alcanzó `daily_budget_usd` del perfil |

### Códigos de cierre

`4400` Host/Origin no permitido · `4401` autenticación · `4403` dispositivo revocado ·
`4413` mensaje demasiado grande · `4429` bloqueado temporalmente.

## 4. HTTP

| Método | Ruta | Uso |
|---|---|---|
| GET | `/v1/health` | `{"ok":true,"v":1}` — nada más |
| POST | `/v1/pair` | ver [PAIRING.md](PAIRING.md) |

## Versionado

`v` en `auth.hello` y en el QR. Un cambio incompatible sube la versión y la ruta (`/v2/ws`).
