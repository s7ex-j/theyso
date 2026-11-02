import 'dart:io';
import 'dart:ui' show FontFeature;

import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';

import '../../core/pairing.dart';

class ScanScreen extends StatefulWidget {
  const ScanScreen({super.key});

  @override
  State<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends State<ScanScreen> {
  final _controller = MobileScannerController(formats: const [BarcodeFormat.qrCode]);
  bool _handled = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _onDetect(BarcodeCapture capture) async {
    if (_handled) return;
    final raw = capture.barcodes.firstOrNull?.rawValue;
    if (raw == null) return;
    _handled = true;
    try {
      final qr = PairingQr.parse(raw);
      final session = await PairingSession.start(qr);
      if (!mounted) return;
      await Navigator.pushReplacement(
        context,
        MaterialPageRoute<void>(builder: (_) => PairConfirmScreen(session: session)),
      );
    } on FormatException catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
      _handled = false;
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('Escanea el QR de `theyso pair`')),
        body: MobileScanner(controller: _controller, onDetect: _onDetect),
      );
}

class PairConfirmScreen extends StatefulWidget {
  const PairConfirmScreen({super.key, required this.session});
  final PairingSession session;

  @override
  State<PairConfirmScreen> createState() => _PairConfirmScreenState();
}

class _PairConfirmScreenState extends State<PairConfirmScreen> {
  final _name = TextEditingController(text: 'Mi celular');
  bool _waiting = false;
  String? _error;

  Future<void> _send() async {
    setState(() {
      _waiting = true;
      _error = null;
    });
    try {
      final server = await widget.session.complete(
        deviceName: _name.text.trim(),
        platform: Platform.isIOS ? 'ios' : 'android',
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Vinculado con ${server.name}')));
      Navigator.pop(context);
    } catch (e) {
      setState(() {
        _waiting = false;
        _error = '$e';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sas = widget.session.sas;
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text('Vincular con ${widget.session.qr.name}')),
      body: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('Código de verificación', style: theme.textTheme.titleMedium, textAlign: TextAlign.center),
          const SizedBox(height: 12),
          Text('${sas.substring(0, 3)} ${sas.substring(3)}',
              textAlign: TextAlign.center,
              style: theme.textTheme.displayLarge?.copyWith(fontFeatures: const [FontFeature.tabularFigures()])),
          const SizedBox(height: 12),
          const Text(
            'Tu PC mostrará este mismo código. Si NO coincide, rechaza en la PC: '
            'alguien más está intentando vincularse.',
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 32),
          TextField(controller: _name, decoration: const InputDecoration(labelText: 'Nombre de este dispositivo')),
          const SizedBox(height: 24),
          if (_waiting) ...[
            const Center(child: CircularProgressIndicator()),
            const SizedBox(height: 12),
            const Text('Esperando aprobación en la PC…', textAlign: TextAlign.center),
          ] else
            FilledButton(onPressed: _send, child: const Text('Enviar solicitud')),
          if (_error != null)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(_error!, style: TextStyle(color: theme.colorScheme.error)),
            ),
        ]),
      ),
    );
  }
}
