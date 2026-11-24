#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Create a separate I01 package; leave E04 source/results byte-identical."""
import difflib,json,shutil
from pathlib import Path
from e05_common import ROOT,sha,dump_new
A=ROOT/'reports/e_stages/E07/E07_2026-11-18_01'
OUT=ROOT/'results/iterations/E07_2026-11-18_01'

def main():
    assert (A/'execution_headroom_complete.json').exists()
    dest=ROOT/'src/pvldb_a_e07_i01';assert not dest.exists()
    hypothesis={'iteration_id':'I01','parent':'A-E04-0.1','diagnosis':['E06:D03','E06:H03'],'version':'A-E07-I01-1.0',
      'before_code_change':True,'change':'Skip unused max_norm2 in C1 family; cache exact per-query norms once for norm ordering and block summary in B4/B5.',
      'expected_correctness':'Same partition membership/boxes, scores, certificates and outputs; only unused C1 max_norm2 becomes None. B4/B5 maximum and ordering unchanged.',
      'expected_performance':'Lower partition build cost; no expected change in updates/pairs/refills; no promise of 10% full-path saving.',
      'possible_regressions':['accidental consumer of None max_norm2','query sorting/tie behavior changed','registry rebuild path not using correct need_norm','common optimization withheld from B4/B5'],
      'acceptance':'Full inherited E04 tests, exact structural audit on all development registries, equal output/counters and blocks; matched current-run comparisons. Engineering acceptance is distinct from E02 scientific candidate selection.',
      'parent_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src/pvldb_a').glob('*') if p.is_file()},'E08_started':False}
    dump_new(OUT/'I01'/'hypothesis.json',hypothesis)
    dest.mkdir()
    for f in (ROOT/'src/pvldb_a').glob('*.py'):shutil.copy2(f,dest/f.name)
    blocks=dest/'blocks.py';s=blocks.read_text()
    s=s.replace("def build_blocks(queries,limit=64,policy='kd'):","def build_blocks(queries,limit=64,policy='kd',need_norm=True):")
    s=s.replace("    if policy=='norm':\n        ids.sort(key=lambda x:(-norm2(queries[x].v),x.encode('utf8')))",
                "    norms={i:norm2(queries[i].v) for i in ids} if need_norm or policy=='norm' else {}\n    if policy=='norm':\n        ids.sort(key=lambda x:(-norms[x],x.encode('utf8')))")
    s=s.replace("max(norm2(queries[i].v) for i in ids)","max(norms[i] for i in ids) if need_norm else None")
    blocks.write_text(s)
    engine=dest/'engine.py';s=engine.read_text();old='blocks,membership=build_blocks(qs,self.leaf_limit,policy)'
    assert s.count(old)==1
    s=s.replace(old,"blocks,membership=build_blocks(qs,self.leaf_limit,policy,need_norm=self.method in ('B4_SIMPFER_EXACT','B5_SIMPFERPP_EXACT'))")
    engine.write_text(s)
    diff=[]
    for name in ['blocks.py','engine.py']:
        diff+=list(difflib.unified_diff((ROOT/'src/pvldb_a'/name).read_text().splitlines(True),(dest/name).read_text().splitlines(True),fromfile='src/pvldb_a/'+name,tofile=str((dest/name).relative_to(ROOT))))
    with (OUT/'I01'/'implementation.diff').open('x') as f:f.writelines(diff)
    test=ROOT/'tests/e04/check_implementation.py';target=ROOT/'tests/e07_i01/check_implementation.py';target.parent.mkdir(parents=True,exist_ok=False)
    adapted=test.read_text().replace('pvldb_a','pvldb_a_e07_i01').replace("'implementation_version':'A-E04-0.1'","'implementation_version':'A-E07-I01-1.0'")
    adapted=adapted.replace('E04 differential correctness and infrastructure acceptance, not performance comparison.','Inherited full E04 suite against separate E07 I01 namespace; not a performance comparison.')
    with target.open('x') as f:f.write('# -*- coding: utf-8 -*-\n'+adapted)
    dump_new(OUT/'I01'/'implementation_manifest.json',{'version':'A-E07-I01-1.0','package':'pvldb_a_e07_i01',
        'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in dest.glob('*.py')},'parent_test_sha256':sha(test),'adapted_test_sha256':sha(target),
        'test_adaptation':'Only import namespace/source-hash namespace, version/scope annotation, explicit UTF8 cookie. Test logic unchanged.',
        'unchanged_numeric_sha256':sha(dest/'numeric.py'),'E08_started':False})
    print(json.dumps({'I01_created':True,'changed_source_files':['blocks.py','engine.py'],'numeric_formula_changed':False}))

if __name__=='__main__':main()
