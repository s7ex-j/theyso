import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../state/settings.dart';
import '../../theme.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final s = ref.watch(settingsProvider);
    final theme = Theme.of(context);
    Widget header(String t) => Padding(
          padding: const EdgeInsets.fromLTRB(16, 24, 16, 8),
          child: Text(t, style: theme.textTheme.labelLarge?.copyWith(color: theme.colorScheme.primary)),
        );

    return Scaffold(
      appBar: AppBar(title: const Text('Ajustes')),
      body: ListView(children: [
        header('Seguridad'),
        SwitchListTile(
          title: const Text('Bloquear con huella o PIN'),
          subtitle: const Text('Al abrir Theyso y al volver tras un rato'),
          value: s.appLock,
          onChanged: (v) => s.update((x) => x.appLock = v),
        ),
        ListTile(
          enabled: s.appLock,
          title: const Text('Volver a bloquear tras'),
          trailing: DropdownButton<int>(
            value: s.relockMinutes,
            onChanged: s.appLock ? (v) => s.update((x) => x.relockMinutes = v ?? 5) : null,
            items: const [
              DropdownMenuItem(value: 1, child: Text('1 min')),
              DropdownMenuItem(value: 5, child: Text('5 min')),
              DropdownMenuItem(value: 15, child: Text('15 min')),
            ],
          ),
        ),
        SwitchListTile(
          title: const Text('Pantalla privada'),
          subtitle: const Text('Bloquea capturas y oculta el contenido en «apps recientes»'),
          value: s.privacyScreen,
          onChanged: (v) => s.update((x) => x.privacyScreen = v),
        ),
        header('Interacción'),
        SwitchListTile(
          title: const Text('Vibrar al pedir permiso'),
          value: s.haptics,
          onChanged: (v) => s.update((x) => x.haptics = v),
        ),
        SwitchListTile(
          title: const Text('Dictado por voz (offline)'),
          subtitle: const Text('El audio se transcribe en el celular y nunca sale de él'),
          value: s.dictation,
          onChanged: (v) => s.update((x) => x.dictation = v),
        ),
        header('Apariencia'),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SegmentedButton<ThemeMode>(
            segments: const [
              ButtonSegment(value: ThemeMode.system, label: Text('Sistema'), icon: Icon(Icons.brightness_auto)),
              ButtonSegment(value: ThemeMode.light, label: Text('Claro'), icon: Icon(Icons.light_mode)),
              ButtonSegment(value: ThemeMode.dark, label: Text('Oscuro'), icon: Icon(Icons.dark_mode)),
            ],
            selected: {s.themeMode},
            onSelectionChanged: (v) => s.update((x) => x.themeMode = v.first),
          ),
        ),
        const SizedBox(height: 32),
        const Center(child: TheysoMark(size: 48)),
        const SizedBox(height: 8),
        Center(child: Text('Theyso 0.1 · código abierto (MIT)', style: theme.textTheme.bodySmall)),
        Center(
          child: Text('Sin cuentas, sin nube: solo tu celular y tu PC.', style: theme.textTheme.bodySmall),
        ),
        const SizedBox(height: 32),
      ]),
    );
  }
}
