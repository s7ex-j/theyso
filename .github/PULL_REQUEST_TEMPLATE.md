## Qué cambia

## Checklist

- [ ] Tests (`pytest`, `flutter test`) pasan
- [ ] Si cambia el protocolo: `docs/PROTOCOL.md`, `protocol.py` y la app actualizados
- [ ] Si cambia criptografía: vectores actualizados en `server/tests/test_vectors.py` **y** `app/test/crypto_test.dart`
- [ ] Ninguna acción con efectos se salta `deny_check` / `ask`
- [ ] No se registran ni envían secretos
