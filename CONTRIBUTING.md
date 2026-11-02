# Contribuir

¡Gracias! Issues y PRs en español o inglés.

## Entorno

```bash
# servidor
cd server
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && mypy theyso

# app
cd app
python tool/setup.py      # solo la primera vez: carpetas nativas + parches + íconos
flutter test && flutter analyze
```

## Reglas

1. **Cambios de protocolo**: actualiza `docs/PROTOCOL.md`, `server/theyso/protocol.py` y la app en el mismo PR.
2. **Cambios criptográficos**: actualiza los vectores en `server/tests/test_vectors.py` **y** `app/test/crypto_test.dart`.
3. **Nunca** añadas un modo que salte los permisos, ni un endpoint público sin autenticación.
4. Un adaptador de agente nuevo debe pasar por `deny_check` y `ask` para toda acción con efectos.
5. Commits con [Conventional Commits](https://www.conventionalcommits.org/es/) (`feat:`, `fix:`, `docs:`, `sec:`).

## Vulnerabilidades

No las publiques en issues: ver [SECURITY.md](SECURITY.md).
