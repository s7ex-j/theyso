# Dejar la PC lista

## Lo automático (recomendado)

```bash
theyso service install   # arranca Theyso al iniciar sesión (Linux, macOS o Windows)
```

Y en `config.toml`, que ya viene así por defecto:

```toml
[server]
keep_awake = "sessions"     # no dormir mientras haya una sesión del agente abierta
keep_awake_ac_only = true   # …y solo con el cargador conectado
```

Con eso Theyso **sujeta un bloqueo de "no suspender" solo mientras trabaja**: lo toma cuando abres
la primera sesión, lo suelta al cerrar la última o al desconectar el cargador (lo revisa cada minuto).
La pantalla sí se apaga y se bloquea; el servidor sigue funcionando con la sesión bloqueada.

| Sistema | Mecanismo |
|---|---|
| Windows | `SetThreadExecutionState(ES_SYSTEM_REQUIRED)` |
| macOS | `caffeinate -i -s` (`-s`: solo con corriente) |
| Linux | `systemd-inhibit --what=sleep:idle` |

Las API keys van en `~/.config/theyso/secrets.env` (Windows: `%APPDATA%\theyso\secrets.env`),
una por línea `CLAVE=valor`. `theyso init` lo crea con permisos 0600 y `theyso serve` lo lee solo.

> Mantén el bloqueo de pantalla y la contraseña de inicio de sesión. Que la PC no se duerma no
> significa que deba quedar desbloqueada.

## Lo que Theyso no puede hacer por ti: cerrar la tapa (laptops)

Al cerrar la tapa, el sistema operativo suspende la laptop aunque haya un bloqueo activo. Si
quieres usarla con la tapa cerrada y enchufada:

**Windows** (PowerShell como administrador):

```powershell
# Cerrar la tapa con cargador = no hacer nada
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
```

**macOS**: con la tapa cerrada solo sigue despierta con monitor externo, teclado y corriente
(modo «clamshell»). No hay ajuste oficial para hacerlo sin monitor.

**Linux** (systemd-logind):

```bash
sudo sed -i 's/^#\?HandleLidSwitchExternalPower=.*/HandleLidSwitchExternalPower=ignore/' /etc/systemd/logind.conf
sudo systemctl restart systemd-logind
```

## Si prefieres no usar `keep_awake`

Pon `keep_awake = "never"` y ajusta la energía a mano:

- **Windows**: `powercfg /change standby-timeout-ac 0` y `powercfg /change hibernate-timeout-ac 0`
- **macOS**: `sudo pmset -c sleep 0 displaysleep 10`
- **Linux (GNOME)**: `gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'`

## Que corra aunque no hayas iniciado sesión (solo Linux)

```bash
sudo loginctl enable-linger $USER
```

## Tailscale

Debe arrancar con el sistema (es lo predeterminado en Windows y macOS; en Linux:
`sudo systemctl enable --now tailscaled`). Activa 2FA en tu cuenta de Tailscale.

## Recursos que consume

| Componente | RAM aprox. | Nota |
|---|---|---|
| `theyso serve` en reposo | **≈ 55 MB** | medido en v0.1 (Python 3.13) |
| por cada sesión de Claude Code | 200–400 MB | es el propio CLI `claude` (Node.js), no Theyso |
| por cada sesión de OpenCode | 150–300 MB | ídem |
| Tailscale | 30–60 MB | |
| App en el celular | 80–150 MB | típico de Flutter; sin servicios en segundo plano |

Las sesiones inactivas y sin nadie conectado se cierran solas tras 6 h (`idle_session_timeout_s`),
y con ellas se libera también el bloqueo de suspensión.
