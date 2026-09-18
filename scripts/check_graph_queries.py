"""Embed and exercise Infinity graph queries against raw diagnostics fixtures.

The jq files in grafana/graphs are the editable source for provisioned queries.
Run with --write to refresh dashboards after editing them. The default --check
mode rejects stale embedded expressions and verifies graph relationships with jq.
Infinity requires separate nodes and edges targets, so each embeds the same source.
https://grafana.com/docs/plugins/yesoreyeram-infinity-datasource/latest/advanced-features/node-graph/
"""

from copy import deepcopy
from pathlib import Path
from urllib.parse import quote
import argparse
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
GRAPHS = (
    ('room-graph.json', 2, 'room', 'room_uuid'),
    ('room-graph.json', 4, 'user', 'room_uuid'),
    ('user-diagnostics.json', 14, 'user', 'room_id'),
)


def expression(name, selected='${user_id:percentencode}'):
    """Bind a URI-encoded user key without inserting user text as jq code.

    Grafana's JSON formatter leaves scalar strings unquoted. Percent encoding
    instead escapes delimiters and matches jq @uri for each raw diagnostics ID.
    """
    common = (ROOT / 'grafana/graphs/common.jq').read_text()
    query = (ROOT / f'grafana/graphs/{name}.jq').read_text()
    binding = json.dumps(selected) + ' as $selected |\n' if name == 'user' else ''
    return common + binding + query


def sync(write):
    """Check or update only graph targets and their descriptions."""
    for filename in dict.fromkeys(graph[0] for graph in GRAPHS):
        path = ROOT / 'grafana/dashboards' / filename
        board = json.loads(path.read_text())
        for _, panel_id, name, room_var in filter(lambda graph: graph[0] == filename, GRAPHS):
            panel = next(panel for panel in board['panels'] if panel['id'] == panel_id)
            assert len(panel['targets']) == 2, f'{filename} panel {panel_id}: expected nodes and edges targets'
            for target, part in zip(panel['targets'], ('nodes', 'edges')):
                expected = {
                    'url': 'http://host.docker.internal:8070/internal/diagnostics/rooms/${' + room_var + ':percentencode}',
                    'parser': 'jq-backend',
                    'root_selector': expression(name) + f' | .{part}[]',
                    'columns': [],
                    'format': 'node-graph-' + part,
                }
                if write:
                    target.update(expected)
                else:
                    for field, value in expected.items():
                        assert target.get(field) == value, f'{filename} panel {panel_id}: stale {field}, run with --write'
            description = 'Current room diagnostics projected into users, sources and subscription paths. '
            if name == 'user':
                description += 'Shows the selected user and their producers and receivers through media workers. An absent user has no graph. '
            description += 'The time picker does not replay topology. Missing rooms return HTTP 404. Missing source or user observations remain visible as placeholders.'
            if write:
                panel['description'] = description
        if write:
            path.write_text(json.dumps(board, indent=2) + '\n')


