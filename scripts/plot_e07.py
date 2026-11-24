#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Static shareable E07 diagnostic figure; only after timing has ended."""
import json,math,os,statistics
os.environ['MPLCONFIGDIR']=os.path.join(os.path.dirname(__file__),'../results/iterations/E07_2026-11-18_01/plot_cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from e07_common import ROOT
OUT=ROOT/'results/iterations/E07_2026-11-18_01'
def main():
    h=json.loads((OUT/'headroom_run_analysis.json').read_text());i=json.loads((OUT/'I01_analysis.json').read_text())
    families=sorted({d['case_id'] for d in h});ys=[]
    for c in families:
        fs=[d['conditional_nonengine_floor'] for d in h if d['case_id']==c and not d['warmup']]
        ys.append(100*(1-math.exp(statistics.mean(math.log(x) for x in fs))))
    fig,axes=plt.subplots(1,2,figsize=(12.8,5.4),layout='constrained');a,b=axes
    a.barh([c.replace('T100_SOC_','') for c in families],ys,color='#247c85');a.axvline(10,color='#a72f36',ls='--',lw=1.5,label='10% target')
    a.set(xlabel='Conditional maximum saving (%)',ylabel='Development SOC family',title='100 batches: engine-only headroom vs B3');a.legend(loc='lower right');a.grid(axis='x',alpha=.2);a.set_axisbelow(True)
    wanted=['C1_ORIGINAL','C1_NO_CERT_I01','B1_DELTA_MATRIX_I01','B2_RESERVE_EXACT_I01','B2_ADAPTIVE_I01','B3_ALL_SCORES_I01','B6_HYBRID_EXACT_I01']
    contrasts=[next(c for c in i['equal_case_aggregate'] if c['baseline']==x) for x in wanted]
    for j,c in enumerate(contrasts):
        assert c['estimable']
        b.errorbar(c['ratio'],j,xerr=[[c['ratio']-c['central_95_low']],[c['central_95_high']-c['ratio']]],fmt='o',color='#247c85',capsize=3)
    b.set_yticks(range(len(wanted)),['Original C1','C1 without certificate','B1 delta matrix','B2 exact reserve','B2 adaptive reserve','B3 all scores','B6 hybrid']);b.invert_yaxis()
    b.axvline(1,color='#555555',lw=1);b.axvline(.9,color='#a72f36',ls='--',lw=1.5);b.grid(axis='x',alpha=.2)
    b.set(xlabel='C1 I01 / baseline full-path time',title='Families 27 and 25: 20 paired blocks')
    fig.suptitle('E07 development diagnostics — no confirmed scientific candidate',fontsize=13)
    fig.text(.50,-.035,'Left: fixed other B3 costs, 3 blocks; conditional ceiling only. Right: central 95% timing-block bootstrap; lower is better.\nShared workstation; fixed synthetic histories from real source texts. No held-out validation or population inference.',ha='center',fontsize=8)
    for ext in ['png','svg']:
        p=OUT/('E07_diagnostics.'+ext);assert not p.exists();fig.savefig(p,dpi=170,bbox_inches='tight')
    plt.close(fig)
    print('Saved PNG and SVG diagnostic figure.')
if __name__=='__main__':main()
