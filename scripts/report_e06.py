#!/usr/bin/env python3
"""Write E06 evidence, interpretation, fairness audit and handoff without tuning."""
import collections, json, statistics
from pathlib import Path
from e05_common import ROOT, sha, dump_new
A=ROOT/'reports/e_stages/E06/E06_2026-11-18_01'
REPORT=ROOT/'reports/e_stages/E06'
OUT=ROOT/'results/comparison/E06_2026-11-18_01'

def write_new(path,text):
    with path.open('x') as f:f.write(text)

def main():
    a=json.loads((OUT/'analysis.json').read_text());g=json.loads((OUT/'geometry_audit.json').read_text())
    original=json.loads((ROOT/'reports/e_stages/E05/E05_2026-11-18_01/analysis.json').read_text())
    protocol=json.loads((ROOT/'protocol/pilot_v1.json').read_text())
    by={(x['case_id'],x['method']):x for x in a['summary']}
    geometry={c:dict(collections.Counter(x['classification'] for x in g['records'] if x['case_id']==c)) for c in sorted({x['case_id'] for x in g['records']})}
    facts=[
      {'id':'D01','classification':'implementation_cost','symptom':'P05: 20/20 cells certify, 0 update score pairs, yet C1/B1=8.831.',
       'evidence':['analysis.json/summary/P05/C1','profiles/E06_diag_v1_P05_ready_dominated_11_C1/profile.json','src/pvldb_a/numeric.py:69'],
       'cause':'Exact Fraction BOX loops over 768 coordinates for both old/new delta fragments: 40 bounds. E05 median certificate span 0.471570 s of 0.480294 s maintenance. Separate profile bounds=0.465742 s; B1 update matrix calls=0.001529 s. Profile times are perturbed and not a replacement speed ratio.',
       'hypothesis':'H01','target':'E07; E03/E04 revalidation if numeric implementation changes'},
      {'id':'D02','classification':'loose_influence_bound','symptom':'P07: 134 paid bounds, zero certified cells, 1.576187 s certificate cost.',
       'evidence':['geometry_audit.json','analysis.json/profile_summary','src/pvldb_a/blocks.py:8'],
       'cause':'One box covers 32 queries. Of 134 attempted cells, 75 satisfy actual strict fixed-witness dominance for every query but fail the box; 59 have a genuinely changed document row. All rejected first bounds have nonnegative exact box support before numeric error is added. Tightening only the rounding envelope cannot fix these rejections.',
       'hypothesis':'H02','target':'E07'},
      {'id':'D03','classification':'redundant_build_cost','symptom':'P06 C1 partition_build median 0.042238 s; 16 norm2 calls in separate build profile cost 0.040722 s.',
       'evidence':['src/pvldb_a/blocks.py:25','src/pvldb_a/engine.py:147','src/pvldb_a/engine.py:179','analysis.json/profile_summary'],
       'cause':'build_blocks computes max_norm2 for C1 although C1 BOX reads only the box. The max_norm2 field is consumed by B4/B5 reverse thresholds. All pilot registries fit one leaf (limit 64), so this cost is not KD splitting. B4/B5 norm ordering also recomputes query norms when assembling blocks.',
       'hypothesis':'H03','target':'E07; implementation validation in E04 for changed code'},
      {'id':'D04','classification':'short_result_fallback','symptom':'P06: 16 queries remain short at every snapshot; C1/B2/B2_ADAPTIVE perform 48 full refills and 968 update score pairs; B3 performs zero new update score pairs.',
       'evidence':['analysis.json/summary/P06','analysis.json/profile_summary','src/pvldb_a/engine.py:216','src/pvldb_a/engine.py:249','src/pvldb_a/scoring.py'],
       'cause':'k=20 while only about 7-9 documents per query are applicable. Enlarging a reserve cannot create missing eligible documents. old.small triggers mandatory refill; metadata-only changes leave vectors reusable, which B3 exploits through its full score cache. Initial B3 cache-fill cost remains charged.',
       'hypothesis':'H04','target':'E07; prove any short-result completeness optimization before implementation'},
      {'id':'D05','classification':'known_component_not_new_gain','symptom':'P01/P07 C1 performs exactly the same score work as fixed-reserve B2; P07 update pairs=9248 and refills=0 in both.',
       'evidence':['analysis.json/summary','src/pvldb_a/engine.py:245','literature/technical_comparison.csv'],
       'cause':'Savings relative to smaller-reserve B1 can be explained by the already-known reserve. They do not establish the value or novelty of C1 coverage. B3 additionally reuses unchanged columns: P07 update score pairs=4960.',
       'hypothesis':'H04','target':'E07; keep B2/B2_ADAPTIVE/B3 mandatory'},
      {'id':'D06','classification':'common_cost_ceiling','symptom':'Cold aggregate C1 fails the 10% target against five strong simple methods.',
       'evidence':['analysis.json/conditional_cold_aggregate_floors','analysis.json/zero_certificate_partition_cold_aggregate'],
       'cause':'With baseline non-engine cost frozen, making all initialization and maintenance free leaves R=0.967264..0.979197 versus B0/B1/B2/B3/B6. Thus only 2.08..3.27% aggregate reduction is available under that restricted change. Removing only C1 certificates/partition leaves R=0.984438..0.994789 versus those methods. Neither is a new implemented result or a universal lower bound.',
       'hypothesis':'H05','target':'E07/E05 planning; E02 only if claim domain is changed'},
      {'id':'D07','classification':'expensive_adapted_baselines','symptom':'C1 passes prospective pilot time target against B4/B5, but this does not extend to B1/B2/B3/B6.',
       'evidence':['analysis.json/profile_summary','analysis.json/summary/P04','src/pvldb_a/engine.py:178','docs/baseline_adaptations_E04.md'],
       'cause':'P04 B4/B5 execute 567/63 rational bounds, no reverse blocks pruned, and 344 update score pairs each, equal to B3. B4 pays additional per-query bounds and sample maintenance. P07 B5 pays 289 bounds while reusing scores, again without block pruning. Original author implementations and published runtimes are not replicated.',
       'hypothesis':'H03','target':'E07 common bound optimizations also supplied to applicable baselines'},
      {'id':'D08','classification':'coverage_limits','symptom':'No observed sustained advantage against B3 in ready-vector histories; two short cold histories do not cover the frozen primary domain.',
       'evidence':['analysis.json/observed_prefixes','analysis.json/conditional_horizon_models','protocol/pilot_v1.json','docs/success_criteria.json'],
       'cause':'The intended primary domain has 100 batches and full family registries. E05 has 3/8 cold batches, one query block per case and uniform bulk reads. No independent popularity sweep or multi-leaf amortization test exists. Every fitted C1-vs-B3 10% affine-horizon model has positive intercept and slope; merely lengthening the same measured cost pattern cannot reach the target. This is conditional extrapolation only.',
       'hypothesis':'H05','target':'E05 if additional comparable pilot cases are required'},
      {'id':'D09','classification':'measurement_scope_limit','symptom':'Three cold casewise intervals miss 5% precision; memory windows differ; reads are bulk-registry calls.',
       'evidence':['reports/e_stages/E05/E05_2026-11-18_01/interpretation.json','analysis.json/primary_statistics','results/pilot_runs.jsonl'],
       'cause':'These restrict precision and resource/tail claims, not the observed exact answers or the large ready-vector cost differences. No additional repeats were selected by favorable effect. Exact process-tree peak, per-query tails and wrong-reuse denominator remain unverified.',
       'hypothesis':'H06','target':'E04 for future instrumentation; E05 for new fixed measurement protocol'}
    ]
    hypotheses=[
      {'id':'H01','priority':2,'proposal':'Reduce cost of a sound canonical bound, potentially a proved cheap first level with exact-rational fallback.',
       'must_preserve':['canonical math.fsum output','strict ties','two-sided delta coverage','UNKNOWN -> exact engine'],
       'test':'Compare same cells and numeric contract; measure paid successful/failed bounds, total update and full path versus B2/B3 and NO_CERT.',
       'reject_if':'Only dot counts improve, full path fails prospective target, or safe bound cannot be proved. Do not replace proof with epsilon.',
       'new_method_implemented':False},
      {'id':'H02','priority':2,'proposal':'Investigate finer/geometry-aware blocks and cost-aware certificate attempts; charge partition/routing and all failed bounds.',
       'test':'Use P07 loose-bound cells as development diagnosis, then predeclare broader development cases; compare no-certificate engine, identical flat predicate and matched adaptive controls. Measure avoided work against all added costs.',
       'reject_if':'Certification improves but routing/bounds cost exceeds savings, or benefit is explained entirely by known reserve/switch.',
       'warning':'The current certificate_budget bounds stored successful cells, not failed-attempt CPU cost. This matches E03 specification and is not an implementation bug.',
       'new_method_implemented':False},
      {'id':'H03','priority':1,'proposal':'Remove unused norm metadata for methods that do not consume it; compute and share reusable norms once where needed.',
       'test':'Static consumer audit, identical outputs and guards, lower partition costs; apply the same applicable optimization to B4/B5 and controls.',
       'reject_if':'Any semantic change or claimed novelty from ordinary caching; this alone cannot establish cold 10% target.',
       'new_method_implemented':False},
      {'id':'H04','priority':2,'proposal':'Explore exact handling of short result sets and reuse of unchanged score columns under metadata updates.',
       'test':'Preserve complete document-max/filters/version semantics; compare B3 full table and adaptive reserve at equal memory. Charge invalidation, metadata handling and full cache build.',
       'reject_if':'Known caching alone explains gain, memory constraints fail, or short-result completeness has no proof.',
       'new_method_implemented':False},
      {'id':'H05','priority':1,'proposal':'Before substantial tuning, establish whether intended 100-batch domain has enough avoidable cost; measure a frozen representative development slice with reachable multi-leaf registries and actual changed-output fractions.',
       'test':'Predeclare development workload, method limits and repetitions; retain the existing E02 primary target and final isolation. Estimate full cost headroom and observed amortization, not ready-vector speed alone.',
       'reject_if':'Optimistic engine-saving ceiling remains below 10% against any mandatory simple baseline, or no useful geometric regime remains under common costs.',
       'scope_change_rule':'A materially new domain/metric requires versioned E02 before confirmation; no selecting successful final cases.',
       'new_method_implemented':False},
      {'id':'H06','priority':1,'proposal':'Before any confirmatory claim, align process-tree memory window, instrument required single-query reads/reused-output denominator, and fix repeat policy under adequate background conditions.',
       'test':'Explicit boundaries, correct denominators, sample counts, unchanged numeric guards; new versioned E04/E05 artifacts. Existing bulk-p95 remains descriptive.',
       'new_method_implemented':False}
    ]
    diagnosis={'article_id':'A','stage_id':'E06','attempt_id':A.name,'version':'A-E06-diagnosis-1.0',
       'status':'completed','gate':'pass','validity':'valid','scope':'Diagnosis of immutable E05 pilot and separate development diagnostics; not superiority or final-domain feasibility.',
       'primary_diagnosis':'No observed overall algorithmic advantage of current C1; expensive certificates, loose query boxes, redundant build metadata and short-result refills.',
       'ten_percent_current_pilot_confirmed':False,'ten_percent_engine_only_current_cold_model_feasible':False,
       'ten_percent_final_domain_feasible':'unresolved; not disproved by the short pilot and not established',
       'scientific_superiority_established':False,'geometry_counts':geometry,'diagnoses':facts,'candidate_hypotheses':hypotheses,
       'open_rework_id':None,'return_policy':'Current diagnosis is valid. New faulty answer/unequal optimization -> E04; invalid statistics -> E06; new measurement needs -> E04/E05; changed domain/novelty -> E02/E03. No E07 implementation in this attempt.',
       'final_holdout_accessed':False,'E07_started':False,'next_stage_authorized':False}
    dump_new(REPORT/'diagnosis.json',diagnosis)
    audit={
      'version':'A-E06-fairness-1.0','common_contract_verified':True,'source_unchanged':True,
      'common_optimizations':['native binary64 products + actual pinned math.fsum','64x128 blocked scorer','same filter/doc-max/ties/version semantics','same atomic final-state batching','same per-run embedding cache and model','same pinned runtime/thread policy'],
      'source_findings':{'unused_C1_norm_field':['src/pvldb_a/blocks.py:25','src/pvldb_a/engine.py:147','src/pvldb_a/engine.py:179'],
                         'shared_scoring':['src/pvldb_a/scoring.py','src/pvldb_a/numeric.py:49'],
                         'short_registry_refill':['src/pvldb_a/engine.py:216','src/pvldb_a/engine.py:249'],
                         'memory_budget_not_time_budget':['docs/implementations.md:37','docs/complexity.md:7','src/pvldb_a/engine.py:212']},
      'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src/pvldb_a').glob('*') if p.is_file()},
      'no_general_optimization_deliberately_withheld_found':True,
      'all_possible_optimizations_or_original_author_speed_verified':False,
      'covariates_not_independently_swept':['query popularity','multi-leaf block structure','long-run amortization in primary 100-batch domain'],
      'scope_limits':['B4/B5/Yi are local exact-contract adaptations; no claim about author-code speed','E05 axes vary jointly; no causal scaling regression from eight cases','P05 has one query; FLAT/SEPARATE comparisons do not establish general factorization/correlation benefit','B3 full cache is a legitimate stronger algorithm within measured memory, not an unfair extra input','Original literature comparison CSV/component_hypotheses contain historical E02/E03 statuses; effective implementation evidence is E04 and measured evidence E05/E06. Historical files preserved.'],
      'publication_resource_and_tail_criterion_verified':False,'E07_started':False}
    dump_new(OUT/'fairness_audit.json',audit)
    fairness='''# E06 — аудит сопоставимости

18.11.2026. Проверена реализация A-E04-0.1 на неизменных входах E05. Проверка касается указанного локального контракта и пилотной области, не оптимальности всех реализаций.

| Проверка | Свидетельство и решение |
|---|---|
| Численный контракт | Все методы используют общий native binary64-products + настоящий pinned math.fsum; фильтры, максимум по фрагментам, UTF-8 ties и версии общие. Проверены source SHA и полные ответы. |
| Общие оптимизации | Общие blocked scorer 64×128, подготовка атомарного final state, фильтрация, embedding runtime/cache, потоки и лимиты. Цена cache/индекса/резерва включена. Разные алгоритмические структуры не должны искусственно выравниваться удалением сильного B3. |
| Полный путь | Прямой worker clock включает imports/setup, входы, модель/embeddings, построение, обновления, fallback, публикацию, чтение и сериализацию. Запуск процесса и исследовательский validator/report остаются вне принятой границы. Вложенные spans не добавлены повторно. |
| Измерения | Перемешанные парные блоки, общий лимит внутри случая. Все 43 measured timeout сохранены. Ни исключения неудобных случаев, ни повторов до удобного результата нет. |
| Аналоги | B0–B6, B2_ADAPTIVE и C1-контроли сохранены. B4/B5 — собственные адаптации Simpfer/Simpfer++, а не воспроизведение времени оригинального C++ кода. Большая цена их рациональных границ объясняет часть выигрыша C1. |
| Оптимизации для следующего варианта | Неиспользуемое C1 поле нормы и повторное вычисление норм — кандидаты на обычную оптимизацию. Общий ускоренный численный примитив следует предоставить и подходящим B4/B5/контролям. Его ещё нет; утверждение о выигрыше после всех возможных оптимизаций не делается. |
| Отдельный профиль | 23 вызова оригинальных функций с диагностическими обёртками, затем 3 точных геометрических аудита. Численные guards сохранены; sys.setprofile/cProfile не применялись, поскольку runtime contract их запрещает. Профильные времена и дорогой geometry oracle не смешаны с E05. |
| Данные и область | Только development. Validation/final retrieval и tuning не выполнялись. Один O*NET выпуск, контролируемые изменения, шаблонные запросы; это не независимые предприятия или реальные release deltas. |
| Недостаточно исследованные оси | Все C1 случаи имеют один leaf при limit=64. Популярность не варьировалась независимо: uniform bulk reads всего registry. k, число запросов, фильтры и партии меняются совместно; по ним нельзя восстановить независимый причинный эффект. |
| Точность и память | Три casewise интервала шире 5%; aggregate семь интервалов точнее 5%. Разные RSS окна не образуют общий интервал. B* ещё не выбран на validation; точный memory ratio и per-query p95/p99 не подтверждены. |

Профиль не отключал guards ради удобства. Его результаты поддерживаются исходными E05 spans, счётчиками и абляциями; отдельные профили не считаются дополнительными статистическими повторениями.

Новых расхождений полного ответа или скрытых исключённых расходов принятого worker-пути не найдено. Аудит достаточен для диагностики и передачи гипотез в E07. Исправления измерений памяти/индивидуальных задержек и уточнённый пилот потребуются до подтверждающего эксперимента; это ограничение не превращается в автоматически пройденный ресурсный критерий. Новые файлы E04/E05 здесь не создавались.

Исторические literature/technical_comparison.csv и docs/component_hypotheses.json сохранены: их «не реализовано/не выполнено» относятся к дате E02/E03. Актуальные основания — E04 implementation report и E05/E06, а не переписывание истории.
'''
    write_new(REPORT/'fairness_audit.md',fairness)
    lines=['# E06 — сравнение, причины проигрыша и достижимость 10%','',
      '**18.11.2026 · E06_2026-11-18_01 · completed / gate pass / valid для диагностики. E07 не начат.**','',
      'Общее преимущество C1 не подтверждено. Выявлены высокая стоимость exact-rational BOX, слабая селективность общей query-box, лишнее вычисление норм при построении и повторные полные поиски при короткой допустимой выдаче. В пределах двух коротких cold-историй только улучшением построения/обслуживания достичь 10% против сильных простых методов нельзя при сохранении прочих наблюдённых расходов. Для исходной области E02 из 100 партий этот вывод остаётся открытым.','',
      '## Основа и проверка','',
      'Повторно разобраны 2 707 measured E05 runs: 2 664 completed и 43 timeout, все полные сохранённые ответы совпали с oracle. Исходные primary-статистики с прежними seeds воспроизведены точно. 76 warmup не участвуют в оценках. Отдельно выполнены 23 диагностических профиля и 3 geometry-аудита на неизменных ready-vector development workloads; они не увеличивают число timing blocks. Код метода, критерии, модель и разбиения не менялись.','',
      'Предмет — актуальная выдача требований к компетенциям для кадровой безопасности. Семантической разметки нет, производственный эффект и полнота компетенций не проверены.','',
      '## Матрица и наблюдаемый эффект','',
      '| Случай | Документы / фрагменты | Запросы / k | Партии | Изменённые документы, доля | Изменённые ordered hits, доля |','|---|---:|---:|---:|---|---|']
    for c in protocol['cases']:
        trace=a['event_trace'][c['id']];changes=[x['changed_document_fraction'] for x in trace];hits=[x['affected_hit_fraction'] for x in trace]
        lines.append(f"| {c['id']} | {c['documents']} / {c['fragments']} | {c['queries']} / {c['k'][0]} | {c['batches']} | {min(changes):.3f}–{max(changes):.3f} | {min(hits):.3f}–{max(hits):.3f} |")
    lines+=['','P01/P02 — cold с физическими embeddings; P03/P04 — соответствующие ready-vector контроли. Между методами cold-векторы побитно совпали, но cold/ready twins не обязаны иметь идентичный способ батчирования инференса, поэтому разность их времён не используется как причинная цена embeddings. Для цены используются фактические spans/embedding calls внутри каждого cold run. Изменённые fragment records включают text_version, а не только новый вектор.','',
      '| Случай | Аналог | R=C1/аналог | Центральный 95% интервал | Статус |','|---|---|---:|---|---|']
    for x in a['contrasts']:
        if x.get('estimable'):lines.append(f"| {x['case_id']} | {x['baseline']} | {x['ratio']:.3f} | [{x['central_95_low']:.3f}; {x['central_95_high']:.3f}] | {'3 блока, только диагностика' if x['resource_probe'] else '40 блоков'} |")
        else:lines.append(f"| {x['case_id']} | {x['baseline']} | NA | NA | timeout; полной серии нет |")
    lines+=['','Случайные единицы — целые парные блоки, не отдельные запросы. Эти интервалы отражают шум фиксированной нагрузки. Secondary таблица исследовательская; совместное покрытие всех строк не обещается. P08 с тремя блоками не поддерживает точный tail/скоростной вывод.','',
      '## Подтверждённый диагноз','']
    for d in facts:
        lines += [f"### {d['id']} — {d['classification']}",d['symptom'],'',d['cause'],'',f"Проверяемая гипотеза: {d['hypothesis']}. Адрес последующей работы: {d['target']}.",'']
    lines += ['','Особенности геометрии: P03 — 3 loose-bound cells и 1 с реально изменившейся строкой; P07 — 75 и 59; P08 — 3 и 41. Всего 81 ложный отказ границы при фактическом строгом доминировании и 101 клетка с изменившейся строкой. Это оплаченная отдельная диагностика всех запросов клетки, не предлагаемый быстрый сертификат. У всех рассмотренных отказов exact box support уже неотрицателен, поэтому устранение только численного запаса недостаточно.','',
      'В P04 десять certified cells означают полностью совпавшие fragment records: BOX вообще не вызывался. Их нельзя выдавать за десять удачных численных границ. В P05 все 40 BOX bounds успешны, но M=1: выигрыш от факторизации многих запросов этим случаем не проверен. FLAT посещает 20 postings вместо 0, однако C1/FLAT≈0.998; экономия перечисления мала относительно сертификата. C1/SEPARATE≈0.908 здесь отражает также цену арифметики, а не доказанную пользу более тесной границы на многозапросных блоках.','',
      '## Достижимы ли 10% по полному пути','',
      'Использованы два явно условных расчёта. F_b=(T_b−initialization_b−maintenance_b)/T_b: даже весь engine конкурента бесплатен, остальные затраты неизменны. Z_b=(T_C1−certificates_C1−partition_build_C1)/T_b: сертификат и построение блоков C1 бесплатны, остальные затраты неизменны. Ничего из этого не является запущенным новым методом. Полные init/maintenance spans не пересекаются; certificate/partition spans также не пересекаются друг с другом.','',
      '| Аналог | Наблюдённый cold R | Условный F_b | Макс. экономия 1−F_b | Условный Z_b |','|---|---:|---:|---:|---:|']
    fs={x['baseline']:x for x in a['conditional_cold_aggregate_floors']};zs={x['baseline']:x for x in a['zero_certificate_partition_cold_aggregate']}
    for b in protocol['mandatory_methods']:
        actual=a['primary_statistics']['contrasts']['cold_equal_history/'+b]
        lines.append(f"| {b} | {actual['ratio']:.4f} | {fs[b]['ratio']:.4f} | {100*(1-fs[b]['ratio']):.2f}% | {zs[b]['ratio']:.4f} |")
    lines+=['','Все числа агрегированы с прежним равным весом двух cold-историй по log ratios внутри timing block. У B0/B1/B2/B3/B6 F_b=0.9673–0.9792, то есть оптимистический резерв составляет только 2.08–3.27%. Основные затраты вне engine: embeddings, чтение/подготовка/проверка локальной модели, imports/setup и прочий обязательный путь. Только embeddings занимают примерно 86–90% baseline total, поэтому утверждение «одни embeddings превышают 90% во всех случаях» было бы неверным.','',
      'Для P05 даже обнуление certificates и partition даёт C1/B1≈0.982 и C1/B3≈0.978: это не 10%. Точная новая реализация может изменить другие расходы, но тогда нужна новая гипотеза и симметричная проверка общих оптимизаций.','',
      'Выводы разделены: (1) нынешний C1 цель не проходит; (2) двигатель поиска при фиксированном остальном пути короткого cold-пилота имеет недостаточный резерв; (3) невозможность во всей области E02 не доказана. Новая версия/длинная история/много запросов могут изменить доли затрат, но такое изменение нужно проверить до открытия final.','',
      '## Окупаемость и граница применимости','',
      'observed_prefixes содержит стоимость от начала worker до каждого materialized read, включая построение; последний prefix включает финальную сериализацию. Нельзя переносить выигрыш только в maintenance на полный prefix. Относительно B3 устойчивого наблюдаемого выигрыша C1 в ready-vector сериях нет. В P08 C1/B0≈0.957 при трёх блоках — ниже 1 точечно, но не требуемые 0.90 и не выигрыш над B1/B2/B3/B6.','',
      'Дополнительно T(H)=A+H·u: A — наблюдённые initial setup/build/first read плюс заключительная сериализация, u — средняя фактическая стоимость цикла партии до следующего read. Для всех восьми случаев при сравнении C1 с 0.9·B3 и intercept, и slope положительны. Поэтому простое продолжение того же среднего cost pattern не создаёт 10%-й окупаемости. Это модель чувствительности, а не прогноз реальной эволюции корпуса: кеши, геометрия и доли новых текстов меняются. Результат для 100 заранее фиксированных партий остаётся непроверенным.','',
      'Популярность и многоблочная структура не исследованы независимо; все запросы читаются uniform bulk call, все C1 registry имеют ≤64 запроса при leaf_limit=64. Нельзя объявить найденной общую границу по M/k/селективности на восьми совместно меняющихся сценариях. Следующий пилот должен проверять заранее выбранную development-часть целевой области, сохраняя отрицательные случаи.','',
      '## Задержки и память рядом со стоимостью','',
      'p95 ниже — описательный pooled показатель отдельных партий/чтений, не независимых датасетов. Read — весь registry, не один запрос. RSS-op — self high-water на конце T_total + максимальный последовательный embedding child; RSS-life — sampled вся жизнь worker, включая последующий исследовательский report. Это разные окна, не верх/низ одного интервала. B* на validation не выбран; ограничения p95/p99 и memory ratio не объявлены пройденными.','',
      '| Случай / метод | Median total, s | Freshness p95, s (n) | Bulk-read p95, ms (n) | RSS-op max, MiB | RSS-life sampled max, MiB |','|---|---:|---|---|---:|---:|']
    for s in original['summary']:
        if s['T_total_median_seconds'] is None:
            lines.append(f"| {s['case_id']} / {s['method']} | timeout | NA | NA | NA | NA |")
        else:
            f=s['freshness'];r=s['reads']
            lines.append(f"| {s['case_id']} / {s['method']} | {s['T_total_median_seconds']:.4f} | {f['p95_seconds']:.6f} ({f['samples']}) | {r['p95_seconds']*1000:.4f} ({r['samples']}) | {s['peak_tree_upper_max_bytes']/2**20:.2f} | {s['peak_tree_lower_max_bytes']/2**20:.2f} |")
    lines+=['','E05 background load average менялся примерно от 7.04 до 27.37. Шум холодного инференса и отдельные длинные задержки сохранены: min/max/geomean, log-SD, lag-1 и late/early ratios доступны в analysis.json и E05 analysis. Три casewise primary интервала шире 5% (P01/B0, P02/B2, P02/B3); aggregate все семь удовлетворяют 5%. Стационарность не объявляется доказанной. Никаких новых зачётных повторов здесь нет.','',
      '## Проверяемые следующие гипотезы','']
    for h in hypotheses:lines += [f"**{h['id']} (приоритет {h['priority']}).** {h['proposal']}",f"Проверка: {h['test']}",('Отклонение: '+h['reject_if']) if 'reject_if' in h else '', '']
    lines += ['Все гипотезы — задания для будущего E07/R02, не реализованные улучшения. При изменении численной границы обязателен возврат к доказательству E03; при изменении кода — валидация E04; новые сравнения имеют новый E05 protocol/run_id. Изменение основной области — новая E02 версия до подтверждения.','',
      '## Статус и состав','',
      'E06 completed / gate pass / valid для диагностики: полный пилот учтён, отрицательные исходы сохранены, причины подтверждены исходными spans/counts, исходным кодом, отдельными профилями и точным geometry audit. Нового критического нарушения полного ответа/учёта времени не обнаружено, открытый R02 не создавался. Непроверенные precision/resource/scale вопросы ограничивают будущие выводы. Гипотеза превосходства и мировой приоритет не подтверждены.','',
      'Основные данные: results/comparison/E06_2026-11-18_01/analysis.json, run_analysis.json, profile_index.json, profiles/, geometry_audit.json, fairness_audit.json и cost_components.png. diagnosis.json содержит symptom→evidence→cause→hypothesis→target; fairness_audit.md — аудит сопоставимости.','',
      'E07 не начат; validation/final не открывались; материалы локальны.','',
      '![Непересекающиеся средние компоненты времени](../../../results/comparison/E06_2026-11-18_01/cost_components.png)']
    write_new(REPORT/'comparison.md','\n'.join(lines)+'\n')
    dump_new(A/'report_generation.json',{'script_sha256':sha(__file__),'analysis_sha256':sha(OUT/'analysis.json'),'geometry_sha256':sha(OUT/'geometry_audit.json'),'E07_started':False})
    print(json.dumps({'diagnoses':len(facts),'hypotheses':len(hypotheses),'E07_started':False}))

if __name__=='__main__':main()