def evaluate(query, detail):
    """Execute jq and surface parser or evaluation failures as process errors."""
    result = subprocess.run(['jq', '-c', query], input=json.dumps(detail), text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return [json.loads(line) for line in result.stdout.splitlines()]


def graph(name, detail, selected='7'):
    """Evaluate the same graph source embedded in every dashboard target."""
    return evaluate(expression(name, quote(selected, safe='-._~')), detail)[0]


def connected_graph(result):
    """Require distinct node and edge IDs and endpoints that exist in the graph."""
    nodes = {node['id'] for node in result['nodes']}
    assert len(nodes) == len(result['nodes']), 'Duplicate node IDs'
    assert len({edge['id'] for edge in result['edges']}) == len(result['edges']), 'Duplicate edge IDs'
    for edge in result['edges']:
        assert edge['source'] in nodes and edge['target'] in nodes, edge
    return {node['id']: node for node in result['nodes']}, {edge['id']: edge for edge in result['edges']}


def check_graphs():
    """Verify identity, path direction, route state and unavailable observations.

    The fixture includes shared workers, unobserved producers and sources,
    inactive routes and a numeric-looking string identity distinct from 7.
    """
    detail = json.loads((ROOT / 'tests/diagnostics-room.json').read_text())
    room = graph('room', detail)
    nodes, edges = connected_graph(room)
    assert len(nodes) == 11 and len(edges) == 13
    assert nodes['source:fixture-room:999']['subTitle'] == 'source not observed'
    assert nodes['user:fixture-room:007']['subTitle'] == 'unknown'
    assert nodes['source:fixture-room:101']['secondaryStat'] == '1 encodings / 2 downloads'
    assert edges['download:fixture-room:101:guest']['secondaryStat'] == 'inactive'
    assert edges['download:fixture-room:999:7']['color'] == 'yellow'
    assert edges['download:fixture-room:999:7']['strokeDasharray'] == '5, 5'
    assert edges['download:fixture-room:102:7']['detail__selected_rid'] == 'h'
    user = graph('user', detail)
    nodes, edges = connected_graph(user)
    assert 'user:fixture-room:99' not in nodes and 'source:fixture-room:104' not in nodes
    assert nodes['worker:0']['mainStat'] == '2 users'
    assert nodes['worker:0']['secondaryStat'] == '1 pub / 3 sub'
    assert edges['publish:fixture-room:101']['source'] == 'worker:0'
    assert edges['deliver:fixture-room:102:7']['source'] == 'source:fixture-room:102'
    assert edges['deliver:fixture-room:102:7']['target'] == 'worker:0'
    assert edges['consume:fixture-room:102:7']['target'] == 'user:fixture-room:7'
    assert edges['deliver:fixture-room:101:guest']['detail__direction'] == 'outbound'
    assert edges['deliver:fixture-room:102:7']['detail__direction'] == 'inbound'
    assert graph('user', detail, 'missing') == {'nodes': [], 'edges': []}
    assert graph('user', detail, '') == {'nodes': [], 'edges': []}
    string_user = graph('user', detail, '007')
    assert next(node for node in string_user['nodes'] if node['id'] == 'user:fixture-room:007')['title'] == '007 selected'
    for key in ['quote" slash\\ / space !\'()* ${room_id} % é', '7', '9223372036854775807']:
        escaped = deepcopy(detail)
        escaped['users'][0]['userId'] = key
        escaped['users'][0]['subscriptions'] = []
        escaped['users'][0]['publications'] = []
        escaped['sources'] = []
        for candidate in escaped['users'][1:]:
            candidate['subscriptions'] = []
        result = graph('user', escaped, key)
        nodes, _ = connected_graph(result)
        assert nodes['user:fixture-room:' + key]['title'] == key + ' selected'
    for field, value in [('userId', 9223372036854775807), ('userId', -9223372036854775808), ('sourceId', 18446744073709551615)]:
        unsafe = deepcopy(detail)
        (unsafe['users'][0] if field == 'userId' else unsafe['sources'][0])[field] = value
        for name in ('room', 'user'):
            try:
                graph(name, unsafe)
            except RuntimeError as error:
                assert 'Infinity JSON integer precision' in str(error)
            else:
                raise AssertionError('Unsafe numeric graph identity was accepted')
    empty = deepcopy(detail)
    empty['users'] = []
    empty['sources'] = []
    empty['summary'].update(userCount=0, publicationCount=0, subscriptionCount=0, sourceCount=0)
    assert len(connected_graph(graph('room', empty))[0]) == 1
    assert graph('user', empty) == {'nodes': [], 'edges': []}
    for filename, panel_id, name, _ in GRAPHS:
        board = json.loads((ROOT / 'grafana/dashboards' / filename).read_text())
        panel = next(panel for panel in board['panels'] if panel['id'] == panel_id)
        for target, part in zip(panel['targets'], ('nodes', 'edges')):
            query = target['root_selector'].replace('${user_id:percentencode}', '7')
            assert evaluate(query, detail) == (room if name == 'room' else user)[part]
    print('Validated all six embedded graph queries, graph paths and encoded user identities.')


def main():
    """Regenerate provisioned expressions on request and always run fixtures."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    sync(args.write)
    check_graphs()


if __name__ == '__main__':
    main()
