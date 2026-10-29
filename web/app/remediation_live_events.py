"""Event stream of durable state changes; never fabricates job progress."""
import hashlib,json,time

def change_stream(read_state, duration=50, interval=.25, clock=time.monotonic, sleep=time.sleep):
    previous=None;started=clock();heartbeat=started
    while clock()-started<duration:
        state=read_state()
        if state is None:return
        revision=hashlib.sha256(json.dumps(state,sort_keys=True,default=str).encode()).hexdigest()
        if revision!=previous:
            yield 'event: activity\ndata: '+json.dumps({'revision':revision})+'\n\n'
            previous=revision
        if state.get('status') not in('queued','running'):return
        if clock()-heartbeat>=10:
            yield ': keepalive\n\n';heartbeat=clock()
        sleep(interval)
