"""Run the existing unittest suite with machine-readable evidence; no production data."""
import argparse,json,os,platform,shutil,sqlite3,ssl,subprocess,sys,tempfile,time,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def environment():
    if sys.version_info < (3,10):raise RuntimeError('Python 3.10 or newer is required')
    tools={name:shutil.which(name) for name in ('git','ssh-keygen','openssl')}
    if not all(tools.values()):raise RuntimeError('Required test tools missing: '+str([k for k,v in tools.items() if not v]))
    return {'python':sys.version,'platform':platform.platform(),'sqlite':sqlite3.sqlite_version,'ssl':ssl.OPENSSL_VERSION,'tools':tools}

def execute(suite,stream=sys.stderr):
    start=time.monotonic();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    return {'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'skipped':[{'test':test.id(),'reason':reason} for test,reason in result.skipped],
            'unexpected_successes':[t.id() for t in result.unexpectedSuccesses],
            'expected_failures':[t.id() for t,_ in result.expectedFailures],
            'seconds':round(time.monotonic()-start,3),'ok':result.wasSuccessful() and result.testsRun>0,
            'failed_tests':[{'test':t.id(),'traceback':trace} for t,trace in result.failures+result.errors]}

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    output=a.output.resolve();output.mkdir(parents=True,exist_ok=True);os.chdir(ROOT)
    report={'ok':False,'source_sha':os.environ.get('GITHUB_SHA') or (ROOT/'.ci-source-sha').read_text().strip() if (ROOT/'.ci-source-sha').exists() else os.environ.get('GITHUB_SHA')}
    try:
        report['environment']=environment();print(json.dumps(report['environment']),flush=True)
        # All generated DBs/keys remain in a private run-specific directory, not in the checkout.
        with tempfile.TemporaryDirectory(prefix='starroute-tests-') as private:
            previous=tempfile.tempdir;tempfile.tempdir=str(Path(private).resolve())
            try:report.update(execute(unittest.defaultTestLoader.discover(str(ROOT/'tests'),top_level_dir=None)))
            finally:tempfile.tempdir=previous
        if report['ok']:
            code=subprocess.call([sys.executable,'scripts/demo.py'],cwd=ROOT)
            report['cli_exit_code']=code;report['ok']=code==0
            if report['ok']:
                with tempfile.TemporaryDirectory(prefix='srt-release-demos-') as demo:
                    for name in ('trade_cycle','exploration'):
                        code=subprocess.call([sys.executable,'scripts/'+name+'_demo.py','--directory',str(Path(demo)/name)],cwd=ROOT)
                        report[name+'_exit_code']=code
                        if code:report['ok']=False;break
    except Exception as error:report['error']=str(error)
    (output/'tests.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('SRT_UNIT_SUMMARY '+json.dumps({k:v for k,v in report.items() if k not in ('failed_tests','environment')}),flush=True)
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())
