// Cross-language test vectors. The expected values were produced by the Python
// server (theyso.security.pairing / keys / handshake). If one of these fails,
// the app and the server no longer speak the same protocol.

import 'dart:typed_data';

import 'package:theyso/core/crypto.dart';
import 'package:theyso/core/storage.dart';
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';

Uint8List range(int a, int b) => Uint8List.fromList([for (var i = a; i < b; i++) i]);

void main() {
  final secret = range(0, 32);
  final dev = range(32, 64);
  final srv = range(64, 96);

  test('pairing proof matches server', () async {
    expect(b64u(await pairingProof(secret, 'pid123', dev)), '9tTALmf9ku5zANZwf12VktIF2i8MfSdiW7ykGZlELHc');
  });

  test('short authentication string matches server', () async {
    expect(await shortAuthString(secret, dev, srv), '516447');
  });

  test('fingerprint matches server', () async {
    expect(await fingerprint(srv), 'ZIVE-7ZZH-7KXM-6FXM');
  });

  test('auth transcript matches server', () async {
    final t = authTranscript('dev_abc', Uint8List(32)..fillRange(0, 32, 1), Uint8List(32)..fillRange(0, 32, 2), srv);
    final hash = await Sha256().hash(t);
    expect(hash.bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join(),
        'd5fc65ebc41d15d7451d1ee92b791f11e4728a158337a2bbad503bc714bc16fa');
  });

  test('sign / verify round trip', () async {
    final key = await DeviceKey.generate();
    final sig = await key.sign([1, 2, 3]);
    expect(await verifyServer(key.publicKey, [1, 2, 3], sig), isTrue);
    expect(await verifyServer(key.publicKey, [1, 2, 4], sig), isFalse);
    final restored = await DeviceKey.fromSeed(await key.seed());
    expect(restored.publicKey, key.publicKey);
  });

  test('url guard only allows the tailnet or wss', () {
    expect(isAllowedServerUrl(Uri.parse('ws://100.101.102.103:8765')), isTrue);
    expect(isAllowedServerUrl(Uri.parse('ws://pc.tail1234.ts.net:8765')), isTrue);
    expect(isAllowedServerUrl(Uri.parse('wss://anything.example.com')), isTrue);
    expect(isAllowedServerUrl(Uri.parse('ws://192.168.1.20:8765')), isFalse);
    expect(isAllowedServerUrl(Uri.parse('ws://evil.example.com')), isFalse);
    expect(isAllowedServerUrl(Uri.parse('http://100.64.0.1')), isFalse);
  });
}
