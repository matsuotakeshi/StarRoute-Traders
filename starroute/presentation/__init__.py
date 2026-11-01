import string
from pathlib import Path
from ..model import GameError
from ..settings import read_json

class Presentation:
    def __init__(self, language='ja', files=None):
        if language not in ('ja', 'en'):
            raise GameError('INVALID_LANGUAGE')
        self.language = language
        base=Path(__file__).parent
        schema=read_json(base/'schema.json','INVALID_LOCALE')
        paths=files if files is not None else {lang:base/'locales'/(lang+'.json') for lang in ('ja','en')}
        packs={}
        try:
            if set(paths)!={'ja','en'}:raise ValueError('languages')
            for lang,path in paths.items():
                data=read_json(path,'INVALID_LOCALE')
                if not isinstance(data,dict) or set(data)!={'messages','errors','names'}:
                    raise ValueError('locale fields')
                if not isinstance(data['messages'],dict) or not isinstance(data['errors'],dict):raise ValueError('mapping')
                if set(data['messages'])!=set(schema['messages']) or set(data['errors'])!=set(schema['errors']):
                    raise ValueError('keys')
                for key,text in data['messages'].items():
                    if not isinstance(text,str):raise ValueError('message')
                    fields=set()
                    for _,field,spec,conversion in string.Formatter().parse(text):
                        if field is not None:
                            if not field or '.' in field or '[' in field or '{' in spec or '}' in spec or conversion is not None:
                                raise ValueError('format field')
                            if spec != schema['formats'][key].get(field):raise ValueError('format specification')
                            fields.add(field)
                    if fields!=set(schema['messages'][key]):raise ValueError('placeholders')
                if any(not isinstance(value,str) for value in data['errors'].values()):raise ValueError('error string')
                if not isinstance(data['names'],dict) or set(data['names'])-{'planets','ships','goods','resources'}:
                    raise ValueError('names')
                for mapping in data['names'].values():
                    if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) for k,v in mapping.items()):
                        raise ValueError('name string')
                packs[lang]=data
        except (KeyError,TypeError,ValueError):
            raise GameError('INVALID_LOCALE') from None
        self.data=packs[language]
        self.canonical_names=schema['canonical_names']

    def text(self, key, **params):
        return self.data['messages'][key].format(**params)

    def name(self, kind, key, fallback):
        original=self.canonical_names.get(kind,{})
        if key in original and fallback!=original[key]:
            return fallback
        return self.data['names'].get(kind, {}).get(key, fallback)

    def error(self, code):
        return self.text('error', message=self.data['errors'].get(code, code))
