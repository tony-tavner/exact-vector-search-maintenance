"""Create hand-specified toy snapshots for E03 reasoning; no method implementation."""
import json
import math
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests/fixtures/method_cases'


def frag(score, fid='f', version='v1'):
    return {'fragment_id': fid, 'text_version': version,
            'vector': [score, math.sqrt(1-score*score)]}


def doc(did, score=None, *, fragments=None, enabled=True, equipment='pump'):
    return {'doc_id': did, 'metadata': {'enabled': enabled, 'equipment': equipment,
            'valid_from': '2026-01-01', 'valid_to': '2027-01-01'},
            'fragments': fragments if fragments is not None else [frag(score)]}


def query(k=1, equipment='pump', version='qv1', config='toy-e03-canonical-v1'):
    return {'query_id': 'q', 'query_version': version, 'config_version': config,
            'vector': [1.0, 0.0], 'query_time': '2026-11-18', 'k': k,
            'filter': {'equipment': equipment}}


def hit(did, fid='f', version='v1'):
    return [did, fid, version]


def snap(documents, expected, q=None):
    return {'documents': documents, 'expected_hits': expected, 'query': q or query()}


def main():
    cases = []

    def add(cid, cap, trace, snapshots, bad_rule=None):
        for i, s in enumerate(snapshots):
            s['corpus_version'] = cid + '-c' + str(i)
        cases.append({'id': cid, 'reserve_capacity': cap, 'manual_trace': trace,
                      'counterexample_bad_rule': bad_rule, 'snapshots': snapshots})

    a, b, c, x = doc('A', 1), doc('B', .5), doc('C', .25), doc('X', .75)
    add('reserve_frontier_two_batches', 2,
        'R=[A,B], b=B(.5); insert X(.75) -> R=[A,X]; delete A -> R=[X]. '
        'Top-k-only routing misses X and incorrectly returns B after deletion.',
        [snap([a,b,c],[hit('A')]), snap([a,b,c,x],[hit('A')]),
         snap([b,c,x],[hit('X')])], 'Use kth output score instead of last reserve score')

    a, b, x = doc('A', .875), doc('B', .625), doc('X', .75)
    add('stale_frontier_requires_fallback', 1,
        'R=[A]; delete A and insert X -> no key<=old b; C empty, full search returns X.',
        [snap([a,b],[hit('A')]), snap([b,x],[hit('X')])],
        'Retain old threshold as completeness certificate after losing its witnesses')

    a,b,c,z = doc('A',.875),doc('B',.5),doc('C',.5),doc('Z',.5)
    add('lexical_reserve_boundary', 2,
        'R=[A,B]; delete B, insert Z tied on score but Z>B: C=[A]. '
        'Delete A -> fallback returns C. Scalar-only admission would keep Z and return it wrongly.',
        [snap([a,b,c],[hit('A')]),snap([a,c,z],[hit('A')]),snap([c,z],[hit('C')])],
        'Use scalar score>=tau without full lexical boundary for reserve admission')

    a=doc('A',fragments=[frag(1,'winner'),frag(.5,'other')]); b=doc('B',.75)
    add('delete_winning_fragment', 2,
        'Remove whole A record; recompute A max=.5 from remaining fragment; B now wins.',
        [snap([a,b],[hit('A','winner')]),
         snap([doc('A',fragments=[frag(.5,'other')]),b],[hit('B')])])

    a=doc('A',.5); x=doc('X',1,enabled=False)
    add('metadata_opens_applicability', 2,
        'X has no new vector but enabled change puts X in D; compute current max and admit X.',
        [snap([a,x],[hit('A')]),snap([a,doc('X',1)],[hit('X')])])

    add('text_version_only', 1,
        'Same scores do not license stale text_version; A is touched and its complete record replaced.',
        [snap([doc('A',1)],[hit('A')]),
         snap([doc('A',fragments=[frag(1,version='v2')])],[hit('A',version='v2')])])

    add('fragment_tie_changes_representative', 1,
        'New tied fragment a precedes z in UTF8 order; document score unchanged, winner changes.',
        [snap([doc('A',fragments=[frag(1,'z')])],[hit('A','z')]),
         snap([doc('A',fragments=[frag(1,'z'),frag(1,'a')])],[hit('A','a')])])

    add('mixed_atomic_batch', 2,
        'A changes .75->.25 while X(1) is inserted; old b=B(.5), final candidates B,X; publish X.',
        [snap([doc('A',.75),doc('B',.5)],[hit('A')]),
         snap([doc('A',fragments=[frag(.25,version='v2')]),doc('B',.5),doc('X',1)],
              [hit('X')])])

    add('empty_and_short_reserve', 3,
        'k=3, eligible count 1: Small includes q; deletion leaves empty, full search confirms empty.',
        [snap([doc('A',.5)],[hit('A')],query(k=3)),snap([],[],query(k=3))])

    docs=[doc('A',1),doc('B',.75,equipment='valve')]
    add('query_filter_change', 1,
        'Same vector, new filter/query_version: full initialize; old reserve cannot certify new scope.',
        [snap(docs,[hit('A')]),snap(deepcopy(docs),[hit('B')],query(equipment='valve',version='qv2'))])

    hi=math.nextafter(.5, math.inf); higher=math.nextafter(hi, math.inf)
    add('binary64_near_tie', 2,
        'B is one binary64 step above A; X is one step above B. No epsilon treats them as a tie.',
        [snap([doc('A',.5),doc('B',hi)],[hit('B')]),
         snap([doc('A',.5),doc('B',hi),doc('X',higher)],[hit('X')])])

    add('negative_scores', 2,
        'All scores negative: initial threshold -.5, new X=-.125 qualifies; threshold 0 would miss it.',
        [snap([doc('A',-.25),doc('B',-.5)],[hit('A')]),
         snap([doc('A',-.25),doc('B',-.5),doc('X',-.125)],[hit('X')])],
        'Initialize routing threshold to zero')

    docs=[doc('A',1),doc('B',.75,equipment='valve')]
    qa=query(); qa['query_id']='qa'; qb=query(equipment='valve'); qb['query_id']='qb'
    add('identical_vectors_different_filters', 1,
        'Two simultaneous query fixtures share all vector bits but retain distinct filters/hits; '
        'these snapshots are query instances on the same corpus, not a query update trace.',
        [snap(docs,[hit('A')],qa),snap(deepcopy(docs),[hit('B')],qb)])
    cases[-1]['snapshots'][1]['corpus_version']=cases[-1]['snapshots'][0]['corpus_version']

    add('ordered_batch_final_version', 1,
        'Ordered valid replacements v1->v2->v3; final score equals initial but publish only v3. '
        'Intermediate states are not exposed. Event validation is a separate implementation obligation.',
        [snap([doc('A',1)],[hit('A')]),
         snap([doc('A',fragments=[frag(1,version='v3')])],[hit('A',version='v3')])])

    add('configuration_rebuild', 1,
        'Config change requires full initialization; final vectors here are explicitly supplied toy inputs, '
        'not an embedding generation experiment.',
        [snap([doc('A',1),doc('B',.5)],[hit('A')]),
         snap([doc('A',.5),doc('B',1)],[hit('B')],query(version='qv2',config='toy-e03-canonical-v2'))])

    a=doc('A',.875); b=doc('B',fragments=[frag(.75,'win'),frag(.25,'rest')]); c=doc('C',.5)
    b_after=doc('B',fragments=[frag(.25,'rest')])
    add('delete_reserve_winning_fragment', 2,
        'R=[A,B]. Losing B.win drops B below frontier: R=[A]. Then deletion A requires full search '
        'and returns C; an unrefreshed reserve would incorrectly return B.',
        [snap([a,b,c],[hit('A')]),snap([a,b_after,c],[hit('A')]),snap([b_after,c],[hit('C')])])

    obligations=[
      {'id':'version_alias', 'input':'Same (doc_id,fragment_id,text_version), different source text',
       'expected':'Reject entire batch; old root remains', 'verification':'manual specification only'},
      {'id':'partial_failure', 'input':'OOM or malformed vector after some staging updates',
       'expected':'Discard staging; do not publish new corpus_version', 'verification':'manual specification only'},
      {'id':'external_applicability_change', 'input':'External access/role map changes with incomplete D',
       'expected':'Complete D or rebuild; incremental acceptance forbidden', 'verification':'manual specification only'}]
    obj={'schema_version':1,'method_version':'A-E03-2.0-composition-audit',
         'scope':'Hand-authored full-snapshot answers and reasoning traces; no incremental implementation or performance data.',
         'cases':cases,'manual_validation_obligations':obligations}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'cases_v1.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'cases':len(cases),'snapshots':sum(len(c['snapshots']) for c in cases),
                      'manual_validation_obligations':len(obligations)}))


if __name__=='__main__':
    main()
