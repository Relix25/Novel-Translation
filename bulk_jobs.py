"""Persistent sequential runs. Every restart/error requires explicit resumption."""
import json
import uuid
from novel_v1 import encode, digest, require
from job_tracking import limits, now, spent, enough_usage
from source_images import require_readable


def preview(library,value):
    from quality_review import policy
    from consumption import estimate
    selected=value.get('numbers', [])
    require(isinstance(selected,list) and all(type(n) is int for n in selected) and len(set(selected))==len(selected),'Invalid selection.')
    require('numbers' not in value or bool(selected), 'Select at least one chapter.')
    count=value.get('count',10)
    require(type(count) is int and count>0,'Choose a positive chapter count.')
    selected=set(selected)
    options={'model':value['model'],'effort':value['effort'],'review':policy(value.get('review')),
             'limits':limits(value.get('limits')),'chapter_limits':limits(value.get('chapter_limits'))}
    chapters=[]
    with library.pair(value['series_id'],value['source'],value['target']) as project:
        origins=library.origins(value['series_id'],value['source'])
        for c in project.status():
            if selected and c['number'] not in selected:continue
            if not selected and origins.get(c['number'],{}).get('kind','chapter') not in ('chapter','intermission','interlude','epilogue','prologue'):continue
            chapter=project.chapter(c['number'])
            if chapter['translation']:
                require(not selected,'A selected chapter already has a translation; review it individually.')
                continue
            packet=project.packet(c['number'])
            require_readable(packet)
            chapters.append({'number':c['number'],'title':c['title'],'paragraphs':len(packet['segments']),
                             'characters':sum(len(s['source']) for s in packet['segments']),
                             'packet_hash':packet['packet_hash'],'volume':origins.get(c['number'],{}).get('volume')})
            if not selected and len(chapters)>=count:break
    require(chapters,'No untranslated chapters in this selection.')
    require(not selected or len(chapters)==len(selected),'A selected chapter is missing.')
    data={'series':value['series_id'],'source':value['source'],'target':value['target'],'chapters':chapters,'options':options}
    return {**data,'fingerprint':digest(encode(data)),'estimate':estimate(sum(c['characters'] for c in chapters),options['model'],options['review'],len(chapters))}


def create(library,value):
    plan=preview(library,value)
    require(plan['fingerprint']==value.get('fingerprint'),'The selection or its context changed. Recalculate the preview.')
    run=uuid.uuid4().hex
    with library.db:
        library.db.execute('BEGIN IMMEDIATE')
        require(not library.db.execute("SELECT 1 FROM bulk_runs WHERE series=? AND source=? AND target=? AND state IN ('queued','running','pause_requested','paused')",(plan['series'],plan['source'],plan['target'])).fetchone(),'A run already exists for this language; resume or cancel it.')
        for c in plan['chapters']:
            require(not library.db.execute("SELECT 1 FROM jobs WHERE series=? AND source=? AND target=? AND number=? AND state IN ('queued','running')",(plan['series'],plan['source'],plan['target'],c['number'])).fetchone(),'A selected chapter already has an active job.')
        library.db.execute('INSERT INTO bulk_runs VALUES(?,?,?,?,?,?,?,?,?)',(run,plan['series'],plan['source'],plan['target'],encode(plan['options']),'queued',None,now(),now()))
        library.db.executemany('INSERT INTO bulk_items(run,position,number,state) VALUES(?,?,?,?)',[(run,i,c['number'],'pending') for i,c in enumerate(plan['chapters'])])
    return run


