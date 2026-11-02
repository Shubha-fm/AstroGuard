#!/usr/bin/env python3
"""Create a reviewable AstroGuard research archive from the current project directory.
No upload to Zenodo is performed. Python 3.9+ standard library only.
"""
from pathlib import Path
from datetime import datetime, timezone
import os, json, re, hashlib, zipfile, argparse, sys

EXCLUDE_DIRS = {'.git','.venv','venv','env','__pycache__','node_modules','.pytest_cache','.mypy_cache','.tox','.idea','.vscode','ZENODO_FIRST_RELEASE'}
EXCLUDE_FILES = {'.DS_Store','Thumbs.db'}
SENSITIVE = re.compile(r'(^\.env($|\.)|(^|[._-])(secret|secrets|password|token|credential|api[_-]?key|private[_-]?key)([._-]|$)|\.(pem|p12|pfx|key)$)',re.I)
TEXT_SUFFIXES = {'.py','.tla','.cfg','.md','.txt','.json','.jsonl','.csv','.yaml','.yml','.toml','.ini','.sh','.log','.tex','.bib'}
PATTERNS = [('home_paths',re.compile(rb'/Users/[^/\s]+|/home/[^/\s]+')),
            ('possible_credentials',re.compile(rb'(?i)(?:api[_-]?key|secret|password|authorization|bearer\s+)\s*[:=]\s*[^\s,;]{5,}')),
            ('email_addresses',re.compile(rb'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'))]

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default='.',help='AstroGuard project folder (default: current directory)')
    parser.add_argument('--max-file-gb',type=float,default=8,help='Skip individual files larger than this (default 8 GiB)')
    parser.add_argument('--no-archive',action='store_true',help='Only create inventory, do not zip')
    args=parser.parse_args()
    root=Path(args.root).expanduser().resolve()
    if not (root/'RESULTS_60K').exists():
        print('ERROR: No RESULTS_60K found. Run from AstroGuard project root or supply --root.',file=sys.stderr)
        return 2
    dest=root/'ZENODO_FIRST_RELEASE';dest.mkdir(exist_ok=True)
    entries=[]; skipped=[]; flagged=[]; files=[]
    for base,dirs,names in os.walk(root):
        dirs[:]=sorted(d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.'))
        for name in sorted(names):
            p=Path(base)/name
            rel=p.relative_to(root).as_posix()
            if name in EXCLUDE_FILES or SENSITIVE.search(name):
                skipped.append({'path':rel,'reason':'potentially sensitive filename or OS metadata'});continue
            if p.is_symlink():
                skipped.append({'path':rel,'reason':'symbolic link'});continue
            if not p.is_file():continue
            try:
                size=p.stat().st_size
                if size>args.max_file_gb*1024**3:
                    skipped.append({'path':rel,'reason':'over file-size limit','bytes':size});continue
                entry={'path':rel,'bytes':size,'sha256':sha(p)}
                entries.append(entry);files.append((p,rel))
                if p.suffix.lower() in TEXT_SUFFIXES and size<=5*1024*1024:
                    blob=p.read_bytes()
                    warnings=[label for label,rx in PATTERNS if rx.search(blob)]
                    if warnings:flagged.append({'path':rel,'review_for':warnings})
            except (OSError,PermissionError) as e:
                skipped.append({'path':rel,'reason':str(e)})
    total=sum(x['bytes'] for x in entries)
    required=['tla/AstroGuardActor.tla','tla/AstroGuardActor.cfg','run_step5b_instrumented_two_object.py','run_step5c_retry_reload.py','RESULTS_60K/FINAL_ALL_CHECKS/final_report.json']
    present={x['path'] for x in entries}
    metadata={'release':'AstroGuard research artifacts v0.1.0 (candidate, not published)',
       'created_utc':datetime.now(timezone.utc).isoformat(),'root_name':root.name,
       'counts':{'files':len(entries),'total_bytes':total,'skipped':len(skipped),'flagged_for_review':len(flagged)},
       'required_file_check':{k:k in present for k in required},'files':entries,'skipped_files':skipped,
       'review_flags':flagged,'scope':'all accessible project files excluding virtual environments, git metadata, hidden folders, symlinks and potentially secret-named files',
       'limitations':['Main TLC run disables deadlock checking; liveness and deadlock freedom not established.',
       'Production-to-TLA+ semantic trace conformance not established.',
       'No claim of independent verification of empirical results or permission to redistribute datasets.']}
    manifest=dest/'release_manifest.json';manifest.write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    review=dest/'REVIEW_BEFORE_PUBLICATION.txt'
    review.write_text('AstroGuard v0.1.0 candidate archive\n\n'
        f'Files: {len(entries)}; uncompressed bytes: {total}; flagged text files: {len(flagged)}; skipped: {len(skipped)}\n'
        'IMPORTANT: REVIEW THE MANIFEST AND FILE CONTENT BEFORE SHARING PUBLICLY.\n'
        'Do not publish passwords, private keys, identifiable data, restricted datasets, or third-party code without rights.\n'
        'Full TLC results, model and scripts are captured only if present on disk.\n'
        'Deadlock checking was disabled for the main model; production trace conformance is not verified.\n'
        'No DOI has been assigned. No Zenodo upload has been performed.\n',encoding='utf-8')
    print('Files:',len(entries),'Uncompressed GiB:',round(total/1024**3,3))
    print('Potentially sensitive files requiring review:',len(flagged),'Skipped:',len(skipped))
    print('Manifest:',manifest)
    if not args.no_archive:
        zpath=dest/'AstroGuard_v0.1.0_complete_experiments_candidate.zip'
        with zipfile.ZipFile(zpath,'w',allowZip64=True,compression=zipfile.ZIP_DEFLATED,compresslevel=4) as z:
            for p,rel in files:z.write(p,arcname='AstroGuard_v0.1.0/'+rel)
            z.write(manifest,arcname='AstroGuard_v0.1.0/release_manifest.json')
            z.write(review,arcname='AstroGuard_v0.1.0/REVIEW_BEFORE_PUBLICATION.txt')
        with zipfile.ZipFile(zpath) as z:
            corrupt=z.testzip()
            if corrupt:raise RuntimeError('ZIP integrity test failed: '+corrupt)
        print('Archive created and ZIP CRC integrity checked:',zpath)
    print('This packages existing files, including available logs; it cannot create missing execution data or upload files to Zenodo.')
    print('Review flagged files and check publishing rights before posting the ZIP publicly.')
    return 0
if __name__=='__main__':sys.exit(main())
