# Modelo de amenazas

**Activo principal:** la capacidad de ejecutar herramientas (shell, edición de archivos, red) en tu PC.
**Activos secundarios:** tu código, credenciales en disco, tus API keys, tu presupuesto en tokens.

## Supuestos

- La PC es de confianza (si está comprometida, Theyso no puede protegerte).
- Tu cuenta de Tailscale está protegida con 2FA.
- El celular tiene bloqueo de pantalla.

## Actores

| Actor | Capacidad |
|---|---|
| A1 Atacante en la misma red Wi-Fi / LAN | ve y envía tráfico local |
| A2 Otro dispositivo de tu tailnet (comprometido o compartido) | llega a la IP de Tailscale de tu PC |
| A3 Página web maliciosa abierta en tu PC o celular | hace peticiones desde el navegador |
| A4 Persona con tu celular desbloqueado o robado | usa la app |
| A5 Persona que fotografió el QR | conoce el secreto durante ≤ 2 min |
| A6 Contenido malicioso leído por el agente (inyección de prompts) | dirige al agente |
| A7 Otro usuario local de la PC | lee archivos con permisos laxos |

## STRIDE

| Amenaza | Actor | Mitigación | Riesgo residual |
|---|---|---|---|
| **S**uplantar al celular | A1, A2 | Firma Ed25519 por conexión; sin tokens portadores; dispositivo desconocido recibe el mismo desafío (no hay enumeración) | Bajo |
| **S**uplantar la PC | A1, A2 | El celular fija `server_pub` del QR y verifica la firma antes de firmar | Bajo |
| **S**e vincula un tercero | A5 | SAS verificado por una persona, aprobación en la PC, uso único, TTL corto | Bajo (si comparas el código) |
| **T**ampering en tránsito | A1 | WireGuard; la transcripción firmada liga ambos nonces y la clave del servidor | Bajo |
| **T**ampering de la política vía configuración local del agente | A6 | Hook `PreToolUse` aplica denegaciones a toda llamada | Bajo |
| **R**epudio | — | Auditoría con dispositivo, IP, decisión y quién decidió | Bajo |
| **I**nfo disclosure: secretos en la salida | A4 | Redacción en el servidor antes de enviar | Medio (formatos desconocidos) |
| **I**nfo disclosure: lectura de credenciales | A6 | Rutas protegidas denegadas para toda herramienta; comandos que las mencionan → riesgo alto | Medio (ofuscación en shell) |
| **I**nfo disclosure: archivos de Theyso | A7 | 0600/0700, escritura atómica, `theyso doctor` avisa | Bajo |
| **D**oS: inundación | A2 | Límite de mensajes, tamaño máximo, bloqueo por fallos | Bajo |
| **D**oS: permiso colgado | — | Timeout → denegar | Bajo |
| **E**levación: navegador habla con el servidor | A3 | Se rechaza cualquier `Origin`; Host debe ser la IP o `*.ts.net` (anti DNS rebinding) | Bajo |
| **E**levación: navegador habla con la API admin | A3 | 127.0.0.1 + token rotado + sin `Origin` | Bajo |
| **E**levación: celular robado aprueba acciones | A4 | Bloqueo biométrico al abrir; biometría para riesgo alto; `theyso revoke` corta al instante | Medio (acciones de riesgo medio) |
| **E**levación: escapar de la carpeta del proyecto | A6 | Carpetas permitidas con `resolve()`; escrituras fuera → riesgo alto | Bajo |
| **E**levación: el agente ejecuta algo dañino que apruebas | A6 | Clasificación de riesgo y diffs visibles antes de aprobar | **Alto** — depende de ti |

## Consideraciones conocidas

- **`tailscale serve`**: si el servidor escucha en 127.0.0.1 detrás de `tailscale serve`, todas las
  conexiones parecen venir de 127.0.0.1 y el bloqueo por IP pasa a ser global. Es aceptable para un
  solo usuario; el roadmap incluye leer la identidad de Tailscale (`Tailscale-User-Login`).
- **Clave del dispositivo exportable**: Ed25519 no está disponible en todo Keystore/Secure Enclave,
  así que la clave vive cifrada en el almacenamiento seguro, no en hardware. Roadmap: P-256 en
  StrongBox / Secure Enclave, no exportable.
- **Redacción ≠ DLP**: es una red de seguridad, no una garantía.
- **OpenCode**: el adaptador fuerza `edit/bash/webfetch = ask` vía `OPENCODE_CONFIG_CONTENT`;
  si una versión futura cambia esa variable, revisa el adaptador.
