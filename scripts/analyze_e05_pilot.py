#!/usr/bin/env python3
"""Summarize frozen E05 runs without changing methods or starting E06."""
import collections, json, math, os, statistics, sys
from pathlib import Path
os.environ.update({k:'1' for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS']})
import numpy as np
from e05_common import ROOT, dump_new, sha
from e05_statistics import interval
ATTEMPT = ROOT/'reports/e_stages/E05/E05_2026-11-18_01'
BASE = ROOT/'results/pilot/E05_2026-11-18_01'

def med(values): return float(statistics.median(values)) if values else None
def pct(values, p): return float(np.quantile(values,p)) if values else None
def fmt(x): return 'NA' if x is None else ('%.4f'%x)

def main():
    done=json.loads((ATTEMPT/'execution_complete.json').read_text());assert done['status']=='completed'
    protocol=json.loads((ROOT/'protocol/pilot_v1.json').read_text())
    records=[json.loads(x) for x in (ROOT/'results/pilot_runs.jsonl').read_text().splitlines()]
    measured=[r for r in records if r['phase']=='measured'];warm=[r for r in records if r['phase']=='warmup']
    precision=json.loads((ATTEMPT/'precision_final.json').read_text());lookup={}; groups=collections.defaultdict(list)
    details=[]; backgrounds=[]; embeddings=[]; cumulative={}; traces={}
    for r in measured:
        lookup[r['block'],r['case_id'],r['method']]=r;groups[r['case_id'],r['method']].append(r)
        out=ROOT/r['path'];provenance=json.loads((out/'provenance.json').read_text());backgrounds.append(provenance['background_before'])
        assert sha(out/'supervisor.json')==r['supervisor_sha256']
        if r['status']!='completed':continue
        assert r['correct'] and sha(out/'worker.json')==r['worker_sha256'] and sha(out/'validation.json')==r['validation_sha256']
        w=json.loads((out/'worker.json').read_text());v=json.loads((out/'validation.json').read_text())
        assert sha(ROOT/v['expected_path'])==v['expected_sha256']
        if r['case_id'] not in traces:traces[r['case_id']]=json.loads((ROOT/v['expected_path']).read_text())['trace']
        spans=w['metrics']['spans'];component=collections.defaultdict(float)
        for s in spans:
            if s['name']!='lifecycle_total':component[s['name']]+=(s['end_ns']-s['start_ns'])/1e9
        counts=collections.Counter();engine_times=collections.defaultdict(float)
        for m in w['engine_metrics']:
            counts.update(m['counts'])
            for s in m['spans']:engine_times[s['name']]+=(s['end_ns']-s['start_ns'])/1e9
        preparations=[s for s in spans if s['name']=='delta_preparation'];maintenance=[s for s in spans if s['name']=='maintenance']
        reads=[s for s in spans if s['name']=='scheduled_reads']
        freshness=[(m['end_ns']-p['start_ns'])/1e9 for p,m in zip(preparations,maintenance)]
        read_latency=[(s['end_ns']-s['start_ns'])/1e9 for s in reads]
        elapsed=[(s['end_ns']-w['timer_start_ns'])/1e9 for s in reads]
        elapsed[-1]=w['T_total_ns']/1e9;cumulative[r['block'],r['case_id'],r['method']]=elapsed
        detail={'run_id':r['run_id'],'case_id':r['case_id'],'method':r['method'],'block':r['block'],
                'T_total_seconds':w['T_total_ns']/1e9,'components_seconds':dict(component),'nested_engine_seconds':dict(engine_times),
                'counts':dict(counts),'freshness_seconds':freshness,'bulk_read_seconds':read_latency,
                'runtime_setup_seconds':w['runtime_import_and_thread_setup_ns']/1e9,
                'embedding_wall_seconds':sum(c['wall_ns'] for c in w['embedding_calls'])/1e9,
                'embedding_texts':sum(c['texts'] for c in w['embedding_calls']),
                'tree_peak_lower_bytes':r['sampled_tree_peak_bytes'],'tree_peak_upper_bytes':r['peak_tree_upper_bound_bytes']}
        details.append(detail)
        if w['embedding_calls']:embeddings.append({'case_id':r['case_id'],'run_id':r['run_id'],'initial_call':w['embedding_calls'][0]})
    dgroups=collections.defaultdict(list)
    for d in details:dgroups[d['case_id'],d['method']].append(d)
    summary=[]; contrasts=[]; noise=[]; breakeven=[]
    for case in protocol['cases']:
        blocks=case['timing_blocks'] if case['role']=='diagnostic_memory_limit' else done['final_blocks']
        for mi,method in enumerate(case['methods']):
            rs=groups[case['id'],method]; ds=dgroups[case['id'],method]; values=[d['T_total_seconds'] for d in ds]
            counts_keys=set(k for d in ds for k in d['counts']);component_keys=set(k for d in ds for k in d['components_seconds'])
            engine_keys=set(k for d in ds for k in d['nested_engine_seconds'])
            fresh=[x for d in ds for x in d['freshness_seconds']];reads=[x for d in ds for x in d['bulk_read_seconds']]
            summary.append({'case_id':case['id'],'method':method,'planned_blocks':blocks,'recorded':len(rs),
                'status_counts':dict(collections.Counter(r['status'] for r in rs)),'complete':len(ds)==blocks,
                'T_total_median_seconds':med(values),'T_total_geomean_seconds':math.exp(statistics.mean(math.log(x) for x in values)) if values else None,
                'T_total_min_seconds':min(values) if values else None,'T_total_max_seconds':max(values) if values else None,
                'median_components_seconds':{k:med([d['components_seconds'].get(k,0) for d in ds]) for k in sorted(component_keys)},
                'median_nested_engine_seconds':{k:med([d['nested_engine_seconds'].get(k,0) for d in ds]) for k in sorted(engine_keys)},
                'median_counts':{k:med([d['counts'].get(k,0) for d in ds]) for k in sorted(counts_keys)},
                'peak_tree_lower_max_bytes':max((d['tree_peak_lower_bytes'] for d in ds),default=None),
                'peak_tree_upper_max_bytes':max((d['tree_peak_upper_bytes'] for d in ds),default=None),
                'freshness':{'unit':'raw batch preparation start to snapshot-ready publication; inference included in cold',
                    'samples':len(fresh),'p50_seconds':pct(fresh,.5),'p95_seconds':pct(fresh,.95),'p99_seconds':pct(fresh,.99),'max_seconds':max(fresh) if fresh else None,
                    'p99_tail_assurance':False},
                'reads':{'unit':'bulk answers() for the whole registry, not individual query latency',
                    'samples':len(reads),'p50_seconds':pct(reads,.5),'p95_seconds':pct(reads,.95),'p99_seconds':pct(reads,.99),'max_seconds':max(reads) if reads else None,
                    'single_query_tail_criterion_verified':False},
                'partial_run_warning':None if len(ds)==blocks else 'Successful-run times are censored descriptive values; no complete-case speed claim.'})
            if len(ds)==blocks and blocks>=20:
                ordered=sorted(ds,key=lambda d:d['block']);x=np.log([d['T_total_seconds'] for d in ordered]);n=len(x)//3
                sd=float(np.std(x,ddof=1));lag=float(np.corrcoef(x[:-1],x[1:])[0,1]) if sd>0 else None
                if lag is not None and not math.isfinite(lag): lag=None
                noise.append({'case_id':case['id'],'method':method,'blocks':blocks,
                    'relative_log_sd':sd,'late_over_early_geomean':float(np.exp(x[-n:].mean()-x[:n].mean())),
                    'lag1_log_correlation':lag,'stationarity_not_proved':True})
            if method=='C1' or case['role']=='diagnostic_memory_limit':continue
            pair=[(lookup.get((b,case['id'],'C1')),lookup.get((b,case['id'],method))) for b in range(1,blocks+1)]
            if all(a and b and a['status']=='completed' and b['status']=='completed' for a,b in pair):
                stat=interval([math.log(a['T_total_ns']/b['T_total_ns']) for a,b in pair],18052801+mi)
                stat.update(case_id=case['id'],baseline=method,ratio_direction='C1 / baseline; lower is better',primary_cold=case['role']=='primary_cold')
                contrasts.append(stat)
                curves=np.array([np.log(np.array(cumulative[b,case['id'],'C1'])/np.array(cumulative[b,case['id'],method])) for b in range(1,blocks+1)])
                ratios=np.exp(curves.mean(axis=0)).tolist();sustained=next((i for i in range(len(ratios)) if all(r<1 for r in ratios[i:])),None)
                breakeven.append({'case_id':case['id'],'baseline':method,'geomean_prefix_ratios':ratios,
                    'first_sustained_lower_observed_prefix':sustained,'not_an_asymptotic_break_even_guarantee':True})
            else:contrasts.append({'case_id':case['id'],'baseline':method,'estimable':False,'reason':'Incomplete paired suite; no speedup assigned to timeout/memory-limit outcomes'})

    total_status=collections.Counter(r['status'] for r in measured)
    result={'attempt_id':protocol['attempt_id'],'protocol_sha256':sha(ROOT/'protocol/pilot_v1.json'),
        'execution_sha256':sha(ATTEMPT/'execution_complete.json'),'index_sha256':sha(ROOT/'results/pilot_runs.jsonl'),
        'warmup_runs':len(warm),'measured_runs':len(measured),'final_blocks':done['final_blocks'],
        'measured_statuses':dict(total_status),'all_completed_outputs_correct':all(r.get('correct',True) for r in records),
        'measured_snapshots_checked':sum(r.get('snapshots',0) for r in measured),
        'measured_query_outputs_checked':sum(r.get('query_outputs',0) for r in measured),
        'unique_real_development_sources':True,'semantic_recall_changed_at_k':None,'incorrect_reuse_rate':None,
        'incorrect_reuse_rate_note':'Full output correctness checked; separate reused-output denominator was not instrumented, so no invented reuse rate.',
        'summary':summary,'contrasts':contrasts,'precision':precision,'noise':noise,'event_trace':traces,'observed_prefix_costs':breakeven,
        'background_load_min':min(b['load_average'][0] for b in backgrounds),
        'background_load_max':max(b['load_average'][0] for b in backgrounds),
        'thermal_reports':dict(collections.Counter(b['thermal_stdout'] for b in backgrounds)),
        'E06_started':False,'scientific_superiority_established':False,'final_baseline_selection_performed':False}
    dump_new(ATTEMPT/'analysis.json',result);dump_new(BASE/'run_components.json',details)

    # Resource model: measured scaling diagnostics, never certify unexecuted scales.
    by={(s['case_id'],s['method']):s for s in summary};scale=by.get(('P07_ready_scale_128','B0_FULL_EXACT'))
    actual_case=next(c for c in protocol['cases'] if c['id']=='P07_ready_scale_128')
    scale_build=scale['median_nested_engine_seconds'].get('build_total') if scale else None
    per_pair=scale_build/(actual_case['fragments']*actual_case['queries']) if scale_build else None
    embedding_ns_per_text=[e['initial_call']['wall_ns']/e['initial_call']['texts'] for e in embeddings]
    # CPython object allocation model, distinct from RSS or an actual scale run.
    # Ready JSON constructs separate float objects; retaining only one tuple
    # per vector is already much larger than packed binary64 storage.
    float_object_bytes=sys.getsizeof(0.0)
    one_vector_python_bytes=768*float_object_bytes+sys.getsizeof(tuple([None]*768))
    forecasts=[]
    for n in [100000,1000000]:
        for m in [32,64,679]:
            forecasts.append({'fragments':n,'queries':m,'packed_binary64_vector_bytes':n*768*8,
                'dense_score_table_bytes_only':n*m*8,'packed_vectors_plus_scores_bytes_only':n*768*8+n*m*8,
                'unshared_Python_float_plus_one_tuple_allocation_model_bytes':n*one_vector_python_bytes,
                'linear_B0_build_seconds_from_239_fragment_probe':per_pair*n*m if per_pair else None,
                'initial_embeddings_linear_seconds_observed_rate_band':[min(embedding_ns_per_text)*n/1e9,max(embedding_ns_per_text)*n/1e9] if embedding_ns_per_text else None,
                'fits_article_budget_verified':False,'actual_run_executed':False})
    memory_probe=[s for s in summary if s['case_id']=='P08_memory_headroom_256']
    resource={'attempt_id':protocol['attempt_id'],'actual_max_documents':256,'actual_max_fragments':max(c['fragments'] for c in protocol['cases']),
        'actual_max_queries':64,'dimension':768,'article_budget_bytes':16*1024**3,
        'diagnostic_memory_limit_bytes':128*1024**2,'diagnostic_probe':memory_probe,'forecasts':forecasts,
        'B0_scale_build_seconds':scale_build,'B0_scale_build_seconds_per_pair':per_pair,
        'source_scale_case':actual_case,'initial_embed_ns_per_text_median':med(embedding_ns_per_text),
        'python_float_object_bytes':float_object_bytes,'python_single_vector_allocation_model_bytes':one_vector_python_bytes,
        'limitations':['Linear build extrapolation from one larger measured shape; no confidence or complexity guarantee',
            'Packed storage omits Python floats/tuples/dicts, JSON input, duplicate snapshots, source text, model, native temporaries and indexes',
            'Python float+tuple allocation model assumes unshared parsed coordinates and one container; extra input lists and snapshots omitted. Allocated object bytes are not a measured simultaneous RSS; compression/swapping/sharing differ.',
            'Sparse query filtering, batch mix, fraction certification, and bigint cost may change with scale',
            'E01 has only 1264 development fragments; no suitable 1e5-1e6-fragment independent corpus prepared',
            'Neither unexecuted scale is certified feasible; obtain suitable data and perform separate scale tests',
            'Sampled RSS is a lower bound; conservative child+self upper bound used for completed runs'],
        'E06_started':False}
    dump_new(ROOT/'reports/e_stages/E05/resource_estimate.json',resource)

    lines=['# E05 — пилот полного пути статьи A','',
        '**Попытка E05_2026-11-18_01.** Реализация A-E04-0.1 сохранена; протокол A-E05-pilot-1.0. Все данные/запуски локальны. E06 не запускался.','',
        'Пилот изучает точную актуальную выдачу сведений о компетенциях для кадровой безопасности. O*NET 29.3 — реальный источник текста; изменения и фильтры контролируемые, запросы шаблонные. Независимой предметной разметки нет; семантический Recall_changed@k и снижение кадровых рисков не оцениваются.','',
        '## Матрица и повторения','',
        'Использована только development-часть; validation и final retrieval/embeddings не применялись. Два cold-сценария заново вычисляют embeddings в каждом процессе, остальные — явно вторичные ready-vector проверки. Cold означает отсутствие кеша готовых embeddings между запусками; системный файловый кеш не очищался.','',
        '| Сценарий | Режим | Документы / фрагменты | Запросы / k | Партии |','|---|---|---:|---:|---:|']
    for c in protocol['cases']:lines.append(f"| {c['id']} | {c['mode']} | {c['documents']} / {c['fragments']} | {c['queries']} / {c['k'][0]} | {c['batches']} |")
    lines += ['',f"Измерительных блоков: **{done['final_blocks']}**; прогревочных запусков {len(warm)}, измерительных {len(measured)}. Исходы измерений: `{dict(total_status)}`. Порядок методов/сценариев перемешивался; процессы запускались последовательно. Решение о дополнительных 20 блоках принято только по заранее заданной ширине интервалов в precision_at_20.json, не по лидерству или p-value.",'',
        'Сценарии включают вставку заранее удержанного лидера, удаление winning fragment, замену текста/версии, изменение применимости, смешанную партию, 20% и 100% изменения, селективность фильтра и короткий/длинный горизонт. P05 намеренно имеет благоприятную форму неизменного свидетеля; выбран по точной геометрии development-данных до замеров, не по скорости. Его результат нельзя переносить на общую область. Фактические доли изменённых документов/фрагментов и затронутых ordered hits записаны для каждой партии в analysis.json/event_trace.','',
        'P08 — отдельная проверка с общим диагностическим лимитом 128 MiB и тремя блоками. Это не ресурсный критерий статьи 16 GiB и не доказательство границы памяти; если лимит не достигнут, наблюдается только работа в измеренном диапазоне. P07 имеет одинаковый лимит времени 30 s для всех методов; остальные временные лимиты закреплены в протоколе.','',
        '## Корректность и полный учёт','',
        f"Проверено {result['measured_snapshots_checked']} полных снимков и {result['measured_query_outputs_checked']} полных query outputs в завершённых измерительных запусках. Необъяснённых расхождений: **0**. Прогрев проверялся отдельно. Cold-вектора восстановлены независимо из сохранённого raw вывода модели, затем выполнен полный snapshot oracle. Векторы повторились побитово между методами и блоками каждого cold-сценария.",'',
        'T_total измерен непосредственно монотонными часами: worker imports/setup, чтение входа, обязательные initial/delta embeddings, построение индекса, обработка всех партий, fallback, материализация и чтения, сериализация. Внешний независимый validator и формирование отчёта исключены. Вложенные engine spans не прибавляются повторно к total. Для отказов сохранены stdout/stderr/лимиты/status; времени незавершённого полного пути и ускорения ему не приписываются.','',
        '## Наблюдаемые затраты','',
        'Медианы T_total в секундах. Строка с неполным числом завершений — только описание успешных запусков с цензурированием; это не результат полной сравнительной серии. Все исходы, включая timeout, сохраняются.','',
        '| Сценарий | Метод | Завершено / запланировано | Медиана total, s | Макс. верхняя граница RSS, MiB |','|---|---|---:|---:|---:|']
    for s in summary:
        upper=s['peak_tree_upper_max_bytes'];lines.append(f"| {s['case_id']} | {s['method']} | {s['status_counts'].get('completed',0)} / {s['planned_blocks']} | {fmt(s['T_total_median_seconds'])} | {fmt(upper/1024**2 if upper else None)} |")
    lines += ['','## Парные отношения и шум','',
        'R = C1 / baseline; меньше 1 означает меньшую стоимость C1. Ниже только primary cold-варианты. Интервалы отражают измерительный шум условно на двух фиксированных разработочных историях; это не выборочная неопределённость предприятий или независимых датасетов и не итоговый E02 критерий полного набора семейств. Ресемплировались целые парные timing blocks (10 000 bootstrap повторов); односторонняя поправка Bonferroni охватывает семь обязательных контрастов внутри одного набора. Одновременное покрытие всех casewise и агрегированных строк вместе не утверждается.','',
        '| История / аналог | R | Центральный 95% интервал | Верхняя односторонняя граница | Отн. полуширина |','|---|---:|---|---:|---:|']
    for key,s in precision['contrasts'].items():
        if s.get('estimable'):lines.append(f"| {key} | {s['ratio']:.3f} | [{s['central_95_low']:.3f}; {s['central_95_high']:.3f}] | {s['one_sided_bonferroni_upper']:.3f} | {s['relative_halfwidth']:.3f} |")
    lines += ['',f"Требование пилотной относительной полуширины ≤0.05 по всем primary-контрастам: **{precision['all_primary_precision_met']}**. Если False, точность для соответствующих контрастов остаётся недостаточной; порог практического эффекта R≤0.90 не изменён. Все casewise отношения, в том числе ready-vector и контроли, — analysis.json/contrasts.",'',
        'Шум дополнительно описан log-SD, lag-1 корреляцией и отношением последней/первой трети блоков. Фоновая нагрузка и системный thermal report сохранены перед каждым запуском. Bootstrap предполагает достаточно стационарные блоки; записанные корреляция/дрейф не превращают это предположение в доказанный факт.','',
        '## Механизм и ресурсные ограничения','',
        'analysis.json/summary содержит отдельно медианы input preparation, initialization, maintenance, reads и serialisation; nested certificate/reverse-filter/refill расходы; число score pairs, успешных клеток, посещённых postings, cache hits и fallback. Компонентные медианы не суммируются в оценку медианы total. run_components.json содержит исходные производные значения каждого запуска.','',
        'P05 позволяет проверить, окупается ли устранение score pairs относительно цены exact-rational BOX. P01/P02/P04/P06/P07 показывают также смену лидера, широкие/селективные фильтры и массовые партии. Эти наблюдения дают материал следующей диагностике E06; метод и параметры по их итогам здесь не изменялись.','',
        'Freshness измерена от начала подготовки raw-партии до завершения публикации снимка; необходимые embeddings включены в cold. Read latency относится к одному bulk answers() всего registry, а не отдельному запросу. p95/p99 и sample count доступны, но недостаточный размер и отсутствие per-query измерителя не позволяют объявить tail-критерий статьи пройденным. Отдельный знаменатель повторно использованных ответов не инструментирован, поэтому incorrect_reuse_rate=NA, несмотря на ноль наблюдаемых ошибок полного ответа.','',
        'RSS sampler даёт нижнюю оценку пика; self ru_maxrss + максимум одного последовательного embedding child — консервативную верхнюю. Сравнение с окончательно выбранным на validation B* не выполнено. Тайм-ауты и диагностические memory-limit исходы не являются доказанным OOM операционной системы.','',
        'Масштабы 10^5 и 10^6 фрагментов **не выполнялись**. resource_estimate.json содержит измеренные масштабы, минимальное упакованное хранение, осторожную линейную оценку build/embedding затрат и её ограничения. Отдельно сохранены измеренные sys.getsizeof размеры Python float/tuple и модель объёма для неразделяемых координат: это оценка аллокаций, не замер simultaneous RSS. Копии входных списков/снимков, JSON, тексты, индексы и буферы добавляют расходы; вычисленный packed размер 8Nd не доказывает выполнимость.','',
        '## Научный исход и дальнейший шаг','',
        'E05 проверяет выполнимость пилота и даёт данные о выигрыше/проигрыше. Универсальное преимущество, мировой приоритет и снижение кадрового риска не установлены. Полный научный критерий E02 не проверен на финальной области; границы и пороги не смягчались. Yi/Simpfer/Simpfer++ — собственные адаптации по локальным источникам, не независимая репликация опубликованного времени авторских программ.','',
        'Сохранены protocol/pilot_v1.json, все results/pilot/…/runs, append-only results/pilot_runs.jsonl, expected oracle traces, analysis.json, precision reports, resource_estimate.json и версионный receipt.']
    report=ROOT/'reports/e_stages/E05/pilot_report.md'
    with report.open('x') as f:f.write('\n'.join(lines)+'\n')
    print(json.dumps({'measured_runs':len(measured),'outcomes':dict(total_status),'snapshots':result['measured_snapshots_checked'],
        'outputs':result['measured_query_outputs_checked'],'precision_met':precision['all_primary_precision_met'],'E06_started':False}))

if __name__=='__main__':main()
