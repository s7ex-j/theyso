import 'package:local_auth/local_auth.dart';

final _auth = LocalAuthentication();

/// False when the phone has no screen lock at all (no PIN, pattern or biometrics).
Future<bool> strongAuthAvailable() async {
  try {
    return await _auth.isDeviceSupported();
  } catch (_) {
    return false;
  }
}

/// Strong confirmation for high-risk actions (force push, sudo, writes outside
/// the workspace…). Falls back to the device PIN/pattern if no biometrics.
Future<bool> confirmStrong(String reason) async {
  try {
    if (!await _auth.isDeviceSupported()) return false;
    return await _auth.authenticate(
      localizedReason: reason,
      options: const AuthenticationOptions(biometricOnly: false, stickyAuth: true),
    );
  } catch (_) {
    return false;
  }
}
