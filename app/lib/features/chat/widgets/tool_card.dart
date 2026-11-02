import 'dart:convert';

import 'package:flutter/material.dart';

import '../../../state/chat_controller.dart';

class ToolCard extends StatelessWidget {
  const ToolCard({super.key, required this.item});
  final ChatItem item;

  String _summary(Map<String, dynamic> input) {
    for (final k in ['command', 'file_path', 'filePath', 'path', 'pattern', 'url', 'query']) {
      if (input[k] != null) return '${input[k]}';
    }
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final d = item.data;
    final input = (d['input'] as Map?)?.cast<String, dynamic>() ?? {};
    final done = d['done'] == true;
    final isError = d['is_error'] == true;
    final mono = Theme.of(context).textTheme.bodySmall?.copyWith(fontFamily: 'monospace');
    final isEdit = input.containsKey('old_string') && input.containsKey('new_string');

    return Card(
      child: ExpansionTile(
        leading: Icon(!done ? Icons.hourglass_top : (isError ? Icons.error_outline : Icons.check_circle_outline)),
        title: Text(item.text),
        subtitle: Text(_summary(input), maxLines: 2, overflow: TextOverflow.ellipsis, style: mono),
        childrenPadding: const EdgeInsets.all(12),
        children: [
          if (isEdit)
            _Diff(oldText: '${input['old_string']}', newText: '${input['new_string']}')
          else
            SelectableText(const JsonEncoder.withIndent('  ').convert(input), style: mono),
          if (done) ...[
            const Divider(),
            SelectableText('${d['output'] ?? ''}', style: mono),
            if (d['truncated'] == true) const Text('(salida recortada)'),
          ],
        ],
      ),
    );
  }
}

/// Minimal line diff for Edit tool calls: removed lines red, added lines green.
class _Diff extends StatelessWidget {
  const _Diff({required this.oldText, required this.newText});
  final String oldText;
  final String newText;

  @override
  Widget build(BuildContext context) {
    final mono = Theme.of(context).textTheme.bodySmall?.copyWith(fontFamily: 'monospace');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      for (final l in oldText.split('\n'))
        Container(color: Colors.red.withValues(alpha: 0.15), child: Text('- $l', style: mono)),
      for (final l in newText.split('\n'))
        Container(color: Colors.green.withValues(alpha: 0.15), child: Text('+ $l', style: mono)),
    ]);
  }
}
