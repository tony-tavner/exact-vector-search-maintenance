# Реализации и приёмка E04 статьи A

18.11.2026 · **A-E04-0.1**, attempt **E04_2026-11-18_01**. Входы: E01/E02 valid, метод A-E03-C1-0.3-bounded-fsum / E03_2026-11-18_03, закрытый RW_A_E03_2026-11-18_02. Предмет — точная актуальная выдача сведений о компетенциях для кадровой безопасности; реализация не доказывает полноту компетенций или снижение реального риска.

## Модули

| Файл | Назначение |
|---|---|
| src/pvldb_a/model.py | Immutable query/document/fragment/row; валидация, полные bits/text/config identities, ordered events и version ledger |
| src/pvldb_a/oracle.py | Независимый простой пересчёт из raw snapshot; не импортирует model/engine/bounds |
| src/pvldb_a/native.c, numeric.py | Общее native SIMD multiplication + настоящий math.fsum; attestation/FPCR guards; exact Fraction F_OP/box/norm bounds |
| src/pvldb_a/scoring.py | Пакетный scorer с одинаковыми tiles, группировка max по документу, column cache для сильных конкурентов |
| src/pvldb_a/engine.py | C1 и B0–B6, контроли, exact prefix/refill, single-writer transaction и pinned reader snapshots |
| src/pvldb_a/persistent.py | Persistent AVL внешних postings, внутренних query sets и version ledger, подсчёт скопированных узлов |
| src/pvldb_a/blocks.py, reserve.py | Точные kd/norm blocks; fixed и Yi-style adaptive cap |
| src/pvldb_a/embedding.py, metrics.py | Локальные raw-text embeddings; монотонные вложенные spans и resource accounting |
| scripts/run_pilot.py | Явный E04_SMOKE/E05_PILOT режим, worker isolation, timeout/RSS supervisor, неизменяемые каталоги результатов |

Версии/хеши среды — environment/manifest.json, параметры — configs/e04_implementations.json. Семь обязательных семейств запускаются локально; дополнительные варианты делают полный список METHODS длиной 13. Предоставление baseline вариантов не означает выбор финального варианта по validation: он ещё не выполнен.

## Общий интерфейс и ошибки

`Engine(method, cap=None, leaf_limit=64, certificate_budget=2**20, hybrid_fraction=0.3, disable_box=False)`.

1. `build(documents, queries, corpus_version, config=None, dimension=None)` принимает один полный raw snapshot и registry. Для пустого initial registry нужны явные config/dimension; последующее удаление всех запросов поддержано.
2. `apply(events, corpus_version, expected_corpus_version, queries=None, documents=None, cap=None)` применяет всю упорядоченную партию к приватному staging. Event ops: put_document, delete_document, metadata (changes), put_fragment, delete_fragment. Все конечные affected docs входят в D, в том числе net-same события. Промежуточные fragment identities также проходят ledger: последняя корректная запись не скрывает прежний invalid event.
3. Смена registry/cap/config вызывает полный rebuild. Для нового config/dimension обязателен полный documents snapshot; смешивать его с events запрещено. Для B0/B1/B3 размер сохраняемого ответа равен k; резервные варианты используют cap. B2_ADAPTIVE самостоятельно управляет cap по явно указанной политике.
4. `answers()` либо `with engine.pin() as reader: reader.answers()` возвращает копии полного ответа: query_id, query_version, config_version, corpus_version, ordered_hits с doc_id/fragment_id/text_version.

Входы — обычные распарсенные JSON primitives; arbitrary Python callbacks/objects не поддерживаются. Нет автоматического исправления неверной нормы/NaN/размерности/duplicate IDs или повторного corpus_version. Вектора нормированы с прежней norm tolerance 1e-12; это **не** epsilon ранжирования. Неизвестный op/ID, alias версии, неверный ввод или числовая/ресурсная ошибка завершают операцию исключением до commit. Прежний опубликованный root/ответ сохраняется. Исключения ValueError/KeyError/TypeError/RuntimeError/MemoryError различают причины, но все имеют одинаковую транзакционную семантику отказа.

Каждый успешный commit публикует один immutable root. Старые readers сохраняют прежнюю corpus_version. Пока закреплён более старый root, следующая запись отклоняется `reader_backpressure`; это удерживает максимум old+current/staging roots, а не допускает бесконечную retention. После выхода из pin reader недействителен. Приватные атрибуты/debug Root не являются поддерживаемым интерфейсом долговременного удержания. Персистентность означает sharing неизменяемых структур между in-memory snapshots, не дисковую crash durability.

## Соответствие C1 доказательству

