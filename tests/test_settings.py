import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from starroute.settings import Settings, DEFAULT_SETTINGS
from starroute.catalog import Catalog
from starroute.presentation import Presentation
from starroute.model import GameError

ROOT = Path(__file__).resolve().parents[1]

class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.settings = json.loads(DEFAULT_SETTINGS.read_text())
        self.settings.update(default_language='en', game_file='game.json',
                             inter_bbs_file='inter.json', language_files={'ja':'ja.json','en':'en.json'})
        self.game = json.loads((ROOT/'starroute/config/game.json').read_text(encoding='utf-8'))
        self.game['starting']['cash'] = 7000
        self.save('runtime.json', self.settings)
        self.save('game.json', self.game)
        self.save('inter.json', {'format_version':1,'enabled':False,'bbs_id':None})
        for lang in ('ja','en'):
            self.save(lang+'.json', json.loads((ROOT/f'starroute/presentation/locales/{lang}.json').read_text(encoding='utf-8')))

    def save(self, name, data):
        (self.base/name).write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')

    def cli(self, command, *extra, expected=0, db='world.db'):
        r=subprocess.run([sys.executable,'-m','starroute','--settings',str(self.base/'runtime.json'),
                          '--db',str(self.base/db),'--player','p','--command',command,*extra],
                         cwd=ROOT,text=True,encoding='utf-8',capture_output=True)
        self.assertEqual(r.returncode,expected,r.stdout+r.stderr)
        return r.stdout+r.stderr

    def test_relative_paths(self):
        settings=Settings.load(self.base/'runtime.json')
        self.assertEqual(settings.game_file,self.base/'game.json')
        self.assertEqual(settings.default_language,'en')

    def test_legacy_default_catalog_identical(self):
        self.assertEqual(Catalog.load().canonical(),Catalog.load(ROOT/'starroute/data/demo.json').canonical())

    def test_existing_world_retains_parameters(self):
        self.cli('register Captain')
        self.game['starting']['cash']=9000;self.save('game.json',self.game)
        self.assertIn('7,000',self.cli('status'))
        self.cli('register Captain',db='new.db')
        self.assertIn('9,000',self.cli('status',db='new.db'))
        (self.base/'game.json').unlink()
        self.assertIn('7,000',self.cli('status'))

    def test_language_precedence_and_override_not_saved(self):
        self.cli('register Captain')
        english=self.cli('status')
        self.cli('language ja')
        japanese=self.cli('status')
        self.assertNotEqual(english,japanese)
        self.assertEqual(english,self.cli('status','--lang','en'))
        self.assertEqual(japanese,self.cli('status'))

    def test_default_change_for_unset_preference(self):
        self.cli('register Captain');english=self.cli('status')
        self.settings['default_language']='ja';self.save('runtime.json',self.settings)
        self.assertNotEqual(english,self.cli('status'))
        self.cli('language en')
        self.assertEqual(english,self.cli('status'))

    def test_custom_translation(self):
        data=json.loads((self.base/'en.json').read_text(encoding='utf-8'))
        data['names']['goods']['grain']='Custom Grain';self.save('en.json',data)
        view=Presentation('en',Settings.load(self.base/'runtime.json').language_files)
        self.assertEqual(view.name('goods','grain',view.canonical_names['goods']['grain']),'Custom Grain')
        self.assertEqual(view.name('goods','grain','Custom catalog name'),'Custom catalog name')

    def test_invalid_locale_does_not_create_database(self):
        for value in ([], {'bad':'value'}):
            data=json.loads((ROOT/'starroute/presentation/locales/en.json').read_text(encoding='utf-8'))
            data['messages']=value;self.save('en.json',data)
            self.assertIn('INVALID_LOCALE',self.cli('register Captain',expected=1))
            self.assertFalse((self.base/'world.db').exists())

    def test_invalid_placeholder_rejected(self):
        data=json.loads((self.base/'en.json').read_text(encoding='utf-8'))
        data['messages']['error']='{message.attribute}';self.save('en.json',data)
        self.cli('register Captain',expected=1)
        self.assertFalse((self.base/'world.db').exists())

    def test_duplicate_key_rejected(self):
        (self.base/'runtime.json').write_text('{"format_version":1,"format_version":1}')
        self.assertIn('INVALID_SETTINGS',self.cli('status',expected=1))

    def test_invalid_default_language(self):
        self.settings['default_language']='xx';self.save('runtime.json',self.settings)
        self.assertIn('INVALID_SETTINGS',self.cli('status',expected=1))

    def test_inter_bbs_enabled_rejected(self):
        self.save('inter.json',{'format_version':1,'enabled':True,'bbs_id':'bbs_a'})
        self.assertIn('INTER_BBS_NOT_IMPLEMENTED',self.cli('register Captain',expected=1))
        self.assertFalse((self.base/'world.db').exists())

    def test_inter_bbs_id_does_not_change_local_identity(self):
        self.save('inter.json',{'format_version':1,'enabled':False,'bbs_id':'bbs_a'})
        self.cli('register Captain')
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.base/'world.db')) as db:
            self.assertEqual(db.execute('SELECT bbs_id FROM bbs_accounts').fetchone()[0],'local')

    def test_explicit_catalog_still_rejects_existing_mismatch(self):
        self.cli('register Captain')
        self.game['starting']['cash']=9000;self.save('game.json',self.game)
        self.cli('status','--config',str(self.base/'game.json'),expected=1)
        self.assertIn('7,000',self.cli('status'))
