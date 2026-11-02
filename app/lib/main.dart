import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/biometric.dart';
import 'core/privacy.dart';
import 'features/servers/servers_screen.dart';
import 'state/settings.dart';
import 'theme.dart';

void main() => runApp(const ProviderScope(child: TheysoApp()));

class TheysoApp extends ConsumerWidget {
  const TheysoApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(settingsProvider);
    return MaterialApp(
      title: 'Theyso',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(Brightness.light),
      darkTheme: buildTheme(Brightness.dark),
      themeMode: settings.themeMode,
      builder: (context, child) => PrivacyShield(enabled: settings.privacyScreen, child: child!),
      home: settings.loaded
          ? const AppLockGate(child: ServersScreen())
          : const Scaffold(body: Center(child: TheysoMark())),
    );
  }
}

/// Requires biometrics / device PIN when the app opens (on by default).
/// Someone who grabs your unlocked phone still can't drive your PC.
class AppLockGate extends ConsumerStatefulWidget {
  const AppLockGate({super.key, required this.child});
  final Widget child;

  @override
  ConsumerState<AppLockGate> createState() => _AppLockGateState();
}

class _AppLockGateState extends ConsumerState<AppLockGate> with WidgetsBindingObserver {
  bool _unlocked = false;
  DateTime? _pausedAt;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _check();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState s) {
    if (s == AppLifecycleState.paused) _pausedAt = DateTime.now();
    final minutes = ref.read(settingsProvider).relockMinutes;
    if (s == AppLifecycleState.resumed &&
        _pausedAt != null &&
        DateTime.now().difference(_pausedAt!) > Duration(minutes: minutes)) {
      setState(() => _unlocked = false);
      _check();
    }
  }

  Future<void> _check() async {
    if (!ref.read(settingsProvider).appLock) {
      setState(() => _unlocked = true);
      return;
    }
    if (!await strongAuthAvailable()) {
      // No screen lock on this phone: let the user in, but say why it matters.
      if (mounted) setState(() => _unlocked = true);
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(const SnackBar(
          content: Text('Configura un PIN o huella en tu celular: sin eso no podrás aprobar acciones de riesgo alto.'),
        ));
      }
      return;
    }
    final ok = await confirmStrong('Desbloquea Theyso');
    if (mounted) setState(() => _unlocked = ok);
  }

  @override
  Widget build(BuildContext context) {
    if (_unlocked) return widget.child;
    return Scaffold(
      body: Center(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const TheysoMark(size: 96),
          const SizedBox(height: 24),
          FilledButton.icon(onPressed: _check, icon: const Icon(Icons.fingerprint), label: const Text('Desbloquear')),
        ]),
      ),
    );
  }
}
