#!/usr/bin/env python3
"""Interpret recorded E05 measurements; preserve the base report and raw files."""
import collections, json, statistics
from pathlib import Path
from e05_common import ROOT, dump_new, sha
A=ROOT/'reports/e_stages/E05/E05_2026-11-18_01'

def main():
    analysis=json.loads((A/'analysis.json').read_text());resource=json.loads((ROOT/'reports/e_stages/E05/resource_estimate.json').read_text())
    rows=[json.loads(x) for x in (ROOT/'results/pilot_runs.jsonl').read_text().splitlines()]
    primary={k.split('/',1)[1]:s for k,s in analysis['precision']['contrasts'].items() if k.startswith('cold_equal_history/')}
    met=[m for m,s in primary.items() if s.get('estimable') and s['one_sided_bonferroni_upper']<=.90]
    update_counts=[]
    for r in rows:
        if r['phase']=='measured' and r['case_id']=='P05_ready_dominated_11' and r['method']=='C1' and r['status']=='completed':
            w=json.loads((ROOT/r['path']/'worker.json').read_text());counts=collections.Counter()
            for metric in w['engine_metrics'][1:]:counts.update(metric['counts'])
            update_counts.append(dict(counts))
    medcounts={k:statistics.median(x.get(k,0) for x in update_counts) for k in ['cells_visited','certified_cells','score_pairs','postings_visited','full_refills']}
    group={(x['case_id'],x['method']):x for x in analysis['summary']}
    c1=group['P05_ready_dominated_11','C1'];b1=group['P05_ready_dominated_11','B1_DELTA_MATRIX']
    contrast=next(x for x in analysis['contrasts'] if x['case_id']=='P05_ready_dominated_11' and x['baseline']=='B1_DELTA_MATRIX')
    scope_rows=[r for r in rows if r['status']=='completed' and r['sampled_tree_peak_bytes']>r['peak_tree_upper_bound_bytes']]
    timeouts=collections.Counter((r['case_id'],r['method'],r['status']) for r in rows if r['phase']=='measured' and r['status']!='completed')
    note={'version':'A-E05-interpretation-1.0','analysis_sha256':sha(A/'analysis.json'),
        'resource_estimate_sha256':sha(ROOT/'reports/e_stages/E05/resource_estimate.json'),
        'code_sha256':sha(Path(__file__)),'primary_time_contrasts_meeting_prospective_upper_le_0_90':met,
        'all_seven_primary_time_contrasts_meet_target':len(met)==7,'scientific_superiority_established':False,
        'P05_C1_update_counts_median':medcounts,'P05_C1_vs_B1':contrast,
        'measured_incomplete_groups':[{'case_id':k[0],'method':k[1],'status':k[2],'runs':v} for k,v in sorted(timeouts.items())],
        'memory_window_scope':{
            'operational_upper':'Worker self ru_maxrss captured immediately after T_total ends, plus maximum sequential embedding-child ru_maxrss: conservative upper bound for the measured operational window.',
            'sampled_process_peak':'Supervisor observes worker and descendants over their entire lifetimes, including excluded scientific report writing after T_total. It is a sampled lower observation of that longer process lifetime.',
            'joint_interval_claim':False,
            'samples_above_operational_upper_count':len(scope_rows),
            'samples_above_operational_upper_run_ids':[r['run_id'] for r in scope_rows],
            'implication':'The two fields do not form a rigorously bracketed interval for one identical time window. Use the operational upper bound for the declared worker lifecycle; do not claim exact whole-process peak or final B* ratio.'},
        'changed_fragment_definition':'changed_fragments counts full fragment-record changes including text_version, not only new vectors; actual dot work is score_pairs and embeddings are recorded separately.',
        'E06_started':False}
    dump_new(A/'interpretation.json',note)
    path=ROOT/'reports/e_stages/E05/pilot_report.md';base=path.read_text()
    with (A/'pilot_report_base_v1.md').open('x') as f:f.write(base)
    lines=['## Основные наблюдения пилота','',
        f"На равновзвешенном наборе двух cold-историй верхнюю одностороннюю границу R≤0.90 прошли **{len(met)} из 7** обязательных временных контрастов. Прошедшие: `{met}`. Это только временная часть малого пилота; научное превосходство в полной области E02 и все ресурсные ограничения не подтверждены.",'',
        f"В P05 C1 за историю сертифицировал медианно {medcounts['certified_cells']:g} из {medcounts['cells_visited']:g} клеток; дополнительные score pairs после построения — {medcounts['score_pairs']:g}, посещённые postings — {medcounts['postings_visited']:g}. Медиана полного ready-vector пути C1: {c1['T_total_median_seconds']:.6f} s; фиксированный простой контроль B1: {b1['T_total_median_seconds']:.6f} s. Парное геометрическое R C1/B1={contrast['ratio']:.3f}, центральный 95% интервал [{contrast['central_95_low']:.3f}; {contrast['central_95_high']:.3f}]. Это измерение окупаемости сертификата в объявленном благоприятном малом случае, не общий вывод для всех масштабов.",'',
        'Внутри каждой партии changed_fragments означает изменение полной записи фрагмента, в том числе text_version; показатель не приравнивается к числу новых векторов. Фактические новые скалярные произведения и обращения к embedding runtime приведены отдельно.','',
        'Незавершённые измерительные группы:']
    for (case,method,status),count in sorted(timeouts.items()):lines.append(f'- {case} / {method}: {status}, {count} запусков; полное время и speedup отсутствуют.')
    lines += ['','Уточнение окон памяти: верхняя оценка self+child относится к измеренному операционному пути до конца T_total. Supervisor семплирует всю жизнь процесса, включая последующую запись исследовательского JSON-отчёта. Эти два числа не объявляются строгим интервалом одного и того же временного окна. Для критерия операционного пути применима консервативная верхняя оценка; точный peak всей жизни процесса и отношение к окончательному B* не установлены.',
        f"В журналах {len(scope_rows)} завершённых запусков имеют sampled whole-process значение выше operational upper; это различие окон и/или внешнего RSS-интерфейса сохранено в interpretation.json. Оно не используется для сертификации точного пика или для замены верхней оценки меньшим семплированным числом.",'',
        'Осторожный ресурсный расчёт ниже не означает выполнения больших запусков. Время build масштабировано линейно из измеренного B0 случая; embedding-диапазон — линейный расчёт по наблюдавшимся initial-call затратам на текст (включая стартап, без гарантии линейности при увеличении размера). Python модель учитывает неразделяемые float-объекты и один tuple на вектор, но не все дополнительные структуры.','',
        '| Фрагменты | Запросы | Packed vectors+scores, GiB | Python vectors, GiB (аллокации, не RSS) | Линейный B0 build, s | Линейные initial embeddings, h |',
        '|---:|---:|---:|---:|---:|---:|']
    for f in resource['forecasts']:
        if f['queries'] not in [32,679]:continue
        t=f['linear_B0_build_seconds_from_239_fragment_probe'];band=f['initial_embeddings_linear_seconds_observed_rate_band']
        lines.append(f"| {f['fragments']} | {f['queries']} | {f['packed_vectors_plus_scores_bytes_only']/1024**3:.3f} | {f['unshared_Python_float_plus_one_tuple_allocation_model_bytes']/1024**3:.3f} | {t:.1f} | {band[0]/3600:.2f}–{band[1]/3600:.2f} |")
    lines += ['', 'При 10^6 неразделяемых векторов одна Python-модель аллокаций уже превышает бюджет 16 GiB; это сильное ограничение текущего представления, хотя аллокации и simultaneous RSS не тождественны. Для 10^5 также нет сертификата выполнимости: потребуются подходящие данные и прямые масштабные проверки. Фактически использованный максимум и все допущения находятся в resource_estimate.json.', '']
    assert '## Научный исход и дальнейший шаг' in base
    path.write_text(base.replace('## Научный исход и дальнейший шаг','\n'.join(lines)+'\n## Научный исход и дальнейший шаг',1))
    print(json.dumps({'primary_time_targets_met':len(met),'P05_C1_vs_B1':contrast['ratio'],
        'RSS_window_differences':len(scope_rows),'E06_started':False}))

if __name__=='__main__':main()
