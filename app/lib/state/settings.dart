import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/privacy.dart';
import '../core/storage.dart';

/// User preferences, stored in the secure store (nothing leaves the phone).
class AppSettings extends ChangeNotifier {
  bool loaded = false;
  bool appLock = true; // biometrics / PIN when opening the app
  int relockMinutes = 5; // re-lock after this long in the background
  ThemeMode themeMode = ThemeMode.system;
  bool privacyScreen = true; // block screenshots + hide content in "recent apps"
  bool haptics = true; // vibrate when the agent asks for permission
  bool dictation = true; // show the offline dictation microphone

  final _store = SecureStore();

  Future<void> load() async {
    final s = await _store.settings();
    appLock = s['app_lock'] as bool? ?? true;
    relockMinutes = s['relock_minutes'] as int? ?? 5;
    themeMode = ThemeMode.values.firstWhere((m) => m.name == s['theme'], orElse: () => ThemeMode.system);
    privacyScreen = s['privacy_screen'] as bool? ?? true;
    haptics = s['haptics'] as bool? ?? true;
    dictation = s['dictation'] as bool? ?? true;
    loaded = true;
    await setSecureWindow(privacyScreen);
    notifyListeners();
  }

  Future<void> update(void Function(AppSettings s) change) async {
    change(this);
    await setSecureWindow(privacyScreen);
    await _store.saveSettings({
      'app_lock': appLock,
      'relock_minutes': relockMinutes,
      'theme': themeMode.name,
      'privacy_screen': privacyScreen,
      'haptics': haptics,
      'dictation': dictation,
    });
    notifyListeners();
  }
}

final settingsProvider = ChangeNotifierProvider<AppSettings>((ref) => AppSettings()..load());
