import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/connection.dart';
import '../../core/dictation.dart';
import '../../state/chat_controller.dart';
import '../../state/settings.dart';
import '../../theme.dart';
import 'widgets/permission_card.dart';
import 'widgets/tool_card.dart';

class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key, required this.conn, required this.session});
  final TheysoConnection conn;
  final Map<String, dynamic> session;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  late final ChatController chat = ChatController(
    widget.conn,
    widget.session['sid'] as String,
    onNewPermission: _buzz,
  );
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final _dictation = Dictation();
  bool _listening = false;
  String _textBeforeDictation = '';

  static const _quick = ['Corre los tests', 'Resume los cambios', 'Haz commit con un buen mensaje', 'Explica el error'];

  @override
  void initState() {
    super.initState();
    chat.addListener(_autoscroll);
  }

  @override
  void dispose() {
    _dictation.stop();
    chat.removeListener(_autoscroll);
    chat.dispose();
    super.dispose();
  }

  void _buzz() {
    if (ref.read(settingsProvider).haptics) {
      HapticFeedback.heavyImpact();
      Future<void>.delayed(const Duration(milliseconds: 180), HapticFeedback.heavyImpact);
    }
  }

  void _autoscroll() {
    if (!mounted) return;
    final atBottom = !_scroll.hasClients || _scroll.position.extentAfter < 120;
    setState(() {});
    if (!atBottom) return; // don't yank the user away while they read older messages
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) _scroll.jumpTo(_scroll.position.maxScrollExtent);
    });
  }

  void _send([String? text]) {
    final t = (text ?? _input.text).trim();
    if (t.isEmpty) return;
    if (_listening) _toggleDictation();
    chat.sendPrompt(t);
    _input.clear();
  }

  Future<void> _toggleDictation() async {
    if (_listening) {
      await _dictation.stop();
      setState(() => _listening = false);
      return;
    }
    _textBeforeDictation = _input.text.isEmpty ? '' : '${_input.text.trimRight()} ';
    setState(() => _listening = true);
    await _dictation.start(
      // Voice only FILLS the box. You read it and press send yourself.
      onText: (text, isFinal) {
        _input.text = '$_textBeforeDictation$text';
        _input.selection = TextSelection.collapsed(offset: _input.text.length);
        if (isFinal && mounted) setState(() => _listening = false);
      },
      onError: (msg) {
        if (!mounted) return;
        setState(() => _listening = false);
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final settings = ref.watch(settingsProvider);
    final running = chat.agentState == 'running' || chat.agentState == 'waiting_permission';
    return Scaffold(
      appBar: AppBar(
        title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(widget.session['title'] as String? ?? 'Sesión'),
          Text('${chat.model ?? widget.session['profile']} · ${_stateEs(chat.agentState)}',
              style: theme.textTheme.bodySmall),
        ]),
        actions: [
          if (running)
            IconButton(tooltip: 'Interrumpir', icon: const Icon(Icons.stop_circle_outlined), onPressed: chat.interrupt),
        ],
      ),
      body: Column(children: [
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 4),
            itemCount: chat.items.length,
            itemBuilder: (_, i) => _buildItem(chat.items[i]),
          ),
        ),
        if (running)
          Container(height: 2, decoration: const BoxDecoration(gradient: TheysoColors.gradient)),
        SizedBox(
          height: 44,
          child: ListView(scrollDirection: Axis.horizontal, padding: const EdgeInsets.symmetric(horizontal: 8), children: [
            for (final q in _quick)
              Padding(padding: const EdgeInsets.all(4), child: ActionChip(label: Text(q), onPressed: () => _send(q))),
          ]),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 6,
                  textInputAction: TextInputAction.newline,
                  decoration: InputDecoration(
                    hintText: _listening ? 'Escuchando… (sin conexión)' : 'Pídele algo al agente…',
                    suffixIcon: settings.dictation
                        ? IconButton(
                            tooltip: _listening ? 'Detener dictado' : 'Dictar (offline)',
                            icon: Icon(_listening ? Icons.mic : Icons.mic_none,
                                color: _listening ? TheysoColors.cyan : null),
                            onPressed: _toggleDictation,
                          )
                        : null,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(onPressed: _send, icon: const Icon(Icons.arrow_upward)),
            ]),
          ),
        ),
      ]),
    );
  }

  Widget _buildItem(ChatItem item) {
    final theme = Theme.of(context);
    switch (item.kind) {
      case ItemKind.user:
        return Align(
          alignment: Alignment.centerRight,
          child: Container(
            margin: const EdgeInsets.only(left: 48, top: 6, bottom: 6),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              gradient: TheysoColors.gradient,
              borderRadius: BorderRadius.circular(18).copyWith(bottomRight: const Radius.circular(4)),
            ),
            child: SelectableText(item.text, style: const TextStyle(color: Colors.white)),
          ),
        );
      case ItemKind.assistant:
        final partial = item.data['partial'] == true;
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: MarkdownBody(data: partial ? '${item.text}▍' : item.text, selectable: !partial),
        );
      case ItemKind.thinking:
        return ExpansionTile(
          title: Text('Razonamiento', style: theme.textTheme.bodySmall),
          children: [Padding(padding: const EdgeInsets.all(8), child: Text(item.text, style: theme.textTheme.bodySmall))],
        );
      case ItemKind.tool:
        return ToolCard(item: item);
      case ItemKind.permission:
        return PermissionCard(item: item, chat: chat);
      case ItemKind.result:
        final d = item.data;
        final cost = d['cost_usd'];
        return Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 4),
            child: Text(
              '${d['model'] ?? ''} · ${d['input_tokens']}→${d['output_tokens']} tokens'
              '${cost != null ? ' · \$${(cost as num).toStringAsFixed(4)}' : ''}',
              style: theme.textTheme.labelSmall?.copyWith(color: theme.colorScheme.outline),
            ),
          ),
        );
      case ItemKind.notice:
        return Center(child: Text(item.text, style: theme.textTheme.labelSmall));
      case ItemKind.error:
        return Card(
          color: theme.colorScheme.errorContainer,
          child: Padding(padding: const EdgeInsets.all(12), child: Text(item.text)),
        );
    }
  }
}

String _stateEs(String s) => switch (s) {
      'running' => 'trabajando',
      'waiting_permission' => 'esperando tu permiso',
      'idle' => 'listo',
      'closed' => 'cerrada',
      'error' => 'error',
      _ => s,
    };
