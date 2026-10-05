// Counter screen: a Flutter widget with state.
import 'package:flutter/material.dart';

/// Max taps before reset.
const int kMaxTaps = 10;

final _private = r'raw ${not} \ { string';

/// A counter page.
class CounterPage extends StatefulWidget {
  const CounterPage({super.key, this.title = 'x'});

  final String title;

  CounterPage.named(int x) : title = '{', super();

  @override
  State<CounterPage> createState() => _CounterPageState();
}

class _CounterPageState extends State<CounterPage> {
  int _count = 0;
  static const greeting = '''multi { line
  ${'nested'} }''';

  void _increment() {
    setState(() {
      _count++;
    });
  }

  String get label => 'Count: ${_count > 1 ? "many {" : '$_count'}';

  set count(int v) {
    _count = v;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Builder(builder: (c) {
        return Text(label);
      }),
    );
  }

}

mixin Loud on Object {
  void shout() {}
}

extension StringX on String {
  String twice() => this + this;
}

enum Color { red, green, blue }

enum Planet {
  mercury(3.3),
  venus(4.8);

  const Planet(this.mass);
  final double mass;
}

typedef Callback = void Function(int);

Future<void> main() async {
  print('hi');
}
