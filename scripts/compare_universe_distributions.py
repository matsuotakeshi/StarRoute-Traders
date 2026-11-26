"""Generate an offline comparison of three synthetic universes."""
import argparse
import itertools
import json
import statistics
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from srt_universe_generator.levels import generate
from starroute.generation_contract import separation


def example(name):
    return json.loads((ROOT / 'examples' / (name + '.json')).read_text(encoding='utf8'))


def metrics(data, params):
    coordinates = data['universe']['coordinates']
    ids = [row['planet_id'] for row in coordinates]
    points = {row['planet_id']: (row['x'], row['y']) for row in coordinates}
    width, height = params['width'], params['height']

    def sector(pid):
        return points[pid][0] * 4 // width

    graph = {pid: [] for pid in ids}
    opened, closed = [], []
    for route in data['routes']:
        if route['is_open']:
            a, b, length = route['from'], route['to'], route['distance']
            graph[a].append((b, length))
            graph[b].append((a, length))
            opened.append(route)
        else:
            closed.append(route)
    distances = {}
    for start in ids:
        pending = [(start, None, 0)]
        while pending:
            node, parent, length = pending.pop()
            distances[start, node] = length
            pending.extend((other, node, length + step)
                           for other, step in graph[node] if other != parent)

    def mean(values):
        return round(statistics.mean(values), 2)

    pairs = list(itertools.combinations(ids, 2))
    cells = [[0] * 60 for _ in range(24)]
    for x, y in points.values():
        cells[y * 24 // height][x * 60 // width] += 1
    occupied_x = sorted({x for x, _ in points.values()})
    empty_columns = max(b - a - 1 for a, b in itertools.pairwise([-1, *occupied_x, width]))
    lengths = [route['distance'] for route in opened]
    best = max(closed, key=lambda r: distances[r['from'], r['to']] - r['distance'])
    return {
        'dimensions': [width, height],
        'minimum_pair_chebyshev': min(separation(points[a], points[b]) for a, b in pairs),
        'mean_nearest_chebyshev': mean(min(separation(points[a], points[b]) for b in ids if a != b) for a in ids),
        'mean_pair_chebyshev': mean(separation(points[a], points[b]) for a, b in pairs),
        'longest_empty_column_run': empty_columns,
        'initial_routes': len(opened),
        'donation_routes': len(closed),
        'open_length_bins': {f'{lo}-{hi}': sum(lo <= n <= hi for n in lengths)
                             for lo, hi in ((1, 15), (16, 30), (31, 60), (61, 120))},
        'mean_open_path': mean(distances[a, b] for a, b in pairs),
        'mean_same_sector_path': mean(distances[a, b] for a, b in pairs if sector(a) == sector(b)),
        'mean_other_sector_path': mean(distances[a, b] for a, b in pairs if sector(a) != sector(b)),
        'best_donation_route': {k: best[k] for k in ('id', 'from', 'to', 'distance')},
        'best_donation_route_current_distance': distances[best['from'], best['to']],
        'map': [''.join('.' if n == 0 else '*' if n == 1 else str(n) for n in row) for row in cells],
        'coordinates': coordinates,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--seed', default='cluster-comparison-0')
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=False)
    template, levels = example('release-world'), example('industry-levels-trial')
    fixtures = {
        'uniform-240': 'connected-universe-trial',
        'clustered-240': 'clustered-universe-trial',
        'clustered-360': 'clustered-universe-large-comparison',
    }
    report = {'seed': args.seed, 'template': 'release-world', 'results': {}}
    for label, name in fixtures.items():
        params = example(name)
        identity = str(uuid.uuid5(uuid.NAMESPACE_URL, 'starroute-comparison/' + label + '/' + args.seed))
        data = generate(template, params, levels, args.seed, identity)
        result = metrics(data, params)
        report['results'][label] = result
        (args.directory / (label + '.txt')).write_text('\n'.join(result['map']) + '\n', encoding='ascii')
    (args.directory / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
