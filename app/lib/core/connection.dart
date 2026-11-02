// Authenticated WebSocket with automatic reconnect + event replay.

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:async/async.dart';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import 'crypto.dart';
import 'storage.dart';

enum ConnState { offline, connecting, online, authFailed }

typedef Frame = Map<String, dynamic>;

class TheysoConnection {
  TheysoConnection(this.server, this._key);

  final PairedServer server;
  final DeviceKey _key;

  final state = ValueNotifier<ConnState>(ConnState.offline);
  final _frames = StreamController<Frame>.broadcast();
  Stream<Frame> get frames => _frames.stream;

  /// Last `auth.ok` payload: profiles, workspaces, sessions, limits.
  Frame? welcome;

  WebSocketChannel? _ws;
  StreamSubscription<dynamic>? _sub;
  bool _closedByUser = false;
  int _attempt = 0;
  final Map<String, int> _lastSeq = {}; // sid → last seq seen, for replay
  final Map<String, List<Frame>> _history = {}; // sid → frames already received (bounded)
  static const _historyLimit = 500; // keeps phone RAM low (outputs are already clipped server-side)

  /// Everything already received for a session, so a re-opened chat is not empty.
  List<Frame> historyFor(String sid) => List.unmodifiable(_history[sid] ?? const <Frame>[]);
  final Set<String> _attached = {};

  Future<void> connect() async {
    _closedByUser = false;
    await _connectOnce();
  }

  Future<void> _connectOnce() async {
    if (state.value == ConnState.connecting) return;
    state.value = ConnState.connecting;
    final uri = Uri.parse('${server.url}/v1/ws');
    if (!isAllowedServerUrl(uri)) {
      state.value = ConnState.authFailed;
      return;
    }
    try {
      final ws = IOWebSocketChannel.connect(uri, pingInterval: const Duration(seconds: 20),
          connectTimeout: const Duration(seconds: 10));
      await ws.ready;
      final queue = StreamQueue<dynamic>(ws.stream);
      final ok = await _handshake(ws, queue);
      if (!ok) {
        state.value = ConnState.authFailed;
        await ws.sink.close();
        return;
      }
      _ws = ws;
      _attempt = 0;
      state.value = ConnState.online;
      _sub = queue.rest.listen(_onRaw, onDone: _onDropped, onError: (_) => _onDropped());
      // Re-attach every session we were watching, asking only for what we missed.
      for (final sid in _attached) {
        send({'type': 'session.attach', 'sid': sid, 'after_seq': _lastSeq[sid] ?? 0});
      }
    } catch (_) {
      _onDropped();
    }
  }

  Future<bool> _handshake(WebSocketChannel ws, StreamQueue<dynamic> q) async {
    const timeout = Duration(seconds: 10);
    final clientNonce = randomBytes(32);
    ws.sink.add(jsonEncode({'type': 'auth.hello', 'device_id': server.deviceId, 'client_nonce': b64u(clientNonce)}));

    final challenge = jsonDecode(await q.next.timeout(timeout) as String) as Frame;
    if (challenge['type'] != 'auth.challenge') return false;
    final serverNonce = b64uDecode(challenge['server_nonce'] as String);
    final t = authTranscript(server.deviceId, clientNonce, serverNonce, server.serverPub);

    // 1) The server must prove it is the PC we paired with (pinned key).
    final serverOk = await verifyServer(server.serverPub, prefixed('server', t),
        b64uDecode(challenge['signature'] as String));
    if (!serverOk) return false; // impersonation attempt: do NOT send our signature

    // 2) We prove we are the paired phone.
    ws.sink.add(jsonEncode({'type': 'auth.response', 'signature': b64u(await _key.sign(prefixed('client', t)))}));
    final reply = jsonDecode(await q.next.timeout(timeout) as String) as Frame;
    if (reply['type'] != 'auth.ok') return false;
    welcome = reply;
    _frames.add(reply);
    return true;
  }

  void _onRaw(dynamic raw) {
    final frame = jsonDecode(raw as String) as Frame;
    final sid = frame['sid'] as String?;
    final seq = frame['seq'] as int?;
    if (sid != null && seq != null) {
      if (seq <= (_lastSeq[sid] ?? 0)) return; // duplicate after replay
      _lastSeq[sid] = seq;
    }
    if (sid != null && (seq != null || frame['type'] == 'permission.request')) {
      final h = _history.putIfAbsent(sid, () => []);
      h.add(frame);
      if (h.length > _historyLimit) h.removeRange(0, h.length - _historyLimit);
    }
    if (frame['type'] == 'session.attached' || frame['type'] == 'session.created') {
      final s = (frame['session'] as Map<String, dynamic>?)?['sid'] as String?;
      if (s != null) _attached.add(s);
    }
    if (frame['type'] == 'session.closed' && sid != null) _attached.remove(sid);
    _frames.add(frame);
  }

  void _onDropped() {
    _sub?.cancel();
    _ws = null;
    if (state.value != ConnState.authFailed) state.value = ConnState.offline;
    if (_closedByUser || state.value == ConnState.authFailed) return;
    // Exponential backoff with jitter: 1s, 2s, 4s … capped at 30s.
    final delay = min(30, pow(2, _attempt).toInt()) + Random().nextDouble();
    _attempt++;
    Future<void>.delayed(Duration(milliseconds: (delay * 1000).toInt()), _connectOnce);
  }

  void send(Frame frame) {
    final ws = _ws;
    if (ws == null) throw StateError('Not connected');
    ws.sink.add(jsonEncode(frame));
  }

  void attach(String sid) {
    _attached.add(sid);
    send({'type': 'session.attach', 'sid': sid, 'after_seq': _lastSeq[sid] ?? 0});
  }

  Future<void> close() async {
    _closedByUser = true;
    await _sub?.cancel();
    await _ws?.sink.close();
    state.value = ConnState.offline;
  }
}
