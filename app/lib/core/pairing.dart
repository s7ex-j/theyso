// QR pairing, phone side. See docs/PAIRING.md.

import 'dart:convert';
import 'dart:typed_data';

import 'package:http/http.dart' as http;

import 'crypto.dart';
import 'storage.dart';

class PairingQr {
  PairingQr({
    required this.url,
    required this.pid,
    required this.secret,
    required this.serverPub,
    required this.name,
    required this.expiresAt,
  });

  final String url;
  final String pid;
  final Uint8List secret;
  final Uint8List serverPub;
  final String name;
  final DateTime expiresAt;

  static PairingQr parse(String raw) {
    final uri = Uri.tryParse(raw);
    if (uri == null || uri.scheme != 'theyso' || uri.host != 'pair') {
      throw const FormatException('This is not a Theyso pairing code');
    }
    final body = jsonDecode(utf8.decode(b64uDecode(uri.queryParameters['d'] ?? ''))) as Map<String, dynamic>;
    if (body['v'] != 1) throw const FormatException('Unsupported pairing version — update the app');
    final qr = PairingQr(
      url: body['url'] as String,
      pid: body['pid'] as String,
      secret: b64uDecode(body['sec'] as String),
      serverPub: b64uDecode(body['spk'] as String),
      name: body['name'] as String,
      expiresAt: DateTime.fromMillisecondsSinceEpoch((body['exp'] as int) * 1000),
    );
    if (qr.secret.length != 32 || qr.serverPub.length != 32) throw const FormatException('Corrupted QR');
    if (!isAllowedServerUrl(Uri.parse(qr.url))) {
      throw const FormatException('Server URL is outside your tailnet and not wss:// — refusing');
    }
    if (DateTime.now().isAfter(qr.expiresAt)) throw const FormatException('This QR has expired');
    return qr;
  }

  Uri get httpBase {
    final u = Uri.parse(url);
    return u.replace(scheme: u.scheme == 'wss' ? 'https' : 'http', path: '');
  }
}

class PairingSession {
  PairingSession(this.qr, this.key, this.sas);
  final PairingQr qr;
  final DeviceKey key;
  final String sas; // show this big on screen; the PC shows the same digits

  static Future<PairingSession> start(PairingQr qr) async {
    final key = await DeviceKey.generate();
    final sas = await shortAuthString(qr.secret, key.publicKey, qr.serverPub);
    return PairingSession(qr, key, sas);
  }

  /// Blocks until the human on the PC approves or rejects (or it times out).
  Future<PairedServer> complete({required String deviceName, required String platform}) async {
    final proof = await pairingProof(qr.secret, qr.pid, key.publicKey);
    final resp = await http
        .post(
          qr.httpBase.replace(path: '/v1/pair'),
          headers: {'content-type': 'application/json'},
          body: jsonEncode({
            'pid': qr.pid,
            'device_pub': b64u(key.publicKey),
            'proof': b64u(proof),
            'name': deviceName,
            'platform': platform,
          }),
        )
        .timeout(const Duration(minutes: 4));
    if (resp.statusCode != 200) {
      throw Exception(resp.statusCode == 429 ? 'Too many attempts, wait a few minutes' : 'Pairing was rejected');
    }
    final body = jsonDecode(resp.body) as Map<String, dynamic>;
    final deviceId = body['device_id'] as String;
    // The answer must be signed by the key we pinned from the QR.
    final signed = Uint8List.fromList([...utf8.encode('$pairedContext|$deviceId|'), ...key.publicKey]);
    final ok = await verifyServer(qr.serverPub, signed, b64uDecode(body['signature'] as String));
    if (!ok) throw Exception('Server signature invalid — possible impersonation. Not saved.');

    final server = PairedServer(
      deviceId: deviceId,
      name: body['server_name'] as String? ?? qr.name,
      url: qr.url,
      serverPub: qr.serverPub,
      serverFingerprint: await fingerprint(qr.serverPub),
      pairedAt: DateTime.now(),
    );
    await SecureStore().saveServer(server, key);
    return server;
  }
}
