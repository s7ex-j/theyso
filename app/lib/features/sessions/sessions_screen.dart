import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/connection.dart';
import '../../core/storage.dart';
import '../../state/providers.dart';
import '../../state/settings.dart';
import '../chat/chat_screen.dart';
import '../usage/usage_screen.dart';

class SessionsScreen extends ConsumerStatefulWidget {
  const SessionsScreen({super.key, required this.server});
  final PairedServer server;

  @override
  ConsumerState<SessionsScreen> createState() => _SessionsScreenState();
}

class _SessionsScreenState extends ConsumerState<SessionsScreen> {
  List<Map<String, dynamic>> _sessions = [];
  StreamSubscription<Frame>? _sub;

  void _listen(TheysoConnection conn) {
    if (_sub != null) return;
    _sessions = _castList(conn.welcome?['sessions']);
    _sub = conn.frames.listen((f) {
      if (f['type'] == 'auth.ok' || f['type'] == 'session.list.result') {
        setState(() => _sessions = _castList(f['sessions']));
      } else if (f['type'] == 'session.created') {
        final s = (f['session'] as Map).cast<String, dynamic>();
        setState(() => _sessions = [..._sessions, s]);
        _open(conn, s);
      } else if (f['type'] == 'permission.request' && (ModalRoute.of(context)?.isCurrent ?? false)) {
        // A session you are not looking at needs you.
        if (ref.read(settingsProvider).haptics) HapticFeedback.heavyImpact();
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text('${f['tool']} pide permiso (riesgo ${f['risk']})'),
          action: SnackBarAction(label: 'Ver', onPressed: () {
            final s = _sessions.where((x) => x['sid'] == f['sid']).firstOrNull;
            if (s != null) _open(conn, s);
          }),
        ));
        conn.send({'type': 'session.list'});
      } else if (f['type'] == 'error' && f['sid'] == null && (ModalRoute.of(context)?.isCurrent ?? false)) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('${f['message']}')));
      }
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _open(TheysoConnection conn, Map<String, dynamic> s) => Navigator.push(
        context,
        MaterialPageRoute<void>(builder: (_) => ChatScreen(conn: conn, session: s)),
      ).then((_) {
        if (conn.state.value == ConnState.online) conn.send({'type': 'session.list'});
      });

  Future<void> _panic(TheysoConnection conn) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (_) => AlertDialog(
        title: const Text('Botón de pánico'),
        content: const Text('Detiene y cierra TODAS las sesiones del agente en esta PC ahora mismo.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Detener todo')),
        ],
      ),
    );
    if (ok == true) conn.send({'type': 'panic'});
  }

  @override
  Widget build(BuildContext context) {
    final connAsync = ref.watch(connectionProvider(widget.server.deviceId));
    return connAsync.when(
      loading: () => Scaffold(appBar: AppBar(title: Text(widget.server.name)), body: const Center(child: CircularProgressIndicator())),
      error: (e, _) => Scaffold(appBar: AppBar(title: Text(widget.server.name)), body: Center(child: Text('$e'))),
      data: (conn) {
        _listen(conn);
        return ValueListenableBuilder<ConnState>(
          valueListenable: conn.state,
          builder: (context, st, _) => Scaffold(
            appBar: AppBar(
              title: Text(widget.server.name),
              bottom: PreferredSize(preferredSize: const Size.fromHeight(4), child: _StatusBar(st)),
              actions: [
                IconButton(
                  tooltip: 'Uso y costos',
                  icon: const Icon(Icons.insights),
                  onPressed: st == ConnState.online
                      ? () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => UsageScreen(conn: conn)))
                      : null,
                ),
                IconButton(
                  tooltip: 'Pánico',
                  icon: const Icon(Icons.dangerous_outlined),
                  onPressed: st == ConnState.online ? () => _panic(conn) : null,
                ),
              ],
            ),
            floatingActionButton: st == ConnState.online
                ? FloatingActionButton.extended(
                    icon: const Icon(Icons.add),
                    label: const Text('Nueva sesión'),
                    onPressed: () => _newSession(conn),
                  )
                : null,
            body: st == ConnState.authFailed
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(32),
                      child: Text('La PC no aceptó este dispositivo, o su identidad no coincide con la vinculada. '
                          'Si reinstalaste el servidor, vuelve a vincular.'),
                    ),
                  )
                : RefreshIndicator(
                    onRefresh: () async => conn.send({'type': 'session.list'}),
                    child: ListView(children: [
                      if (_sessions.isEmpty)
                        const Padding(padding: EdgeInsets.all(32), child: Text('No hay sesiones abiertas.')),
                      for (final s in _sessions)
                        ListTile(
                          leading: _stateIcon(s['state'] as String?),
                          title: Text(s['title'] as String? ?? s['sid'] as String),
                          subtitle: Text('${s['profile']} · ${s['agent']}${s['model'] != null ? ' · ${s['model']}' : ''}\n'
                              '${s['workspace']}'),
                          isThreeLine: true,
                          trailing: (s['pending_permissions'] as int? ?? 0) > 0
                              ? Badge(label: Text('${s['pending_permissions']}'), child: const Icon(Icons.shield_outlined))
                              : null,
                          onTap: st == ConnState.online ? () => _open(conn, s) : null,
                        ),
                    ]),
                  ),
          ),
        );
      },
    );
  }

  Future<void> _newSession(TheysoConnection conn) async {
    final w = conn.welcome ?? {};
    final profiles = _castList(w['profiles']);
    final roots = _castList(w['workspaces']);
    String? profile = profiles.isNotEmpty ? profiles.first['name'] as String : null;
    String? workspace;
    await showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setSheet) => Padding(
          padding: EdgeInsets.fromLTRB(16, 16, 16, MediaQuery.of(ctx).viewInsets.bottom + 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Text('Nueva sesión', style: Theme.of(ctx).textTheme.titleLarge),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: profile,
              decoration: const InputDecoration(labelText: 'Perfil (agente + modelo/proveedor)'),
              items: [
                for (final p in profiles)
                  DropdownMenuItem(value: p['name'] as String, child: Text(p['label'] as String? ?? p['name'] as String)),
              ],
              onChanged: (v) => setSheet(() => profile = v),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: workspace,
              decoration: const InputDecoration(labelText: 'Proyecto'),
              items: [
                for (final r in roots)
                  for (final p in (r['projects'] as List).cast<String>())
                    DropdownMenuItem(value: '${r['root']}/$p', child: Text(p)),
              ],
              onChanged: (v) => setSheet(() => workspace = v),
            ),
            const SizedBox(height: 16),
            FilledButton(
              onPressed: profile == null || workspace == null
                  ? null
                  : () {
                      conn.send({'type': 'session.create', 'profile': profile, 'workspace': workspace});
                      Navigator.pop(ctx);
                    },
              child: const Text('Iniciar'),
            ),
          ]),
        ),
      ),
    );
  }
}

List<Map<String, dynamic>> _castList(Object? v) =>
    (v as List? ?? const []).map((e) => (e as Map).cast<String, dynamic>()).toList();

Widget _stateIcon(String? s) => switch (s) {
      'running' => const Icon(Icons.autorenew),
      'waiting_permission' => const Icon(Icons.front_hand_outlined),
      'error' => const Icon(Icons.error_outline),
      _ => const Icon(Icons.terminal),
    };

class _StatusBar extends StatelessWidget {
  const _StatusBar(this.state);
  final ConnState state;

  @override
  Widget build(BuildContext context) {
    final c = Theme.of(context).colorScheme;
    return switch (state) {
      ConnState.online => const SizedBox(height: 4),
      ConnState.connecting => const LinearProgressIndicator(minHeight: 4),
      ConnState.offline => Container(height: 4, color: c.outline),
      ConnState.authFailed => Container(height: 4, color: c.error),
    };
  }
}
