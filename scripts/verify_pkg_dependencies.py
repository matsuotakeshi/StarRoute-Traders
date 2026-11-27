"""Reject release packages whose dependency manifests disagree with the Ports definitions."""
import argparse
import json
import subprocess
from pathlib import Path

PACKAGES = ('starroute-traders-client', 'starroute-traders', 'starroute-traders-master')


def verify(directory):
    manifests = {}
    for name in PACKAGES:
        matches = [p for p in directory.glob(name+'-*.pkg')
                   if p.name[len(name)+1:len(name)+2].isdigit()]
        if len(matches) != 1:
            raise ValueError(f'Expected one package for {name}')
        raw = subprocess.check_output(['tar', '-xOf', str(matches[0].resolve()), '+MANIFEST'])
        manifest = json.loads(raw)
        if manifest['name'] != name or manifest['origin'] != 'games/'+name:
            raise ValueError(f'Wrong manifest identity for {name}')
        manifests[name] = manifest
    for index, name in enumerate(PACKAGES):
        manifest = manifests[name]
        deps = manifest.get('deps', {})
        siblings = set(deps) & set(PACKAGES)
        expected = {PACKAGES[index-1]} if index else set()
        if siblings != expected:
            raise ValueError(f'Incorrect StarRoute dependencies in {name}')
        for dependency in expected:
            row = deps[dependency]
            target = manifests[dependency]
            if (row['origin'],row['version']) != (target['origin'],target['version']):
                raise ValueError(f'Incorrect dependency version or origin in {name}')
    return {name: manifest['version'] for name,manifest in manifests.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package_directory', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.package_directory)))
    except (subprocess.CalledProcessError, ValueError, KeyError, OSError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
