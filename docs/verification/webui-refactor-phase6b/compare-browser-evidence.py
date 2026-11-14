"""Compare frozen audit baselines with the extracted feature's local runs."""
from pathlib import Path
import collections
import hashlib
import json
import statistics
from PIL import Image, ImageChops

root=Path('.runtime/webui-refactor-phase6b')
evidence=Path('docs/verification/webui-refactor-phase6b')
result={}
for browser,before in [('chrome','before-chrome-6'),('edge','before-edge-3')]:
    a,b=root/before,root/('after-'+browser+'-2')
    old=json.loads((a/'browser-results.json').read_text())
    new=json.loads((b/'browser-results.json').read_text())
    assert old['complete'] and new['complete']
    assert old['audit_focus']==new['audit_focus']
    assert [c['name'] for c in old['checks']]==[c['name'] for c in new['checks']]
    comparisons=[]
    for row in new['screenshots']:
        name=row['file']
        x,y=Image.open(a/name).convert('RGB'),Image.open(b/name).convert('RGB')
        assert x.size==y.size
        bbox=ImageChops.difference(x.crop((0,72,x.width,x.height)),y.crop((0,72,y.width,y.height))).getbbox()
        comparisons.append({'file':name,'identical_below_animated_header':bbox is None,
                            'difference_box_below_y72':bbox})
    def events(folder):
        return [e for line in (folder/'requests.jsonl').read_text().splitlines()
                if (e:=json.loads(line))['path'].startswith('/api/v1/event-history')
                or e['path']=='/api/v1/records/1/history']
    def requests(rows):
        return collections.Counter((e['method'],e['path'],e['query'],e['status'],e['controlled']) for e in rows)
    x,y=events(a),events(b)
    def monitor_searches(folder):
        all_rows=[json.loads(line) for line in (folder/'requests.jsonl').read_text().splitlines()]
        counts=[]
        for i,e in enumerate(all_rows):
            if e['path']!='/api/v1/messages/monitor': continue
            start=next(j for j in range(i+1,len(all_rows)) if all_rows[j]['path']=='/api/v1/event-history/filter-options')
            end=next(j for j in range(start+1,len(all_rows)) if all_rows[j]['path']=='/api/v1/event-history/filter-options')
            counts.append(sum(r['method']=='POST' and r['path']=='/api/v1/event-history/search' and r['status']==200 for r in all_rows[start:end]))
        return counts
    before_monitor,after_monitor=monitor_searches(a),monitor_searches(b)
    assert before_monitor==([1,2] if browser=='chrome' else [2,2])
    assert after_monitor==[2,2]  # initial search and completed reset, each language
    old_counts,new_counts=requests(x),requests(y)
    search_key=('POST','/api/v1/event-history/search','',200,False)
    old_counts[search_key]-=sum(before_monitor)
    new_counts[search_key]-=sum(after_monitor)
    assert old_counts==new_counts,(browser,old_counts-new_counts,new_counts-old_counts)
    # Keep the Chrome baseline timing gap visible. Its first scoped search was
    # still pending when the next navigation began; it is not a new request path.
    if browser=='chrome':
        trace=[json.loads(line) for line in (a/'ui-client-events.jsonl').read_text().splitlines()]
        start=next(i for i,e in enumerate(trace) if e.get('path')=='/api/v1/messages/monitor')
        start=next(i for i in range(start,len(trace)) if trace[i].get('path')=='/api/v1/event-history/search' and trace[i]['event']=='request-start')
        finish=next(i for i in range(start+1,len(trace)) if trace[i].get('path')=='/api/v1/event-history/search' and trace[i]['event']=='request-finish')
        assert any(e['event']=='cancel-reads' for e in trace[start:finish])
    def timing(rows):
        times=[e['milliseconds'] for e in rows if not e['controlled'] and e['status']==200]
        return {'median_ms':statistics.median(times),'max_ms':max(times),'count':len(times)}
    hashes=json.loads((b/'source-environment.json').read_text())['sha256']
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in hashes.items())
    result[browser]={'before':before,'after':'after-'+browser+'-2','checks':len(new['checks']),
                     'screenshots':comparisons,'focus':new['audit_focus'],'focus_equal':True,
                     'all_request_counts_queries_and_outcomes_equal':requests(x)==requests(y),
                     'counts_equal_outside_monitor_reset_segment':True,
                     'monitor_search_counts_before':before_monitor,'monitor_search_counts_after':after_monitor,
                     'uncontrolled_request_times_before':timing(x),'uncontrolled_request_times_after':timing(y),
                     'final_sources_match':True}
result['limits']='Original screenshots retained. Only the unchanged animated header above y72 is excluded. API durations are observations under shared local load, not end-to-end latency guarantees.'
(evidence/'browser-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
for browser in ('chrome','edge'):
    rows=result[browser]['screenshots']
    print(browser,'matching images',sum(r['identical_below_animated_header'] for r in rows),'/',len(rows))
    print('differences',[r for r in rows if not r['identical_below_animated_header']])
assert all(r['identical_below_animated_header'] for browser in ('chrome','edge') for r in result[browser]['screenshots'])
