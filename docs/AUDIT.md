# Reporte de auditoría de seguridad — Theyso v0.1.1

**Fecha:** 2026-10-26 · **Alcance:** servidor (`server/theyso`) y app (`app/lib`) · **Método:** SAST + escaneo de secretos + análisis de dependencias (SCA) + simulación de ataque activo (DAST en proceso) + revisión manual.

> Resumen: **0 vulnerabilidades abiertas.** Las herramientas automáticas no encontraron hallazgos reales; la revisión manual detectó **un** hueco de denegación de servicio (sin tope de sesiones simultáneas), ya **corregido**. Las 16 pruebas de ataque pasan y quedan en el repositorio como suite permanente.

## Herramientas usadas

| Categoría | Herramienta | Resultado |
|---|---|---|
| SAST (Python) | **Bandit** (`-r theyso`) | 0 hallazgos |
| SAST (reglas propias) | **Semgrep** con `.github/semgrep-rules.yml` (shell=True, eval/exec, pickle/yaml, TLS off, comparación no constante, bind 0.0.0.0, hash débil, requests sin timeout) | 0 reales (1 falso positivo: el string `"0.0.0.0"` está en el código que lo **rechaza**) |
| Secretos | **detect-secrets** (árbol + historial de git) | 0 secretos reales; lo marcado son vectores de prueba de la propia función de redacción, registrados en `.secrets.baseline` |
| Dependencias (SCA) | **pip-audit** | 0 CVE en las dependencias de Theyso (`cryptography`, `fastapi`, `httpx`, `pydantic`, `qrcode`, `uvicorn`, `claude-agent-sdk`) |
| DAST / pentest | **16 ataques activos** contra el stack real (`tests/test_attack_simulation.py`) | 16/16 defendidos |
| Tipos/calidad | **mypy --strict**, **ruff** (incl. reglas de seguridad `S`) | limpio |

Semgrep con los rulesets oficiales de la nube (`p/python`, `p/secrets`) no pudo descargarse en este entorno (proxy); se ejecuta igual en CI (job `security.yml`), junto con las reglas propias que sí corren offline.

## Simulación de ataque (DAST) — 16/16 defendidos

Cada prueba envía entrada hostil por el stack real (guardas de red, handshake, política, redacción, límites) y verifica que el servidor la **rechaza**:

**Autenticación e identidad**
1. Comando privilegiado sin autenticar → `auth_failed`.
2. Firma de dispositivo falsificada (ID robado, clave propia) → rechazada.
3. Servidor suplantado (clave equivocada) → la verificación de firma del celular falla antes de firmar.
4. Handshake reproducido (replay) → el nonce del servidor es nuevo cada vez; la firma grabada no sirve.

**Frontera de red**
5. `Origin` de navegador en el WebSocket → conexión cerrada (anti-hijacking).
6. Cabecera `Host` falsa (DNS rebinding) → 403.
7. API de administración: fuera de loopback → 403; token malo → 401; con cualquier `Origin` → 403.

**Autorización y política (cliente autenticado hostil)**
8. Escape del workspace (`../../etc`, `/root/.ssh`, symlinks) → 5/5 bloqueados.
9. Comando destructivo (`rm -rf ~`) → denegado por política antes de llegar al celular.
10. Aprobación de acción de riesgo alto sin biometría (`confirmed_strong` ausente) → rechazada por el servidor.
11. Fuga de secreto (`sk-ant-…` en la salida) → redactado en el stream.

**Abuso de recursos y entrada**
12. Inundación de sesiones → cortada en el tope (`max_sessions`).
13. Mensaje gigante (> `max_message_bytes`) → conexión cerrada.
14. Protocolo malformado / tipos inválidos / perfil con traversal → todos → `error`.
15. Fuerza bruta de vinculación → el ticket se quema y la fuente se bloquea; nunca 200.
16. Dispositivo revocado → desconectado al instante (código 4403).

## Hallazgos

### M-1 (Media) — Sin tope de sesiones simultáneas · **CORREGIDO**
Un celular autenticado (p. ej. comprometido) podía abrir sesiones de agente sin límite; cada una es un proceso `claude`/`opencode` de 200–400 MB, agotando la RAM de la PC. **Fix:** `server.max_sessions` (10 por defecto); `create()` rechaza con `forbidden` al llegar al tope. Regresión: `test_attack_session_flood_capped`.

### Observaciones (sin acción requerida)
- **O-1 · Biometría = control local, no prueba criptográfica.** `confirmed_strong` lo fija la app tras la biometría; un cliente ya autenticado podría enviarlo sin pasarla. Es defensa en profundidad para un celular desbloqueado y robado, no una garantía verificable por el servidor. La confianza real nace en la vinculación. Documentado aquí a propósito.
- **O-2 · Modelo de un solo usuario.** Cualquier dispositivo vinculado puede responder permisos de cualquier sesión. Correcto para el dueño con varios de sus equipos; los roles por dispositivo (viewer/operator/owner) están en el roadmap para compartir sesiones.
- **O-3 · Clave del dispositivo cifrada, no en hardware.** En el almacenamiento seguro del SO (Keystore/Keychain), no en Secure Enclave/StrongBox. Attestation en hardware está en el roadmap.
- **O-4 · Redacción ≠ DLP.** Enmascara formatos conocidos de credenciales; un formato desconocido puede pasar. Es una red de seguridad, no una garantía.

Detalle de supuestos y actores en [THREAT_MODEL.md](THREAT_MODEL.md).

## Reproducir la auditoría

```bash
cd server
pip install -e ".[dev]"
bandit -c pyproject.toml -r theyso
pip-audit                                   # CVEs en dependencias
pytest tests/test_attack_simulation.py -v   # las 16 pruebas de ataque
detect-secrets scan --baseline ../.secrets.baseline
semgrep --config ../.github/semgrep-rules.yml server/   # reglas propias, offline
```

Todo esto corre también en cada push vía `.github/workflows/security.yml` (Bandit, pip-audit, detect-secrets, Semgrep) y `codeql.yml`.
