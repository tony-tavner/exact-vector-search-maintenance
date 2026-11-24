"""Write explicit synthetic contract examples. Expected answers are handwritten."""
import copy
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def doc(identifier,values,**metadata):
    m={'role':'technician','equipment':'pump','language':'ru','access_scope':'public',
       'enabled':True,'valid_from':'2026-01-01','valid_to':'2027-01-01'}
    m.update(metadata)
    return {'doc_id':identifier,'metadata':m,'fragments':[
        {'fragment_id':fid,'text_version':'v1','text':'Искусственный контрольный фрагмент '+fid,
         'vector':[score,math.sqrt(1-score*score)]} for fid,score in values]}

def query(k=3,**changes):
    q={'query_id':'Q1','query_version':'v1','config_version':'toy-2d-v1',
       'query_time':'2026-11-17','k':k,'vector':[1.,0.],
       'filter':{'role':'technician','equipment':'pump','language':'ru','access_scope':'public'}}
    q.update(changes);return q

def main():
    target=ROOT/'tests/fixtures/e01_contract_v1.json'
    if target.exists():raise ValueError('Fixtures exist; create a new version.')
    base=[doc('D1',[('f11',.91),('f12',.80)]),doc('D2',[('f21',.86)]),
          doc('D3',[('f31',.82)]),doc('D4',[('f41',.98)],equipment='turbine')]
    old=[['D1','f11','v1'],['D2','f21','v1'],['D3','f31','v1']]
    cases=[]
    def add(name,before,after,expected_before,expected_after,q=None,events=None):
        cases.append({'id':name,'provenance':'synthetic hand-specified; no source requirement or model prediction',
                      'query':q or query(),'before':{'corpus_version':'C0','documents':before},
                      'after':{'corpus_version':'C1','documents':after},'event_description':events or name,
                      'expected_before':expected_before,'expected_after':expected_after})
    add('new_leader_old_sources_unchanged',base,copy.deepcopy(base)+[doc('D5',[('f51',.94)],valid_from='2026-11-10')],old,[['D5','f51','v1'],['D1','f11','v1'],['D2','f21','v1']],events='Adapted from completed passport §6; insert D5 only. This is not a new scientific result.')
    after=copy.deepcopy(base);after[0]['fragments'].pop(0)
    add('delete_winning_fragment',base,after,old,[['D2','f21','v1'],['D3','f31','v1'],['D1','f12','v1']])
    after=copy.deepcopy(base);after[3]['metadata']['equipment']='pump'
    add('applicability_change',base,after,old,[['D4','f41','v1'],['D1','f11','v1'],['D2','f21','v1']])
    tie=[doc('я',[('z',.90)]),doc('Z',[('f02',.90),('f01',.90)]),doc('A',[('a',.90)])]
    expected=[['A','a','v1'],['Z','f01','v1'],['я','z','v1']]
    add('utf8_doc_and_fragment_ties',tie,copy.deepcopy(tie),expected,expected)
    empty=[doc('E',[]),doc('F',[('f',.99)],enabled=False)]
    add('empty_eligible_result',empty,copy.deepcopy(empty),[],[])
    grouped=[doc('A',[('a1',.99),('a2',.98)]),doc('B',[('b1',.80)])]
    expected=[['A','a1','v1'],['B','b1','v1']]
    add('one_hit_per_document',grouped,copy.deepcopy(grouped),expected,expected)
    after=copy.deepcopy(base);after[0]['fragments'][0]['text_version']='v2'
    add('text_version_is_part_of_answer',base,after,old,[['D1','f11','v2'],['D2','f21','v1'],['D3','f31','v1']])
    boundary=[doc('ends_today',[('f1',.99)],valid_to='2026-11-17'),doc('starts_today',[('f2',.80)],valid_from='2026-11-17')]
    add('half_open_time_interval',boundary,copy.deepcopy(boundary),[['starts_today','f2','v1']],[['starts_today','f2','v1']])
    after=copy.deepcopy(base);del after[0]['metadata']['equipment']
    add('missing_required_metadata_excluded',base,after,old,[['D2','f21','v1'],['D3','f31','v1']])
    expected=old
    add('k_exceeds_eligible_count',base,copy.deepcopy(base),expected,expected,q=query(20))
    after=copy.deepcopy(base);after=[x for x in after if x['doc_id']!='D2'];after[0]['metadata']['enabled']=False
    after.append(doc('D5',[('f51',.94)]))
    add('mixed_atomic_batch',base,after,old,[['D5','f51','v1'],['D3','f31','v1']],events='Delete D2, disable D1, insert D5; evaluate final C1 atomically.')
    after=copy.deepcopy(base);after[1]['fragments'][0]['vector']=[.99,math.sqrt(1-.99**2)];after[1]['fragments'][0]['text_version']='v2'
    add('replacement_changes_rank_and_version',base,after,old,[['D2','f21','v2'],['D1','f11','v1'],['D3','f31','v1']])
    invalid=[]
    for name,vec in [('zero',[0.,0.]),('non_unit',[2.,0.]),('wrong_dimension',[1.]),('non_finite',['NaN',0.])]:
        d=doc('bad',[('bad',.5)]);d['fragments'][0]['vector']=vec
        invalid.append({'id':name,'query':query(),'documents':[d],'expected_error':'invalid_vector'})
    obj={'schema_version':1,'config_version':'toy-2d-v1','purpose':'E01 contract checks only; not an embedding model, empirical corpus, or proposed-method test',
         'gold_construction':'Expected ordered triples explicitly written independently of verifier.',
         'cases':cases,'invalid_cases':invalid}
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'fixture_cases':len(cases),'invalid_input_cases':len(invalid)}))

if __name__=='__main__':main()
