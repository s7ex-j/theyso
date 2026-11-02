import 'dart:convert';

import 'package:flutter/material.dart';

import '../../../core/biometric.dart';
import '../../../state/chat_controller.dart';

class PermissionCard extends StatelessWidget {
  const PermissionCard({super.key, required this.item, required this.chat});
  final ChatItem item;
  final ChatController chat;

  @override
  Widget build(BuildContext context) {
    final d = item.data;
    final risk = d['risk'] as String? ?? 'medium';
    final status = d['status'] as String? ?? 'pending';
    final strong = d['requires_strong_auth'] == true;
    final scheme = Theme.of(context).colorScheme;
    final color = switch (risk) {
      'high' => scheme.errorContainer,
      'low' => scheme.surfaceContainerHighest,
      _ => scheme.tertiaryContainer,
    };
    final input = (d['input'] as Map?)?.cast<String, dynamic>() ?? {};
    final mono = Theme.of(context).textTheme.bodySmall?.copyWith(fontFamily: 'monospace');

    return Card(
      color: color,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(risk == 'high' ? Icons.warning_amber : Icons.shield_outlined),
            const SizedBox(width: 8),
            Expanded(
              child: Text('${d['tool']} quiere ejecutarse · riesgo ${_riskEs(risk)}',
                  style: Theme.of(context).textTheme.titleSmall),
            ),
          ]),
          const SizedBox(height: 4),
          Text('${d['reason'] ?? ''}'),
          const SizedBox(height: 8),
          SelectableText(
            input['command'] != null ? '\$ ${input['command']}' : const JsonEncoder.withIndent('  ').convert(input),
            style: mono,
          ),
          const SizedBox(height: 12),
          if (status == 'pending')
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              OutlinedButton(
                onPressed: () => chat.answerPermission(item.id!, allow: false, message: 'Denegado desde el celular'),
                child: const Text('Denegar'),
              ),
              const SizedBox(width: 8),
              FilledButton.icon(
                icon: Icon(strong ? Icons.fingerprint : Icons.check),
                label: const Text('Permitir'),
                onPressed: () async {
                  var confirmed = false;
                  if (strong) {
                    if (!await strongAuthAvailable()) {
                      if (context.mounted) {
                        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                          content: Text('Activa un PIN o huella en el celular para aprobar acciones de riesgo alto.'),
                        ));
                      }
                      return;
                    }
                    confirmed = await confirmStrong('Confirma una acción de riesgo alto');
                    if (!confirmed) return;
                  }
                  chat.answerPermission(item.id!, allow: true, strong: confirmed);
                },
              ),
            ])
          else
            Align(alignment: Alignment.centerRight, child: Text(status == 'allowed' ? 'Permitido' : 'Denegado · $status')),
        ]),
      ),
    );
  }
}

String _riskEs(String r) => switch (r) { 'high' => 'ALTO', 'low' => 'bajo', _ => 'medio' };
