"""Build the standalone generator with data validators only, without game/server code."""
import argparse
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VALIDATORS=('__init__','model','catalog','ships','navigation','economy','production','development',
            'regional','events','industry_effects','rules','generation_contract','universe','universe_package','settings','phase3_policy')


def build(output):
    paths=[ROOT/'starroute'/(name+'.py') for name in VALIDATORS]
    paths += [ROOT/'starroute/data/normal-planets.json']
    paths += list((ROOT/'srt_universe_generator').glob('*.py'))
    paths += [ROOT/'examples'/name for name in ('industry-effects-trial.json','universe-generator-trial.json','industry-levels-trial.json','phase3-trial.json','phase3-generator.json')]
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as bundle:
        for path in paths:bundle.write(path,path.relative_to(ROOT).as_posix())
        bundle.writestr('README.txt',
            'Standalone offline generator (Python 3.10+). Shared validators are bundled; no Game Engine, application, database or BBS client is included.\n'
            'Run: python -m srt_universe_generator --template examples/industry-effects-trial.json --parameters examples/universe-generator-trial.json --levels examples/industry-levels-trial.json --seed PRIVATE-SEED --output private-universe.json\n'
            'The output contains private maxima and reproduction data. Store it outside public web directories; never send it to BBS sites.\n'
            'Validation is performed before output. Existing files are never overwritten. Registration and activation are separate Phase 4 functions.\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);build(p.parse_args().output)
