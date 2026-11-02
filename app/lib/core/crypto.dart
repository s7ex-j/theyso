// Cryptographic helpers. Every constant here MUST match the server
// (server/theyso/security/pairing.py and handshake.py). The server's test
// suite contains a Python "PhoneSim" that implements exactly this file.

import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';

final _ed25519 = Ed25519();
final _hmac = Hmac.sha256();

const pairContext = 'theyso-pair-v1';
const sasContext = 'theyso-sas-v1';
const authContext = 'theyso-auth-v1';
const pairedContext = 'theyso-paired-v1';

String b64u(List<int> bytes) => base64Url.encode(bytes).replaceAll('=', '');

Uint8List b64uDecode(String s) =>
    base64Url.decode(s.padRight(s.length + (4 - s.length % 4) % 4, '='));

Uint8List randomBytes(int n) {
  final rnd = Random.secure();
  return Uint8List.fromList(List<int>.generate(n, (_) => rnd.nextInt(256)));
}

Uint8List _join(List<List<int>> parts) {
  final out = BytesBuilder();
  for (var i = 0; i < parts.length; i++) {
    if (i > 0) out.addByte(0x7C); // '|'
    out.add(parts[i]);
  }
  return out.toBytes();
}

class DeviceKey {
  DeviceKey._(this._pair, this.publicKey);
  final SimpleKeyPair _pair;
  final Uint8List publicKey;

  static Future<DeviceKey> generate() async {
    final pair = await _ed25519.newKeyPair();
    final pub = await pair.extractPublicKey();
    return DeviceKey._(pair, Uint8List.fromList(pub.bytes));
  }

  static Future<DeviceKey> fromSeed(Uint8List seed) async {
    final pair = await _ed25519.newKeyPairFromSeed(seed);
    final pub = await pair.extractPublicKey();
    return DeviceKey._(pair, Uint8List.fromList(pub.bytes));
  }

  Future<Uint8List> seed() async => Uint8List.fromList(await _pair.extractPrivateKeyBytes());

  Future<Uint8List> sign(List<int> data) async {
    final sig = await _ed25519.sign(data, keyPair: _pair);
    return Uint8List.fromList(sig.bytes);
  }
}

Future<bool> verifyServer(Uint8List serverPub, List<int> data, List<int> signature) {
  return _ed25519.verify(
    data,
    signature: Signature(signature, publicKey: SimplePublicKey(serverPub, type: KeyPairType.ed25519)),
  );
}

Future<Uint8List> _mac(Uint8List secret, List<int> data) async {
  final mac = await _hmac.calculateMac(data, secretKey: SecretKey(secret));
  return Uint8List.fromList(mac.bytes);
}

/// Proves knowledge of the QR secret without sending it, bound to our key.
Future<Uint8List> pairingProof(Uint8List secret, String pid, Uint8List devicePub) =>
    _mac(secret, _join([utf8.encode(pairContext), utf8.encode(pid), devicePub]));

/// 6-digit code shown on both the phone and the PC terminal.
Future<String> shortAuthString(Uint8List secret, Uint8List devicePub, Uint8List serverPub) async {
  final mac = await _mac(secret, _join([utf8.encode(sasContext), devicePub, serverPub]));
  final n = ByteData.sublistView(mac, 0, 4).getUint32(0, Endian.big) % 1000000;
  return n.toString().padLeft(6, '0');
}

Uint8List authTranscript(String deviceId, Uint8List clientNonce, Uint8List serverNonce, Uint8List serverPub) =>
    _join([utf8.encode(authContext), utf8.encode(deviceId), clientNonce, serverNonce, serverPub]);

Uint8List prefixed(String role, Uint8List transcript) =>
    Uint8List.fromList([...utf8.encode('$role|'), ...transcript]);

/// Human-comparable fingerprint, same algorithm as server keys.fingerprint().
Future<String> fingerprint(Uint8List pub) async {
  final digest = (await Sha256().hash(pub)).bytes.sublist(0, 10);
  final text = _base32(digest);
  final groups = <String>[];
  for (var i = 0; i < text.length; i += 4) {
    groups.add(text.substring(i, min(i + 4, text.length)));
  }
  return groups.join('-');
}

String _base32(List<int> data) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  var buffer = 0, bits = 0;
  final out = StringBuffer();
  for (final b in data) {
    buffer = ((buffer << 8) | b) & 0xFFFF; // keep only unconsumed bits
    bits += 8;
    while (bits >= 5) {
      out.write(alphabet[(buffer >> (bits - 5)) & 31]);
      bits -= 5;
    }
  }
  if (bits > 0) out.write(alphabet[(buffer << (5 - bits)) & 31]);
  return out.toString();
}
