// Turns the server's event stream for ONE session into a list of chat items.

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../core/connection.dart';

enum ItemKind { user, assistant, thinking, tool, permission, notice, result, error }

class ChatItem {
  ChatItem(this.kind, {this.text = '', this.id, Map<String, dynamic>? data}) : data = data ?? {};
  final ItemKind kind;
  String text;
  final String? id; // part_id / tool_use_id / request_id for in-place updates
  final Map<String, dynamic> data;
}

class ChatController extends ChangeNotifier {
  ChatController(this.conn, this.sid, {this.onNewPermission}) {
    for (final f in conn.historyFor(sid)) {
      _onFrame(f, notify: false); // rebuild what we already had
    }
    _sub = conn.frames.listen(_onFrame);
    conn.attach(sid); // then ask only for what we missed
  }

  final TheysoConnection conn;
  final String sid;
  final List<ChatItem> items = [];
  String agentState = 'idle';
  String? model;
  StreamSubscription<Frame>? _sub;

  /// Called for permission requests that arrive live (not from history),
  /// so the screen can vibrate exactly once per new request.
  final void Function()? onNewPermission;

  void _dropPartials() => items.removeWhere((i) => i.kind == ItemKind.assistant && i.data['partial'] == true);

  ChatItem? _find(ItemKind kind, String? id) {
    if (id == null) return null;
    for (var i = items.length - 1; i >= 0; i--) {
      if (items[i].kind == kind && items[i].id == id) return items[i];
    }
    return null;
  }

  void _onFrame(Frame f, {bool notify = true}) {
    if (f['sid'] != sid) return;
    switch (f['type']) {
      case 'event':
        _onEvent(f['kind'] as String, (f['data'] as Map).cast<String, dynamic>());
      case 'permission.request':
        if (_find(ItemKind.permission, f['request_id'] as String) == null) {
          items.add(ChatItem(ItemKind.permission, id: f['request_id'] as String, data: {...f, 'status': 'pending'}));
          if (notify) onNewPermission?.call();
        }
      case 'session.attached':
        final s = (f['session'] as Map).cast<String, dynamic>();
        agentState = s['state'] as String? ?? agentState;
        model = s['model'] as String? ?? model;
      case 'session.closed':
        agentState = 'closed';
        items.add(ChatItem(ItemKind.notice, text: 'Session closed: ${f['reason']}'));
      case 'error':
        items.add(ChatItem(ItemKind.error, text: f['message'] as String? ?? 'Error'));
      case 'notice':
        items.add(ChatItem(ItemKind.notice, text: f['text'] as String? ?? ''));
      default:
        return;
    }
    if (notify) notifyListeners();
  }

  void _onEvent(String kind, Map<String, dynamic> d) {
    switch (kind) {
      case 'user':
        items.add(ChatItem(ItemKind.user, text: d['text'] as String));
      case 'partial':
        // Reply still being written: one live bubble per stream, replaced by the final text.
        final streamId = 'partial:${d['stream_id']}';
        final existing = _find(ItemKind.assistant, streamId);
        if (existing != null) {
          existing.text = d['text'] as String;
        } else {
          items.add(ChatItem(ItemKind.assistant, id: streamId, text: d['text'] as String, data: {'partial': true}));
        }
      case 'text':
        _dropPartials();
        final partId = d['part_id'] as String?;
        final existing = _find(ItemKind.assistant, partId);
        if (existing != null) {
          existing.text = d['text'] as String; // OpenCode streams full text per part
        } else {
          items.add(ChatItem(ItemKind.assistant, id: partId, text: d['text'] as String, data: d));
        }
        model = d['model'] as String? ?? model;
      case 'thinking':
        final existing = _find(ItemKind.thinking, d['part_id'] as String?);
        if (existing != null) {
          existing.text = d['text'] as String;
        } else {
          items.add(ChatItem(ItemKind.thinking, id: d['part_id'] as String?, text: d['text'] as String));
        }
      case 'tool_use':
        final id = d['tool_use_id'] as String?;
        if (_find(ItemKind.tool, id) == null) {
          items.add(ChatItem(ItemKind.tool, id: id, text: d['tool'] as String? ?? 'tool', data: {...d, 'done': false}));
        }
      case 'tool_result':
        final item = _find(ItemKind.tool, d['tool_use_id'] as String?);
        if (item != null) {
          item.data.addAll({...d, 'done': true});
        }
      case 'permission_resolved':
        final item = _find(ItemKind.permission, d['request_id'] as String?);
        if (item != null) item.data['status'] = (d['allow'] == true) ? 'allowed' : 'denied (${d['by']})';
      case 'status':
        agentState = d['state'] as String? ?? agentState;
        if (agentState == 'idle') {
          // Interrupted mid-sentence: keep what was already shown, as plain text.
          for (final i in items) {
            if (i.data['partial'] == true) i.data['partial'] = false;
          }
        }
      case 'result':
        items.add(ChatItem(ItemKind.result, data: d));
      case 'notice':
        model = d['model'] as String? ?? model;
        items.add(ChatItem(ItemKind.notice, text: d['text'] as String? ?? ''));
      case 'error':
        items.add(ChatItem(ItemKind.error, text: d['text'] as String? ?? 'Agent error'));
    }
  }

  void sendPrompt(String text) => conn.send({'type': 'prompt', 'sid': sid, 'text': text});
  void interrupt() => conn.send({'type': 'interrupt', 'sid': sid});
  void setModel(String? m) => conn.send({'type': 'model.set', 'sid': sid, 'model': m});

  void answerPermission(String requestId, {required bool allow, bool strong = false, String? message}) {
    conn.send({
      'type': 'permission.reply',
      'sid': sid,
      'request_id': requestId,
      'decision': allow ? 'allow' : 'deny',
      'confirmed_strong': strong,
      if (message != null) 'message': message,
    });
  }

  @override
  void dispose() {
    // We stay attached on purpose: permission requests from this session keep
    // arriving (the sessions list can alert you) and the history stays fresh.
    _sub?.cancel();
    super.dispose();
  }
}
