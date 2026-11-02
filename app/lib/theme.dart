import 'package:flutter/material.dart';

/// Theyso palette: electric violet → cyan on deep ink.
/// The gradient is the "line" between your phone and your PC.
class TheysoColors {
  static const violet = Color(0xFF7C5CFF);
  static const cyan = Color(0xFF22D3EE);
  static const ink = Color(0xFF0B0F1A);
  static const inkRaised = Color(0xFF141A2B);
  static const gradient = LinearGradient(colors: [violet, cyan]);
}

ThemeData buildTheme(Brightness brightness) {
  final dark = brightness == Brightness.dark;
  var scheme = ColorScheme.fromSeed(seedColor: TheysoColors.violet, brightness: brightness);
  if (dark) {
    scheme = scheme.copyWith(
      primary: TheysoColors.violet,
      secondary: TheysoColors.cyan,
      surface: TheysoColors.ink,
      surfaceContainer: TheysoColors.inkRaised,
    );
  }
  final shape = RoundedRectangleBorder(borderRadius: BorderRadius.circular(16));
  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: scheme.surface,
    appBarTheme: AppBarTheme(backgroundColor: scheme.surface, scrolledUnderElevation: 0, centerTitle: false),
    cardTheme: CardThemeData(shape: shape, elevation: 0, color: dark ? TheysoColors.inkRaised : null),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(24), borderSide: BorderSide.none),
      contentPadding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
    ),
    chipTheme: ChipThemeData(shape: StadiumBorder(side: BorderSide(color: scheme.outlineVariant))),
    floatingActionButtonTheme: const FloatingActionButtonThemeData(shape: StadiumBorder()),
    snackBarTheme: SnackBarThemeData(behavior: SnackBarBehavior.floating, shape: shape),
  );
}

/// Small brand mark used in empty states and the lock screen.
class TheysoMark extends StatelessWidget {
  const TheysoMark({super.key, this.size = 72});
  final double size;

  @override
  Widget build(BuildContext context) =>
      Image.asset('assets/brand/logo.png', width: size, height: size, filterQuality: FilterQuality.medium);
}
