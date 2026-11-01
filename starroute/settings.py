"""Local configuration routing. No credentials, network activity or game mutations."""
from dataclasses import dataclass
from pathlib import Path
import json
from .model import GameError
from .catalog import identifier

DEFAULT_SETTINGS = Path(__file__).parent/'config/runtime.json'


def read_json(path, error='INVALID_SETTINGS'):
    def unique(pairs):
        result={}
        for key,value in pairs:
            if key in result:raise ValueError('duplicate key')
            result[key]=value
        return result
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=unique)
    except (OSError,ValueError,TypeError):
        raise GameError(error) from None


@dataclass(frozen=True)
class Settings:
    default_language: str
    game_file: Path
    inter_bbs_file: Path
    language_files: dict
    inter_bbs: dict

    def site_settings(self):
        """Detached site-only settings; file routing is not an effective game rule."""
        return {'default_language': self.default_language,
                'language_files': {k: str(v) for k,v in self.language_files.items()},
                'inter_bbs': dict(self.inter_bbs)}

    @classmethod
    def load(cls, path=None):
        path=Path(path) if path else DEFAULT_SETTINGS
        raw=read_json(path)
        try:
            if not isinstance(raw,dict) or set(raw)!={'format_version','default_language','game_file','inter_bbs_file','language_files'}:
                raise ValueError('fields')
            if type(raw['format_version']) is not int or raw['format_version']!=1:
                raise ValueError('version')
            if raw['default_language'] not in ('ja','en') or not isinstance(raw['language_files'],dict) or set(raw['language_files'])!={'ja','en'}:
                raise ValueError('languages')
            def resolve(value):
                if not isinstance(value,str) or not value.strip():raise ValueError('path')
                return (path.resolve().parent/value).resolve()
            game=resolve(raw['game_file']);inter=resolve(raw['inter_bbs_file'])
            languages={key:resolve(value) for key,value in raw['language_files'].items()}
        except (TypeError,ValueError,KeyError,OSError):
            raise GameError('INVALID_SETTINGS') from None
        ib=read_json(inter)
        try:
            if not isinstance(ib,dict) or set(ib)!={'format_version','enabled','bbs_id'} or type(ib['format_version']) is not int or ib['format_version']!=1 or type(ib['enabled']) is not bool:
                raise ValueError('inter-bbs')
            if ib['bbs_id'] is not None:
                identifier(ib['bbs_id'])
                if ib['bbs_id']=='local':raise ValueError('reserved local namespace')
        except (ValueError,TypeError,GameError):
            raise GameError('INVALID_SETTINGS') from None
        if ib['enabled']:
            raise GameError('INTER_BBS_NOT_IMPLEMENTED')
        return cls(raw['default_language'],game,inter,languages,ib)
