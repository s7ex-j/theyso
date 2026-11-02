# Theyso — app móvil (Flutter)

## Opción A: sin instalar nada (Android)

Sube el repo a GitHub. El workflow **app** compila un APK de depuración en cada push:
*Actions → app → la última ejecución → Artifacts → `theyso-debug-apk`*. Descárgalo en el
celular e instálalo (permite «instalar apps desconocidas» para tu navegador o gestor de archivos).

## Opción B: compilar en tu PC

Requisitos: [Flutter](https://docs.flutter.dev/get-started/install) (incluye Dart), Android Studio
(para el SDK de Android y el emulador) y Python 3. Para iOS además una Mac con Xcode.

```bash
cd app
python tool/setup.py          # genera android/ (e ios/ en Mac), aplica los parches de seguridad,
                              # íconos y splash. Se puede repetir sin duplicar nada.
flutter test                  # vectores criptográficos compartidos con el servidor
flutter run                   # celular por USB (depuración USB activada) o emulador
flutter build apk --release   # APK final en build/app/outputs/flutter-apk/
```

`tool/setup.py` hace por ti lo que antes era manual:

| Paso | Por qué |
|---|---|
| Permisos: Internet, cámara, biometría, micrófono | QR, aprobaciones y dictado |
| `allowBackup=false` | la clave del dispositivo nunca viaja en un backup |
| `network_security_config.xml` | `ws://` solo tiene sentido dentro del tailnet (la app lo restringe) |
| `MainActivity.kt` propio | `FlutterFragmentActivity` (huella) + canal `FLAG_SECURE` (pantalla privada) |
| Textos de permisos en `Info.plist` (iOS) | cámara, Face ID, micrófono, reconocimiento de voz |
| `flutter_launcher_icons` + `flutter_native_splash` | ícono y pantalla de carga de Theyso |

## Estructura

```
lib/
├── main.dart                     arranque, tema, pantalla privada, bloqueo con huella
├── theme.dart                    paleta violeta → cian sobre tinta, componentes redondeados
├── core/
│   ├── crypto.dart               Ed25519, HMAC, SAS, huellas (espejo del servidor)
│   ├── storage.dart              almacenamiento seguro + guardia de URL (solo tailnet o wss)
│   ├── pairing.dart              lectura del QR y vinculación
│   ├── connection.dart           WebSocket autenticado, reconexión, historial y reproducción
│   ├── biometric.dart            confirmación fuerte para acciones de riesgo alto
│   ├── dictation.dart            dictado con reconocimiento forzado en el dispositivo
│   └── privacy.dart              FLAG_SECURE + cubierta al salir de la app
├── state/
│   ├── providers.dart            PCs vinculadas y conexiones
│   ├── settings.dart             preferencias (guardadas en el almacenamiento seguro)
│   └── chat_controller.dart      eventos del agente → elementos del chat
└── features/
    ├── servers/                  lista de PCs vinculadas
    ├── pairing/                  escáner QR + código de 6 dígitos
    ├── sessions/                 sesiones, nueva sesión, pánico, alertas de permisos
    ├── chat/                     chat en vivo, herramientas, diffs, permisos, micrófono
    ├── usage/                    tokens, costos, ahorro, estadísticas
    └── settings/                 bloqueo, pantalla privada, vibración, dictado, tema
```

## Identidad visual

- **Logo**: una «T» hecha de cable con tres conectores — tu celular, tu PC y el agente.
  Fuente en `docs/brand/logo.svg`; todos los PNG se regeneran con `python docs/brand/make_brand.py`.
- **Paleta**: violeta `#7C5CFF` → cian `#22D3EE` (el degradado es «la conexión») sobre tinta `#0B0F1A`.
- **Tipografía**: la del sistema (Roboto / SF Pro), para no cargar fuentes extra.
- Tema claro, oscuro o según el sistema (Ajustes).

## Notas de seguridad del lado del celular

- La clave privada del dispositivo vive en Keystore/Keychain, marcada *this device only*.
- La app **fija** la clave pública del servidor del QR y no firma nada si el servidor no la prueba.
- Riesgo alto ⇒ huella o PIN; el servidor rechaza la aprobación sin `confirmed_strong`.
- `ws://` solo hacia IPs de Tailscale o `*.ts.net`; cualquier otro host necesita `wss://`.
- Dictado con `onDevice: true`: si no hay modelo offline, falla en vez de usar la nube.
