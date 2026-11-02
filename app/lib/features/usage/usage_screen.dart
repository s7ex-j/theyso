import 'dart:async';

import 'package:fl_chart/fl_chart.dart';
import 'package:flutter/material.dart';

import '../../core/connection.dart';

/// Tokens per day, cost vs. "list-price equivalent" (savings with free models),
/// breakdown by model/profile, and how fast you answer permission requests.
class UsageScreen extends StatefulWidget {
  const UsageScreen({super.key, required this.conn});
  final TheysoConnection conn;

  @override
  State<UsageScreen> createState() => _UsageScreenState();
}

class _UsageScreenState extends State<UsageScreen> {
  Map<String, dynamic>? _data;
  int _days = 7;
  StreamSubscription<Frame>? _sub;

  @override
  void initState() {
    super.initState();
    _sub = widget.conn.frames.listen((f) {
      if (f['type'] == 'usage.result') setState(() => _data = f);
    });
    _load();
  }

  void _load() => widget.conn.send({'type': 'usage.query', 'days': _days});

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final d = _data;
    return Scaffold(
      appBar: AppBar(title: const Text('Uso y costos'), actions: [
        SegmentedButton<int>(
          segments: const [
            ButtonSegment(value: 7, label: Text('7d')),
            ButtonSegment(value: 30, label: Text('30d')),
          ],
          selected: {_days},
          onSelectionChanged: (s) {
            setState(() => _days = s.first);
            _load();
          },
        ),
        const SizedBox(width: 8),
      ]),
      body: d == null
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              _kpis(context, d),
              const SizedBox(height: 16),
              SizedBox(height: 220, child: _tokensChart(context, d)),
              const SizedBox(height: 24),
              Text('Por modelo / perfil', style: Theme.of(context).textTheme.titleMedium),
              for (final m in (d['by_model'] as List).cast<Map<String, dynamic>>())
                ListTile(
                  dense: true,
                  title: Text('${m['model']} · ${m['profile']}'),
                  subtitle: Text('${m['turns']} turnos · ${m['input_tokens']}→${m['output_tokens']} tokens'),
                  trailing: Text(_costLabel(m)),
                ),
              const SizedBox(height: 16),
              Text('Herramientas', style: Theme.of(context).textTheme.titleMedium),
              for (final t in (d['tools'] as List).cast<Map<String, dynamic>>())
                ListTile(
                  dense: true,
                  title: Text('${t['tool']}'),
                  subtitle: Text('${t['calls']} llamadas · ${t['allowed']} ✔ · ${t['denied']} ✘'),
                  trailing: t['avg_human_latency_ms'] != null
                      ? Text('responde en ${((t['avg_human_latency_ms'] as num) / 1000).toStringAsFixed(1)} s')
                      : null,
                ),
            ]),
    );
  }

  Widget _kpis(BuildContext context, Map<String, dynamic> d) {
    final days = (d['by_day'] as List).cast<Map<String, dynamic>>();
    final spent = days.fold<double>(0, (a, e) => a + (e['cost_usd'] as num).toDouble());
    final saved = days.fold<double>(0, (a, e) => a + (e['list_equivalent_usd'] as num).toDouble());
    final tokens = days.fold<int>(0, (a, e) => a + (e['input_tokens'] as int) + (e['output_tokens'] as int));
    Widget kpi(String label, String value) => Expanded(
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: Column(children: [
                Text(value, style: Theme.of(context).textTheme.titleLarge),
                Text(label, style: Theme.of(context).textTheme.labelSmall, textAlign: TextAlign.center),
              ]),
            ),
          ),
        );
    return Row(children: [
      kpi('gastado', '\$${spent.toStringAsFixed(2)}'),
      kpi('equivalente a precio de lista (vía router)', '\$${saved.toStringAsFixed(2)}'),
      kpi('tokens', _compact(tokens)),
    ]);
  }

  Widget _tokensChart(BuildContext context, Map<String, dynamic> d) {
    final days = (d['by_day'] as List).cast<Map<String, dynamic>>();
    final c = Theme.of(context).colorScheme;
    return BarChart(BarChartData(
      borderData: FlBorderData(show: false),
      gridData: const FlGridData(drawVerticalLine: false),
      titlesData: FlTitlesData(
        topTitles: const AxisTitles(),
        rightTitles: const AxisTitles(),
        leftTitles: AxisTitles(sideTitles: SideTitles(showTitles: true, reservedSize: 44,
            getTitlesWidget: (v, _) => Text(_compact(v.toInt()), style: const TextStyle(fontSize: 10)))),
        bottomTitles: AxisTitles(sideTitles: SideTitles(showTitles: true,
            getTitlesWidget: (v, _) {
              final i = v.toInt();
              return i < days.length ? Text((days[i]['date'] as String).substring(5), style: const TextStyle(fontSize: 10)) : const SizedBox();
            })),
      ),
      barGroups: [
        for (var i = 0; i < days.length; i++)
          BarChartGroupData(x: i, barRods: [
            BarChartRodData(
              toY: ((days[i]['input_tokens'] as int) + (days[i]['output_tokens'] as int)).toDouble(),
              color: c.primary,
              width: 14,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(4)),
            ),
          ]),
      ],
    ));
  }
}

String _costLabel(Map<String, dynamic> m) {
  final cost = (m['cost_usd'] as num).toStringAsFixed(3);
  return switch (m['cost_basis']) {
    'list_equivalent' => '≈\$$cost lista',
    'profile_price' => '\$$cost (tarifa perfil)',
    _ => '\$$cost',
  };
}

String _compact(int n) => n >= 1e6 ? '${(n / 1e6).toStringAsFixed(1)}M' : n >= 1e3 ? '${(n / 1e3).toStringAsFixed(1)}k' : '$n';
