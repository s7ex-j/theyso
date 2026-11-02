import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

const _channel = MethodChannel('theyso/privacy');

/// Android: FLAG_SECURE — blocks screenshots, screen recording and the
/// "recent apps" thumbnail. Implemented in MainActivity.kt (platform/android/).
/// On iOS the call is a no-op; [PrivacyShield] covers the app switcher instead.
Future<void> setSecureWindow(bool enabled) async {
  try {
    await _channel.invokeMethod<void>('setSecure', enabled);
  } on MissingPluginException {
    // iOS / tests: nothing to do
  } on PlatformException {
    // ignore: older Android builds without the snippet applied
  }
}

/// Covers the UI whenever the app is not in the foreground, so the iOS app
/// switcher (and Android recents, as a second layer) never shows your code.
class PrivacyShield extends StatefulWidget {
  const PrivacyShield({super.key, required this.enabled, required this.child});
  final bool enabled;
  final Widget child;

  @override
  State<PrivacyShield> createState() => _PrivacyShieldState();
}

class _PrivacyShieldState extends State<PrivacyShield> with WidgetsBindingObserver {
  bool _hidden = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    setState(() => _hidden = state != AppLifecycleState.resumed);
  }

  @override
  Widget build(BuildContext context) {
    return Stack(children: [
      widget.child,
      if (widget.enabled && _hidden)
        Positioned.fill(
          child: ColoredBox(
            color: Theme.of(context).colorScheme.surface,
            child: Center(child: Image.asset('assets/brand/logo.png', width: 96, height: 96)),
          ),
        ),
    ]);
  }
}
