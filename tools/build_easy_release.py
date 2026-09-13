"""Build the beginner Windows package from a clean release checkout."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware-dir', type=Path, required=True)
    parser.add_argument('--idf-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Build on Windows x64 with requirements-build-exe.txt')
    if subprocess.check_output(['git','status','--porcelain'],cwd=ROOT).strip():
        raise ValueError('Commit the release sources before building user packages')
    revision = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    fw = args.firmware_dir.resolve()
    description = json.loads((fw/'project_description.json').read_text(encoding='utf-8'))
    version = description['project_version']
    app = fw/'FoloToy-AI-Passport.bin'
    if app.read_bytes()[48:80].split(b'\0')[0].decode() != version or app.stat().st_size > 0x300000:
        raise ValueError('Invalid application version or partition size')
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=False)
    desktop = output/'desktop-build'
    subprocess.run([sys.executable,str(ROOT/'tools/build_windows_exe.py'),'--output',str(desktop)],check=True)
    build_meta=json.loads((ROOT/'build-windows-exe/notices/BUILD.json').read_text(encoding='utf-8'))
    if build_meta['version']!=version or build_meta['base_commit']!=revision or build_meta['uncommitted_sources']:
        raise ValueError('Desktop and firmware versions must match the release checkout')
    stage = output/f'Passport-Windows-x64-v{version}'
    stage.mkdir()
    shutil.copy2(desktop/'Passport.exe',stage/'Passport.exe')
    shutil.copy2(ROOT/'docs/QUICKSTART.zh_CN.md',stage/'先读我-三步开始.md')
    shutil.copytree(ROOT/'build-windows-exe/notices',stage/'notices')
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--console',
        '--name','升级设备固件','--collect-all','esptool','--copy-metadata','esptool',
        '--distpath',str(stage),'--workpath',str(ROOT/'build-windows-exe/flasher'),
        '--specpath',str(ROOT/'build-windows-exe'),str(ROOT/'tools/flash_firmware.py')],check=True)
    # Both checks are read-only: no serial reset or flash operation.
    subprocess.run([str(stage/'升级设备固件.exe'),'--esptool','version'],check=True)
    subprocess.run([str(stage/'升级设备固件.exe'),'--list'],check=True)
    (stage/'firmware').mkdir()
    hashes={}
    for name,source in {'FoloToy-AI-Passport.bin':app,'partition-table.bin':fw/'partition_table/partition-table.bin'}.items():
        shutil.copy2(source,stage/'firmware'/name);hashes[name]=digest(source)
    manifest=dict(version=version,commit=revision,chip='esp32c3',app_offset='0x10000',sha256=hashes)
    (stage/'firmware/manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for label,root in [('esp-idf',args.idf_dir.resolve()),('managed_components',ROOT/'managed_components')]:
        for source in root.rglob('*'):
            if source.is_file() and source.name.lower().startswith(('license','licence','copying','notice')):
                dest=stage/'firmware/THIRD_PARTY_LICENSES'/label/source.relative_to(root)
                dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    (stage/'VERSION.json').write_text(json.dumps({'version':version,'commit':revision},indent=2),encoding='utf-8')
    checksums=''.join(f'{digest(p)}  {p.relative_to(stage).as_posix()}\n' for p in sorted(stage.rglob('*')) if p.is_file())
    (stage/'SHA256SUMS.txt').write_text(checksums,encoding='utf-8')
    archive=output/(stage.name+'.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(output).as_posix())
    (output/'SHA256SUMS.txt').write_text(f'{digest(archive)}  {archive.name}\n',encoding='ascii')
    print(json.dumps({'archive':str(archive),'sha256':digest(archive),'commit':revision},indent=2))


if __name__=='__main__':
    main()