def control(library,run_id,action,new_limits=None):
    with library.db:
        library.db.execute('BEGIN IMMEDIATE')
        row=library.db.execute('SELECT * FROM bulk_runs WHERE id=?',(run_id,)).fetchone()
        require(row is not None,'Unknown run.')
        options=json.loads(row['options'])
        if action in ('pause','pause-after-call'):
            require(row['state'] in ('queued','running','pause_requested'),'This run is not active.')
            state='pause_requested' if row['state'] in ('running','pause_requested') else 'paused'
            if action=='pause':
                library.db.execute("UPDATE jobs SET stop_requested=1 WHERE run_id=? AND state IN ('queued','running')",(run_id,))
        elif action=='resume':
            require(row['state']=='paused','Only a paused run can be resumed.')
            if new_limits is not None:options['limits']=limits(new_limits)
            tokens,calls=spent(library.db,run=run_id)
            require(tokens<options['limits']['max_tokens'] and calls<options['limits']['max_calls'],'A limit has already been reached; increase it before resuming. Counters are not reset.')
            state='queued'
        elif action=='cancel':
            require(row['state'] in ('paused','queued'),'Pause the run before cancelling it.')
            state='cancelled'
        else:raise ValueError('Unknown command.')
        library.db.execute('UPDATE bulk_runs SET state=?,options=?,error=NULL,updated_at=? WHERE id=?',(state,encode(options),now(),run_id))
    return state


def work(library,run_id,bridge):
    with library.db:
        claimed=library.db.execute("UPDATE bulk_runs SET state='running',updated_at=? WHERE id=? AND state='queued'",(now(),run_id)).rowcount
    if not claimed:return
    current=None
    try:
        row=dict(library.db.execute('SELECT * FROM bulk_runs WHERE id=?',(run_id,)).fetchone())
        options=json.loads(row['options'])
        items=library.db.execute("SELECT * FROM bulk_items WHERE run=? AND state!='done' ORDER BY position",(run_id,)).fetchall()
        for item in items:
            current=item['position']
            require(library.db.execute('SELECT state FROM bulk_runs WHERE id=?',(run_id,)).fetchone()[0]=='running','Pause requested.')
            tokens,calls=spent(library.db,run=run_id)
            require(tokens<options['limits']['max_tokens'] and calls<options['limits']['max_calls'],'Run limit reached; explicitly resume with adjusted limits.')
            kind='translation'
            with library.pair(row['series'],row['source'],row['target']) as project:
                saved=project.chapter(item['number'])
                if saved['translation']:
                    previous=library.db.execute('SELECT result,error FROM jobs WHERE id=?',(item['job'],)).fetchone() if item['job'] else None
                    previous_result=json.loads(previous['result'] or '{}') if previous else {}
                    # Only resume a review against the exact draft saved by this run.
                    require(previous_result.get('saved',{}).get('translation_hash')==saved['translation_hash'], 'This chapter was translated or edited elsewhere; no automatic replacement.')
                    if previous_result.get('quality',{}).get('status') in ('checked','needs_attention') or (not options['review'] and not previous['error']):
                        with library.db:library.db.execute("UPDATE bulk_items SET state='done',error=NULL WHERE run=? AND position=?",(run_id,current))
                        continue
                    require(options['review'],'Review the existing draft manually before resuming.')
                    kind='quality_review'
            job=library.queue_job(row['series'],row['source'],row['target'],item['number'],kind,options['model'],options['effort'],options['review'],options['chapter_limits'],run_id,current)
            library.run_job(job,bridge)
            result=library.db.execute('SELECT state,error FROM jobs WHERE id=?',(job,)).fetchone()
            require(result['state']=='draft' and not result['error'],result['error'] or 'Travail interrompu.')
            missing=library.db.execute('SELECT usage FROM inference_calls WHERE job=?',(job,)).fetchall()
            require(all(enough_usage(json.loads(r[0] or '{}')) for r in missing),'Usage is unknown; pausing before the next chapter.')
            with library.db:library.db.execute("UPDATE bulk_items SET state='done',error=NULL WHERE run=? AND position=?",(run_id,current))
        with library.db:library.db.execute("UPDATE bulk_runs SET state='completed',updated_at=? WHERE id=?",(now(),run_id))
    except Exception as error:
        with library.db:
            library.db.execute("UPDATE bulk_runs SET state='paused',error=?,updated_at=? WHERE id=?",(str(error),now(),run_id))
            if current is not None:library.db.execute("UPDATE bulk_items SET state='failed',error=? WHERE run=? AND position=?",(str(error),run_id,current))