* Сначала validate/apply всей партии, затем полное D и S/R/A. S требует исходный text, ID/version/config и точные bits; отсутствующий text → нет identity evidence → UNKNOWN. Старые fixtures без text не получают выдуманный сертификат.
* Witness h=1 выбирается по минимальному UTF-8 ID из S. Проверяются обе стороны delta; успех только при exact-rational U_can<0 для каждой пары. Сертификаты живут одну партию, budget ограничивает число успешных клеток, отсутствующая клетка — UNKNOWN.
* Query box строится по реальным конечным extrema и epoch, повторно не строится внутри stable-registry партии. При успехе C1 не открывает соответствующий Rev[(doc,block)].
* D_q вычисляется по Cert; frozen last-reserve full key используется до конца партии. Все непокрытые применимые документы получают полный max. C_q<k ⇒ full current refill; иначе сохраняется exact prefix достаточной длины. Представитель/версия не подменяются одним score.
* Persistent AVL хранит также внутренние query sets; изменение одного posting не копирует целый frozenset. Число созданных узлов учитывается. Таблицы root/docs/query references копируются за O(N+M); это реальная дополнительная цена, не нулевая.

Новые документы о числах/переносе: `implementation_numeric_contract.md`, `baseline_adaptations_E04.md`. Они уточняют реализацию, не переписывают E03/E02 и не изменяют критерий преимущества.

## Сильное сравнение и ограничения

B0/B1 используют тот же C kernel, а не Python oracle как заведомо медленную основную базу. B2 имеет fixed/adaptive варианты; B3 сохраняет все scores и document maxima, обновляет только изменённые columns/документы. B4/B5 используют distinct-document lower bounds, block filtering, exact survivors, одинаковые safe geometric primitives и кэш неизменных scores. B4 сохраняет нормы/sample cache; B5 использует frozen exact admission frontier и lazy full score table. B6 переключается по заранее заданной доле партии; данные о финальном времени не используются.

Оригинальные C++/float32 демонстрации не выдаются за наш exact operator. B4/B5 — проверенные на контракт собственные адаптации по локальным первоисточникам и pinned code, с таблицей переносов. Независимой репликации производительности опубликованных программ нет. Это ограничение последующих выводов, а не сокрытие отсутствующего конкурента. Нельзя по E04 заявить преимущество C1.

У C kernel остаётся стоимость PyFloat/tuple allocation и fsum на каждую пару; у BOX — bigint/Fraction стоимость; у persistent structures — Python objects и копии ссылочных таблиц. Кэш B3/B5 может выиграть у C1 на реальном наборе. Эти затраты должен показать E05/E06; вывод «лучший» сейчас не проверялся.

## Измерения без двойного счёта

Worker T_total берётся **напрямую** из двух perf_counter_ns, от входа worker до материализации/сериализации ответов, включая настройку потоков/imports, input preparation, local embeddings в cold режиме, создание Engine/context, index build, все партии, fallback и scheduled reads. Вложенные spans имеют start/end/parent и не суммируются повторно в total. Отдельно сохраняются counters score pairs, bound work, postings, cache hits, refills, path copies. Внешний validator и generation научного JSON report находятся вне интервала; обычная подготовка response JSON включена. Process-launch/supervisor overhead хранится отдельно в samples; worker не получает бесплатный embedding результат от другого запуска.

Ready-vector режим помечен secondary. Cold режим физически запускает pinned llama-embedding для initial/delta новых текстов; общий within-run text cache допустим всем. Model/binary hashes, commands, raw JSON, stderr и нормализованный vector digest сохраняются. Совпадение digest повторных smoke запусков проверяется, но не доказывает произвольную воспроизводимость инференции на всех будущих нагрузках.

RSS дерева процессов семплируется supervisor: observed maximum — **нижняя оценка**, краткие пики могут быть пропущены. Дополнительно worker ru_maxrss плюс максимум ru_maxrss единственного одновременно живого embedding child даёт консервативную верхнюю границу. Это не точный одновременный peak; для ресурсного критерия можно сертифицировать верхней границей либо уточнять измерение в E05. Если она не проходит, нельзя объявлять ресурсное ограничение пройденным только по sampled peak. Timeout, memory-limit termination и crash сохраняются с кодом/причиной, без бесконечного speedup.

## Проверки и следующий этап

Основной differential suite: старые E01/C1 ручные ответы + independent oracle, случайные истории и инвариант exact reserve prefix, ties/subnormal, winner deletion, metadata, empty docs, регистрация/удаление всех queries/config rebuild, aliases, invalid input, fault rollback, pinned readers, обратимые изменения/перестановка независимых событий, остаточные блоки B4/B5, persistent AVL и guards. Использована маленькая **development** выборка O*NET 12 документов/4 запросов в 768D; финальные ответы/embeddings не открывались.

Точный итог и хеши запусков: `validation/implementation_report.json` и версионный E04 receipt. Запуски проверки/инфраструктуры не являются сравнительным научным пилотом. E05 не выполнялся.
