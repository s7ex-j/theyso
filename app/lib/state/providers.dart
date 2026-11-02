import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/connection.dart';
import '../core/storage.dart';

final secureStoreProvider = Provider((_) => SecureStore());

final serversProvider = FutureProvider<List<PairedServer>>((ref) => ref.watch(secureStoreProvider).servers());

/// One live connection per paired PC, kept alive while the app runs.
final connectionProvider = FutureProvider.family<TheysoConnection, String>((ref, deviceId) async {
  final store = ref.watch(secureStoreProvider);
  final server = (await store.servers()).firstWhere((s) => s.deviceId == deviceId);
  final key = await store.keyFor(deviceId);
  if (key == null) throw StateError('Device key missing — pair again');
  final conn = TheysoConnection(server, key);
  ref.onDispose(conn.close);
  await conn.connect();
  return conn;
});
