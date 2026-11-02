# Proveedores y modelos

Un **perfil** = qué agente + qué modelo + qué variables de entorno. Los secretos nunca van en el
archivo: usa `env:NOMBRE` y exporta la variable antes de `theyso serve`.

> Las URLs y nombres de modelo cambian seguido. Verifica siempre en la documentación del proveedor.

## Claude Code con cuenta oficial o API key de Anthropic

```toml
[profiles.claude]
agent = "claude-code"
```

Usa lo que ya tengas configurado en `claude` (login de claude.ai o `ANTHROPIC_API_KEY`).

## Claude Code vía router local (9Router, LiteLLM, claude-code-router…)

```toml
[profiles.router]
label = "Router local"
agent = "claude-code"
model = "id-del-modelo-en-tu-router"
fallback_model = "otro-id"          # opcional
daily_budget_usd = 2.0              # opcional: corta al llegar al tope (solo costos reales)
price_input_per_mtok = 0.0          # opcional: tu tarifa real → costos correctos
price_output_per_mtok = 0.0
[profiles.router.env]
ANTHROPIC_BASE_URL = "http://127.0.0.1:20128"   # puerto por defecto de 9Router; revisa su dashboard
ANTHROPIC_AUTH_TOKEN = "env:ROUTER_API_KEY"
```

Sin `price_*`, Theyso marca el costo como `list_equivalent`: lo que *habría* costado a precio
de lista de Anthropic. En la app se muestra como «equivalente a precio de lista», no como gasto.

## Claude Code vía OpenRouter

```toml
[profiles.openrouter]
agent = "claude-code"
model = "anthropic/claude-sonnet-4.5"
[profiles.openrouter.env]
ANTHROPIC_BASE_URL = "https://openrouter.ai/api"
ANTHROPIC_AUTH_TOKEN = "env:OPENROUTER_API_KEY"
ANTHROPIC_API_KEY = ""
```

## Claude Code vía un proveedor con API compatible con Anthropic (p. ej. DeepSeek)

```toml
[profiles.deepseek]
agent = "claude-code"
model = "deepseek-chat"
[profiles.deepseek.env]
ANTHROPIC_BASE_URL = "https://api.deepseek.com/anthropic"
ANTHROPIC_AUTH_TOKEN = "env:DEEPSEEK_API_KEY"
```

## OpenCode

```toml
[profiles.opencode]
agent = "opencode"
model = "proveedor/modelo"   # opcional; si no, usa el default de tu opencode.json
```

Theyso arranca un `opencode serve` privado por sesión (127.0.0.1, puerto aleatorio, contraseña
aleatoria) y fuerza permisos `ask` para editar, ejecutar y acceder a la red.

## Exportar las métricas

```bash
theyso usage export ./datos
# → theyso_turns.csv, theyso_tools.csv  (listos para pandas, DuckDB o Power BI)
```

## Uso responsable

Theyso no implementa rotación de cuentas, reutilización de tokens OAuth de suscripciones ni nada
para saltarse límites. Si tu router lo hace, revisa los términos de cada proveedor.
