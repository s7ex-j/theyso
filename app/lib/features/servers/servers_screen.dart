import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/providers.dart';
import '../../theme.dart';
import '../pairing/scan_screen.dart';
import '../settings/settings_screen.dart';
import '../sessions/sessions_screen.dart';

class ServersScreen extends ConsumerWidget {
  const ServersScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final servers = ref.watch(serversProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Row(children: [TheysoMark(size: 28), SizedBox(width: 10), Text('Theyso')]),
        actions: [
          IconButton(
            tooltip: 'Ajustes',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => Navigator.push(context, MaterialPageRoute<void>(builder: (_) => const SettingsScreen())),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        icon: const Icon(Icons.qr_code_scanner),
        label: const Text('Vincular PC'),
        onPressed: () async {
          await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => const ScanScreen()));
          ref.invalidate(serversProvider);
        },
      ),
      body: servers.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('Error: $e')),
        data: (list) => list.isEmpty
            ? const _Empty()
            : ListView(
                children: [
                  for (final s in list)
                    ListTile(
                      leading: const Icon(Icons.computer),
                      title: Text(s.name),
                      subtitle: Text('${s.url}\nHuella ${s.serverFingerprint}'),
                      isThreeLine: true,
                      onTap: () => Navigator.push(
                        context,
                        MaterialPageRoute<void>(builder: (_) => SessionsScreen(server: s)),
                      ),
                      trailing: PopupMenuButton<String>(
                        onSelected: (v) async {
                          if (v != 'forget') return;
                          await ref.read(secureStoreProvider).forget(s.deviceId);
                          ref.invalidate(serversProvider);
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                              content: Text('Olvidado aquí. Revócalo también en la PC: theyso revoke'),
                            ));
                          }
                        },
                        itemBuilder: (_) => const [PopupMenuItem(value: 'forget', child: Text('Olvidar esta PC'))],
                      ),
                    ),
                ],
              ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) => const Padding(
        padding: EdgeInsets.all(32),
        child: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TheysoMark(size: 96),
            SizedBox(height: 24),
            Text(
            '1. En tu PC: theyso serve\n'
            '2. En otra terminal: theyso pair\n'
            '3. Toca «Vincular PC» y escanea el QR\n'
            '4. Comprueba que el código de 6 dígitos coincide',
            style: TextStyle(height: 1.8),
          ),
          ]),
        ),
      );
}
