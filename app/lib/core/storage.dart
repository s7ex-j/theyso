// Paired PCs live in the platform secure store (Android Keystore-backed
// EncryptedSharedPreferences / iOS Keychain, this-device-only, no iCloud sync).

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import 'crypto.dart';

class PairedServer {
  PairedServer({
    required this.deviceId,
    required this.name,
    required this.url,
    required this.serverPub,
    required this.serverFingerprint,
    required this.pairedAt,
  });

  final String deviceId;
  final String name;
  final String url; // ws://100.x.y.z:8765 or wss://pc.tailnet.ts.net
  final Uint8List serverPub; // pinned from the QR — never updated silently
  final String serverFingerprint;
  final DateTime pairedAt;

  Map<String, dynamic> toJson() => {
        'device_id': deviceId,
        'name': name,
        'url': url,
        'server_pub': b64u(serverPub),
        'server_fp': serverFingerprint,
        'paired_at': pairedAt.toIso8601String(),
      };

  factory PairedServer.fromJson(Map<String, dynamic> j) => PairedServer(
        deviceId: j['device_id'] as String,
        name: j['name'] as String,
        url: j['url'] as String,
        serverPub: b64uDecode(j['server_pub'] as String),
        serverFingerprint: j['server_fp'] as String,
        pairedAt: DateTime.parse(j['paired_at'] as String),
      );
}

class SecureStore {
  static const _storage = FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock_this_device),
  );
  static const _serversKey = 'servers.v1';
  static const _settingsKey = 'settings.v1';

  Future<List<PairedServer>> servers() async {
    final raw = await _storage.read(key: _serversKey);
    if (raw == null) return [];
    return (jsonDecode(raw) as List<dynamic>)
        .map((e) => PairedServer.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> saveServer(PairedServer server, DeviceKey key) async {
    await _storage.write(key: 'seed:${server.deviceId}', value: b64u(await key.seed()));
    final list = (await servers()).where((s) => s.deviceId != server.deviceId).toList()..add(server);
    await _storage.write(key: _serversKey, value: jsonEncode(list.map((s) => s.toJson()).toList()));
  }

  Future<DeviceKey?> keyFor(String deviceId) async {
    final seed = await _storage.read(key: 'seed:$deviceId');
    return seed == null ? null : DeviceKey.fromSeed(b64uDecode(seed));
  }

  /// Forget a PC locally. (Revoke it on the PC too: `theyso revoke <id>`.)
  Future<void> forget(String deviceId) async {
    await _storage.delete(key: 'seed:$deviceId');
    final list = (await servers()).where((s) => s.deviceId != deviceId).toList();
    await _storage.write(key: _serversKey, value: jsonEncode(list.map((s) => s.toJson()).toList()));
  }

  Future<Map<String, dynamic>> settings() async {
    final raw = await _storage.read(key: _settingsKey);
    return raw == null ? {'app_lock': true} : jsonDecode(raw) as Map<String, dynamic>;
  }

  Future<void> saveSettings(Map<String, dynamic> s) => _storage.write(key: _settingsKey, value: jsonEncode(s));
}

/// Mirror of the server's bind guard: plain ws:// is only accepted inside the
/// tailnet (traffic is already WireGuard-encrypted). Anything else needs wss://.
bool isAllowedServerUrl(Uri uri) {
  if (uri.scheme == 'wss') return true;
  if (uri.scheme != 'ws') return false;
  final host = uri.host.toLowerCase();
  if (host.endsWith('.ts.net') || host == 'localhost') return true;
  final ip = InternetAddress.tryParse(host);
  if (ip == null) return false;
  if (ip.isLoopback) return true;
  final b = ip.rawAddress;
  if (ip.type == InternetAddressType.IPv4) return b[0] == 100 && (b[1] & 0xC0) == 64; // 100.64.0.0/10
  return b[0] == 0xfd && b[1] == 0x7a && b[2] == 0x11 && b[3] == 0x5c && b[4] == 0xa1 && b[5] == 0xe0;
}
