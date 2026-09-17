"""Check dashboard structure and export interpolated PromQL for promtool.

This checks query syntax using the same Prometheus version as the deployment.
Prometheus rule fixtures separately verify missing data and calculation behavior.
Grafana-specific variables are replaced with representative values before parsing.
"""

from pathlib import Path
import json
import re
import sys


def panels(items):
    """Visit panels inside collapsed rows as well as the visible grid."""
    for panel in items:
        yield panel
        yield from panels(panel.get('panels', []))


def interpolate(expression):
    """Replace supported Grafana macros without changing PromQL structure."""
    replacements = {
        '$__rate_interval': '5m', '$__interval': '1m', '$__range_s': '3600',
        '$__range': '1h', '$__interval_ms': '60000', '$__from': '1000', '$__to': '2000',
    }
    for variable, value in sorted(replacements.items(), key=lambda item: -len(item[0])):
        expression = expression.replace(variable, value)
    expression = re.sub(r'\$\{(?:instance|baseline_instance|candidate_instance):regex\}', lambda _: re.escape('host.docker.internal:8070'), expression)
    expression = re.sub(r'\$\{(?:instance|baseline_instance|candidate_instance)(?::[^}]+)?\}', 'host.docker.internal:8070', expression)
    expression = re.sub(r'\$(?:baseline_instance|candidate_instance|instance)\b', 'host.docker.internal:8070', expression)
    if re.search(r'\$(?:\{|[A-Za-z_])', expression):
        raise ValueError(f'Unresolved query variable: {expression}')
    return expression


def main():
    """Validate all provisioned boards and emit a temporary rule document."""
    root = Path(__file__).resolve().parents[1]
    rules = []
    uids = set()
    for path in sorted((root / 'grafana/dashboards').glob('*.json')):
        board = json.loads(path.read_text())
        assert board['uid'] not in uids, f'Duplicate dashboard UID: {path}'
        uids.add(board['uid'])
        ids = set()
        for panel in panels(board['panels']):
            identity = f'{path.name}: {panel.get("title")}'
            assert panel['id'] not in ids, f'Duplicate panel ID: {identity}'
            ids.add(panel['id'])
            grid = panel['gridPos']
            assert 0 <= grid['x'] < 24 and 0 < grid['w'] <= 24 - grid['x'], identity
            assert grid['y'] >= 0 and grid['h'] > 0, identity
            for target in panel.get('targets', []):
                datasource = target.get('datasource', panel.get('datasource', {}))
                if (isinstance(datasource, str) and datasource.lower() == 'prometheus' or isinstance(datasource, dict) and datasource.get('type') == 'prometheus') and target.get('expr'):
                    rules.append({'record': f'dashboard_syntax_{len(rules)}', 'expr': interpolate(target['expr'])})
        visible = board['panels']
        for index, left in enumerate(visible):
            a = left['gridPos']
            for right in visible[index + 1:]:
                b = right['gridPos']
                assert not (a['x'] < b['x'] + b['w'] and b['x'] < a['x'] + a['w'] and a['y'] < b['y'] + b['h'] and b['y'] < a['y'] + a['h']), f'Overlapping panels: {path.name}: {left["title"]} / {right["title"]}'
    Path(sys.argv[1]).write_text(json.dumps({'groups': [{'name': 'dashboard-syntax', 'rules': rules}]}))
    print(f'Validated {len(uids)} dashboards and extracted {len(rules)} PromQL queries.')


if __name__ == '__main__':
    main()
