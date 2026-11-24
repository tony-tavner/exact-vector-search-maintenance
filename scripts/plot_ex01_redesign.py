"""Standalone scientific plot; descriptive block ranges, not confidence intervals."""
import json
from pathlib import Path
from e05_common import ROOT

def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter
    p=ROOT/'reports/exploration/EX01_2026-11-18_01'
    a=json.loads((p/'analysis.json').read_text())
    fig,axs=plt.subplots(2,2,figsize=(12,8),sharex=True,sharey=True)
    families=['23','27','51','55']
    colors={1:'#2365a0',4:'#af5226'}
    xmax=max([c.get('paired_ratio_max',1) for c in a['cases']]+[1])*1.4
    for ax,reg in zip(axs.flat,a['regimes']):
        g=reg['group_size'];h=reg['horizon']
        cs={c['family']:c for c in a['cases'] if c['group_size']==g and c['horizon']==h}
        for y,family in enumerate(families):
            c=cs[family]
            if c['complete_correct']:
                x=c['ratio'];lo=c['paired_ratio_min'];hi=c['paired_ratio_max']
                ax.errorbar([x],[y],xerr=[[x-lo],[hi-x]],fmt='o',capsize=4,color=colors[g],markersize=7)
                ax.annotate(f'{x:.2f}×',(x,y),xytext=(6,8),textcoords='offset points',fontsize=9)
            else:
                ax.text(1.03,y,'Incomplete comparison',fontsize=10,color='#a02020')
        ax.axvline(.9,color='#2c7c42',ls='--',lw=1.3)
        ax.axvline(1,color='#666666',ls=':',lw=1.1)
        ax.set_xscale('log');ax.set_xlim(.7,xmax);ax.set_ylim(-.55,3.7)
        ax.set_xticks([1,2,5,10,20] if xmax>20 else [1,2,5,10])
        ax.xaxis.set_major_formatter(ScalarFormatter());ax.minorticks_off()
        ax.grid(axis='x',alpha=.15)
        ax.set_yticks(range(len(families)),['SOC '+f for f in families])
        ax.set_title(f'{g} occupation' + ('s' if g!=1 else '') + f' / document · {h} updates',loc='left',fontsize=11)
        for spine in ['top','right']:ax.spines[spine].set_visible(False)
    for ax in axs[-1]:ax.set_xlabel('C1 / B3 elapsed-time ratio (log scale; lower is better)')
    fig.suptitle('Changed document grouping and update horizon: local development screen',fontsize=14,x=.07,ha='left')
    fig.text(.07,.932,'Ready vectors only · 4 development families · fixed workloads and order · no physical embedding costs',fontsize=10,color='#444444')
    fig.text(.07,.035,'Dots: geometric mean of 3 paired blocks. Bars: observed min–max, not confidence intervals.\nGreen line: ratio 0.90. Grey line: equal time. These runs do not establish full-path or independent superiority.',fontsize=9,color='#444444')
    fig.subplots_adjust(left=.09,right=.97,top=.88,bottom=.15,hspace=.3,wspace=.12)
    for ext in ['png','svg']:fig.savefig(p/f'comparison.{ext}',dpi=170)
    print(p/'comparison.png')

if __name__=='__main__':main()
