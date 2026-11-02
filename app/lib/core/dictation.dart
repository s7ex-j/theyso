// Offline dictation. `onDevice: true` makes the platform recognizer FAIL rather
// than silently send audio to Google/Apple servers when no offline model exists.

import 'package:speech_to_text/speech_recognition_error.dart';
import 'package:speech_to_text/speech_to_text.dart';

class Dictation {
  final _stt = SpeechToText();
  bool _ready = false;
  String? _localeId;
  void Function(String message)? _onError;

  bool get listening => _stt.isListening;

  /// Returns null when ready, or a message explaining what is missing.
  Future<String?> init() async {
    if (_ready) return null;
    _ready = await _stt.initialize(onError: _handleError);
    if (!_ready) return 'El reconocimiento de voz no está disponible o no diste permiso al micrófono.';
    final system = await _stt.systemLocale();
    final locales = await _stt.locales();
    if (system != null && system.localeId.startsWith('es')) {
      _localeId = system.localeId;
    } else {
      _localeId = locales.where((l) => l.localeId.startsWith('es')).map((l) => l.localeId).firstOrNull ??
          system?.localeId;
    }
    return null;
  }

  void _handleError(SpeechRecognitionError e) {
    final msg = switch (e.errorMsg) {
      'error_language_not_supported' || 'error_language_unavailable' =>
        'Descarga el idioma español para reconocimiento sin conexión en los ajustes de voz del celular.',
      'error_no_match' || 'error_speech_timeout' => 'No te escuché bien, intenta de nuevo.',
      'error_permission' || 'error_insufficient_permissions' => 'Theyso necesita permiso de micrófono.',
      _ => 'Dictado no disponible (${e.errorMsg}).',
    };
    _onError?.call(msg);
  }

  Future<void> start({
    required void Function(String text, bool isFinal) onText,
    required void Function(String message) onError,
  }) async {
    _onError = onError;
    final problem = await init();
    if (problem != null) {
      onError(problem);
      return;
    }
    await _stt.listen(
      localeId: _localeId,
      onResult: (r) => onText(r.recognizedWords, r.finalResult),
      listenOptions: SpeechListenOptions(
        onDevice: true, // never fall back to cloud recognition
        partialResults: true,
        listenMode: ListenMode.dictation,
        cancelOnError: true,
      ),
    );
  }

  Future<void> stop() => _stt.stop();
}
