"""One-release staging task; product files are checked out at the validated SHA."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

SHA = '3771362e821827944914f298a025f43c9165485a'
VERSION = '0.2.6'
REPO = 'gycodex/codex-passport-companion'
RELEASE_ID = 441487486
SOURCE = Path('source').resolve()
OUT = Path('cloud-output').resolve()
NAMES = ['Passport-Windows-x64-v0.2.6.zip', 'Passport-Desktop-Windows-x64-v0.2.6.zip',
         'FoloToy-AI-Passport-v0.2.6.bin', 'SHA256SUMS.txt']

def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def licenses():
    target = SOURCE / 'build-ci/THIRD_PARTY_LICENSES'
    for label, root in [('esp-idf', Path(os.environ['IDF_PATH'])), ('managed_components', SOURCE/'managed_components')]:
        for path in root.rglob('*'):
            if path.is_file() and path.name.lower().startswith(('license','licence','copying','notice')):
                dest = target/label/path.relative_to(root)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

def package():
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=SOURCE,text=True).strip() == SHA
    legal = SOURCE/'build-ci/THIRD_PARTY_LICENSES'
    assert (legal/'esp-idf').is_dir() and (legal/'managed_components').is_dir()
    shutil.copytree(legal/'managed_components', SOURCE/'managed_components', dirs_exist_ok=True)
    subprocess.run([sys.executable,str(SOURCE/'tools/build_easy_release.py'),
        '--firmware-dir',str(SOURCE/'build-ci'),'--idf-dir',str(legal/'esp-idf'),
        '--output',str(OUT)],cwd=SOURCE,check=True)
    stage = OUT/'Passport-Windows-x64-v0.2.6'
    shutil.copy2(OUT/'desktop-build/Passport-Windows-x64.zip', OUT/NAMES[1])
    shutil.copy2(stage/'firmware/FoloToy-AI-Passport.bin', OUT/NAMES[2])
    version = json.loads((stage/'VERSION.json').read_text(encoding='utf-8'))
    build = json.loads((stage/'notices/BUILD.json').read_text(encoding='utf-8'))
    assert version == {'version':VERSION,'commit':SHA}
    assert build['base_commit']==SHA and not build['uncommitted_sources']
    for name in NAMES[:2]:
        with zipfile.ZipFile(OUT/name) as archive:
            assert archive.testzip() is None
            for member in archive.namelist():
                path = PurePosixPath(member)
                assert not path.is_absolute() and '..' not in path.parts
                assert path.name.lower() not in ('pairing.json','settings.json','credentials-270.json')
                assert path.suffix.lower() != '.log'
    with zipfile.ZipFile(OUT/NAMES[1]) as archive:
        assert archive.read('Passport.exe') == (stage/'Passport.exe').read_bytes()
    for line in (stage/'SHA256SUMS.txt').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ',1)
        assert sha256(stage/name) == digest, name
    (OUT/'SHA256SUMS.txt').write_text(''.join(sha256(OUT/n)+'  '+n+'\n' for n in NAMES[:3]),encoding='ascii')
    sys.path.insert(0,str(SOURCE/'tools'))
    from passport_desktop import Backend
    temp = Path(os.environ['RUNNER_TEMP'])/'passport-release-smoke-026'
    process = subprocess.Popen([str(stage/'Passport.exe'),'--passport-role','backend',
        '--port','18766','--config-dir',str(temp)],creationflags=subprocess.CREATE_NO_WINDOW)
    backend = Backend(18766,temp)
    try:
        deadline = time.monotonic()+45
        while True:
            try:
                backend.attach()
                break
            except OSError:
                assert process.poll() is None, 'Packaged backend exited early'
                if time.monotonic()>deadline:
                    raise RuntimeError('Packaged backend startup timeout')
                time.sleep(.25)
        assert not backend.request('api/status')['key_present']
        for resource in ('','app.js','style.css'):
            with backend.http.open(backend.url+resource,timeout=5) as response:
                assert response.status==200 and response.read()
        assert backend.request('api/exit',{})['ok']
        process.wait(timeout=20)
        assert process.returncode==0
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    result = {'repository':REPO,'version':VERSION,'commit':SHA,'workflow_run_id':os.environ['GITHUB_RUN_ID'],
        'zip_crc':True,'clean_source':True,'backend_smoke':True,'private_files_excluded':True,
        'files':[{'name':n,'size':(OUT/n).stat().st_size,'sha256':sha256(OUT/n)} for n in NAMES]}
    (OUT/'release-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('Packages and backend smoke checks passed',flush=True)

def upload():
    assert os.environ['GITHUB_REPOSITORY']==REPO
    token = os.environ['GH_TOKEN']
    api = 'https://api.github.com/repos/'+REPO
    def request(url,method='GET',data=None):
        headers={'Authorization':'Bearer '+token,'User-Agent':'Passport-release-ci',
                 'Accept':'application/vnd.github+json'}
        if data is not None:
            headers['Content-Type']='application/octet-stream'
        with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=headers,method=method),timeout=180) as response:
            return json.load(response)
    release=request(api+'/releases/'+str(RELEASE_ID))
    assert release['draft'] and release['tag_name']=='v'+VERSION and release['target_commitish']==SHA
    metadata=json.loads((OUT/'release-verification.json').read_text(encoding='utf-8'))
    assert metadata['commit']==SHA and metadata['backend_smoke']
    for item in metadata['files']:
        existing={a['name']:a for a in request(release['assets_url'])}
        if item['name'] in existing:
            assert existing[item['name']].get('digest')=='sha256:'+item['sha256'], 'Existing draft asset differs'
        else:
            url=release['upload_url'].split('{',1)[0]+'?'+urllib.parse.urlencode({'name':item['name']})
            uploaded=request(url,'POST',(OUT/item['name']).read_bytes())
            assert uploaded.get('digest')=='sha256:'+item['sha256']
        print('Uploaded and verified '+item['name'],flush=True)
    actual={a['name']:a for a in request(release['assets_url'])}
    assert set(actual)==set(NAMES)
    metadata['upload_complete']=True
    (OUT/'release-verification.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('RELEASE_VERIFICATION='+json.dumps(metadata),flush=True)

if __name__=='__main__':
    {'licenses':licenses,'package':package,'upload':upload}[sys.argv[1]]()
