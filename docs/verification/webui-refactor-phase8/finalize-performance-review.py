"""Retain explicit review of every repeatable increase, without claiming causal proof."""
import json
from pathlib import Path
r=Path('.runtime/webui-refactor-phase8');details=json.loads((r/'performance-review-details.json').read_text());comparison=json.loads((r/'performance-comparison.json').read_text());assert not comparison['blocked']
notes={
('chrome','classification','ar'):'p90 increases are 7.6/11.0 ms. Slow-cycle API durations remain low and do not explain every total-time difference; request work is identical.',
('chrome','custody','ar'):'Median increases are about 3 ms in both pairs; p90 increases 6.7/0.2 ms. Current slow-cycle API calls are often faster than original calls, so API latency is not a complete explanation.',
('chrome','dashboard_fresh','ar'):'p90 increases 4.7/11.3 ms. The 216.8 ms current outlier includes an 80 ms summary call, versus roughly 22–35 ms in the first original run; other residual variation is not isolated.',
('chrome','dashboard_fresh','en'):'p90 increases 2.6/14.8 ms. A 211.4 ms current cycle has only a 33 ms API call, so the API does not explain the full slower tail.',
('chrome','parent_aggregation','ar'):'p90 increases 13.3/15.3 ms. Slowest totals and API durations overlap across original/current runs; there are no added or duplicate requests.',
('chrome','records','ar'):'Median increases 4.2/1.7 ms. One current slow cycle includes a 22.8 ms API call versus typical 8–12 ms; this does not establish the cause of the small median differences.',
('edge','classification','ar'):'Median increases 0.4/6.0 ms. API durations remain low, and the slower-tail metric does not increase in both pairs.',
('edge','custody','ar'):'Median increases 1.6/7.9 ms. Current slow-cycle API durations do not consistently exceed originals; remaining total-time difference is unisolated.',
('edge','dashboard_fresh','ar'):'Median increases 11.2/2.0 ms. First-pair p90 increases 361.2 ms (244.8%), but second-pair p90 increases only 26.4 ms (18.7%). First-current cycles 7/10 take 540.0/756.2 ms with only 29.9/28.1 ms summary calls. API execution and extra request work do not explain those spikes. The benchmark also includes frontend callbacks, WebDriver readiness polling and two animation frames; this evidence cannot isolate which caused the remaining delay. Retain as an unresolved timing observation, not a proven refactor regression or a fixed issue.',
('edge','dashboard_fresh','en'):'Median increases 8.2/6.5 ms while p90 improves in both pairs. A 54.4 ms API call contributes to one current 190.9 ms cycle; no consistent material slowdown.',
('edge','inbox','en'):'Median increases 5.6/1.9 ms; p90 increases 8.7/6.1 ms. Some API durations vary (including 26.8 ms in a 107.5 ms cycle), but other slow cycles have short API calls, leaving unisolated residual variation.',
('edge','page_to_sign_in','en'):'First pair increases 212.2 ms (24.1%); reverse pair increases only 24.4 ms (2.8%). These are one cold sample per independent process, with no measured API requests. Transport, asset loading, frontend construction and browser scheduling are not separately instrumented, so exact cause is unproven. No repeated material threshold breach.',
('edge','parent_aggregation','en'):'Median increases 0.1/14.7 ms; p90 increases 16.6/13.6 ms. A current 310.4 ms cycle includes a 44.3 ms API call compared with about 26–31 ms in the first original run. API variability explains only part of total variation.',
('edge','record_search','ar'):'Median increases 9.5/11.9 ms. API durations overlap (roughly 20–33 ms in reviewed slow cycles); the p90 increase is not repeatable. No extra requests or slower query shape.',
('edge','record_search','en'):'Median increases 14.5/10.7 ms; p90 increases 5.6/16.0 ms. API durations overlap, with a 36.8 ms call in the 193.1 ms current outlier. Attribution of the small remaining difference is unproven.',
('edge','records','ar'):'p90 increases 4.5/2.4 ms. An isolated current 236.0 ms cycle includes a 122.0 ms API call; the following slow cycles are about 91 ms and calls 7–9 ms. The spike does not form a repeated material p90 increase.',
('edge','settings','ar'):'p90 increases 8.2/0.7 ms. The largest observed cycle is actually original (256.9 ms, including a 174.7 ms API call); current slow cycles are 89–98 ms. No added request work.',
}
assert set(notes)=={(x['browser'],x['workflow'],x['language']) for x in details}
rows=[]
for row in details:
 key=row['browser'],row['workflow'],row['language'];rows.append({**row,'reviewed':True,'review':notes[key],'blocking':False})
result={'all_repeatable_slowdowns_reviewed':True,'workflow_language_groups_reviewed':len(rows),'metrics_reviewed':sum(len(x['metrics']) for x in rows),'blocking_metrics':0,'measured_samples':1744,'excluded_warmups':144,'total_samples':1888,'request_shape_and_count_comparisons':80,'request_differences':0,'method':'Review both independent pair deltas, all four run summaries and the slowest three cycles with per-request API durations for every repeatable positive metric. No reruns or samples discarded for being slow.','conclusion':'Approved 20% AND 100 ms repeated-pair gate passes. Timing is not identical. Smaller increases and isolated Edge spikes remain documented; their exact causes are not all established.','limitations':['Synthetic local fixtures, not production scale','20 ms readiness polling and WebDriver/frame overhead affect both variants','One cold sample per independent process','API execution timing is not end-to-end attribution; overlapping requests must not be naively subtracted'],'reviews':rows}
(r/'performance-review.json').write_text(json.dumps(result,indent=2)+'\n');print('Reviewed',len(rows),'workflow/language groups and',result['metrics_reviewed'],'metrics; no blocking result.')
