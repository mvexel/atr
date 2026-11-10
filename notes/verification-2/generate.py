"""Independent synthetic rooms; never reads the canonical store."""
import pathlib,json,time,sys
root=pathlib.Path(sys.argv[1]); root.mkdir(parents=True,exist_ok=True)
for n in range(1,14):
 p=root/'rooms'/f's{n:02}'; (p/'items').mkdir(parents=True,exist_ok=True); (p/'decisions').mkdir(exist_ok=True)
 (p/'BRIEF.md').write_text(f'---\ntitle: Synthetic S{n}\n---\n## Goal\nVerify S{n}\n')
 (p/'now-head.md').write_text('---\nphase: verification\n'+('wait_actor: vendor\nwait_event: shipment\n' if n==4 else '')+'---\n')
 for i,state,owner in [('T06','done','Designer'),('T07','doing' if n in (1,11) else 'todo','Tooling' if n==5 else 'Lead')]:
  (p/'items'/f'{i}.md').write_text(f'---\nid: {i}\ntitle: {i} synthetic action\nstate: {state}\nowner: {owner}\nagent: fixture-{n}\ndepends_on: []\n---\n## Result\nDone: synthetic evidence\nNext: '+('T07' if i=='T06' else 'none')+'\n')
(root/'.atr').mkdir(exist_ok=True)
(root/'.atr/t3-observations.json').write_text(json.dumps({'fixture-1':[time.time(),{'status':'running'}],'fixture-11':[time.time()-600,{'status':'running'}]}))
print(root)
