#!/usr/bin/env python3
"""Build a separate, sanitized Zenodo candidate from the existing release manifest.
Does NOT modify original project files, does NOT upload to Zenodo.
Run from the AstroGuard project root.
"""
from pathlib import Path
import json, re, hashlib, zipfile, sys, datetime

root = Path.cwd().resolve()
outdir = root / 'ZENODO_FIRST_RELEASE'
manifest_file = outdir / 'release_manifest.json'
if not manifest_file.is_file():
    sys.exit('Missing ZENODO_FIRST_RELEASE/release_manifest.json. Run from the project root.')
manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
entries = manifest.get('files', [])
flags = {x['path']: x.get('review_for', []) for x in manifest.get('review_flags', [])}
output = outdir / 'AstroGuard_v0.1.0_REVIEW_BEFORE_PUBLICATION.zip'
report_file = outdir / 'zenodo_privacy_and_release_review.json'
# Editable policy. Conservative omissions: transient caches/backups and earlier versions of our audit.
def omit(name):
    p = Path(name)
    return (any(x in ('_cache', '__pycache__', '.pytest_cache') for x in p.parts)
        or name.endswith('.before_filename_update')
        or bool(re.fullmatch(r'astroguard_(?:final_all_checks|submission_audit)(?:_v\d+)?\.py', p.name))
        or p.name in ('.DS_Store',))

text_ext = {'.txt','.md','.json','.jsonl','.log','.csv','.tsv','.yaml','.yml','.toml','.cfg','.tla','.py','.sh','.xml','.ini','.tex','.bib','.diff'}
# Replace local machine paths only. No change to numerical experiment results intended.
pattern = re.compile(r'/Users/[^/\s"\',;:]+|/home/[^/\s"\',;:]+')
issues=[]; written=[]; excluded=[]; changed=[]
if output.exists():
    sys.exit('Output already exists. Review or rename it before rerunning: '+str(output))
with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=4,allowZip64=True) as archive:
    for i, entry in enumerate(entries):
        rel = entry['path']; p = root/rel
        if omit(rel):
            excluded.append({'path':rel,'reason':'cache/obsolete audit/backup'}); continue
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root):
            issues.append({'path':rel,'issue':'missing/symlink/unsafe path'}); continue
        digest = hashlib.sha256()
        with p.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
        if digest.hexdigest()!=entry['sha256']:
            issues.append({'path':rel,'issue':'checksum changed since original inventory'}); continue
        arcname='AstroGuard_v0.1.0/'+rel
        if p.suffix.lower() in text_ext and (rel in flags or rel.endswith(('.log','.json','.jsonl'))):
            # Only attempt text handling for <= 50 MiB; larger text artifacts require manual review.
            if p.stat().st_size <= 50*1024*1024:
                raw=p.read_bytes()
                try: content=raw.decode('utf-8')
                except UnicodeDecodeError:
                    issues.append({'path':rel,'issue':'non-UTF8 flagged or log file, not modified'});
                else:
                    clean=pattern.sub('/PROJECT_ROOT',content)
                    if clean!=content:
                        archive.writestr(arcname, clean.encode('utf-8'))
                        changed.append({'path':rel,'replacement':'absolute home prefix -> /PROJECT_ROOT'})
                        written.append(rel)
                        continue
            elif rel in flags:
                issues.append({'path':rel,'issue':'flagged text file >50 MiB, manual review required'})
        archive.write(p,arcname)
        written.append(rel)
    guide='''AstroGuard v0.1.0 research artifacts\n\nThis is a research artifact deposit, NOT proof of production safety.\nThe main TLC check used CHECK_DEADLOCK FALSE; deadlock freedom/liveness is not established.\nThe Step 5B/5C Python programs are reference workflows, not an instrumented production pipeline.\nProduction-to-TLA+ conformance and four production safety properties remain unverified.\n\nCheck data licensing, privacy, all experimental claims, and remaining review flags before publishing.\nSee zenodo_privacy_and_release_review.json next to this ZIP.\n'''
    archive.writestr('AstroGuard_v0.1.0/RELEASE_LIMITATIONS_README.txt',guide)
review = {'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'output':str(output),'included_files':len(written),'changed_home_paths':changed,
    'excluded_files':excluded,'manual_review_issues':issues,
    'original_flags':flags,
    'checks_still_required':['Inspect log and data content for secrets, IDs and personal data',
        'Verify astronomical catalog/third-party dataset redistribution rights',
        'Review any flagged files not changed; path detection is not a comprehensive privacy scan',
        'Confirm complete manuscript evidence and limitations before publication',
        'Check Zenodo file size limits and choose a license appropriate for each component'],
    'publication_status':'NOT APPROVED: HUMAN REVIEW REQUIRED'}
report_file.write_text(json.dumps(review,indent=2),encoding='utf-8')
with zipfile.ZipFile(output) as z:
    bad=z.testzip()
print('Output:',output)
print('ZIP CRC:', 'PASS' if bad is None else f'FAIL: {bad}')
print('Files included:',len(written),'Paths sanitized:',len(changed),
      'Excluded:',len(excluded),'Manual issues:',len(issues))
print('Review:',report_file)
print('NOT PUBLISHED. Do not upload publicly before manual privacy and license review.')
