"""Only explicitly queued campaigns or approved corpus initialization are executed."""
import time
import uuid
from main import app
from settings import get_settings
from harness.store import Store
from harness.engine import Engine
from harness.retrieval import snapshot_collection

def knowledge_tick(store):
    owner=uuid.uuid4().hex
    for row in store.list('knowledge_job'):
        state,_=store.checkpoint(row['id'])
        if state.get('status')!='queued' or not store.claim(row['id'],owner,3600): continue
        store.checkpoint(row['id'],{'status':'running'})
        try:
            import sync_act_rag
            result=sync_act_rag.main(include_complementary=False)
            snapshot=snapshot_collection(store,result['collection'],sync_act_rag.QDRANT_URL,result)
            store.checkpoint(row['id'],{'status':'completed','corpus_id':snapshot['id']})
        except Exception as error:
            store.checkpoint(row['id'],{'status':'interrupted','error':str(error)})
        finally: store.release(row['id'],owner)
        return True
    return False

if __name__=='__main__':
    from jobs import run_worker
    store=Store()
    def experimental_tick():
        engine=Engine(store,get_settings())
        from workspace_pipeline import tick
        return tick(store, get_settings()) or knowledge_tick(store) or engine.tick()
    run_worker(app,additive_tick=experimental_tick)
