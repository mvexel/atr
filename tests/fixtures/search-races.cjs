const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync('web/index.html','utf8');let timer,requests=[];
const storage={window:{get localStorage(){throw Error('denied')}},JSON};vm.createContext(storage);vm.runInContext(source.slice(source.indexOf('const browserStore ='),source.indexOf('let lastRoom ='))+";browserStore.setItem('drafts','x');browserStore.removeItem('drafts');if(browserStore.getItem('drafts')!==null)throw Error('unsafe read');if(Object.keys(storedObject('drafts')).length)throw Error('unsafe restore');",storage);
const c={base:'/',palQ:'first',palSequence:0,palSrv:{},palTimer:null,palOpen:true,state:{rooms:[]},PAL_SRV_KIND:{Items:'item'},palDraw(){},clearTimeout(){},setTimeout(fn){timer=fn;},fetch:()=>new Promise((resolve,reject)=>requests.push({resolve,reject}))};vm.createContext(c);vm.runInContext(source.slice(source.indexOf('function palFetch('),source.indexOf('const palRecent')),c);
(async()=>{c.palFetch();assert.equal(c.palSrv.status,'loading');const first=timer();c.palQ='second';c.palFetch();const second=timer();requests[1].resolve({ok:true,json:async()=>({groups:{Items:[{id:'T02',title:'Second',room:'r',snippet:'result'}]}})});await second;assert.equal(c.palSrv.q,'second');assert.equal(c.palSrv.status,'complete');requests[0].reject(Error('late error'));await first;assert.equal(c.palSrv.q,'second');assert.equal(c.palSrv.status,'complete');c.palQ='offline';c.palFetch();const failed=timer();requests[2].reject(Error('offline'));await failed;assert.equal(c.palSrv.status,'offline');c.palFetch();assert.equal(c.palSrv.status,'loading');const retry=timer();c.palQ='x';c.palFetch();requests[3].resolve({ok:true,json:async()=>({groups:{}})});await retry;assert.equal(c.palSrv.status,'idle');console.log('search races passed');})().catch(e=>{console.error(e);process.exitCode=1});
// Enter on a native palette control must reach its click handler, not open a hit.
let keyHandler,chosen=0,prevented=0;
const keys={document:{activeElement:{id:'',tagName:'BUTTON'},addEventListener:(name,fn)=>keyHandler=fn},palOpen:true,palList:[{}],palSel:0,palChoose:()=>chosen++};
vm.createContext(keys);
const start=source.indexOf('document.addEventListener("keydown", e => {',source.indexOf('function palGroup'));
vm.runInContext(source.slice(start,source.indexOf('// ---------- rooms:',start)),keys);
keyHandler({key:'Enter',preventDefault(){prevented++}});
assert.equal(chosen,0);assert.equal(prevented,0);
keys.document.activeElement={id:'palq',tagName:'INPUT'};
keyHandler({key:'Enter',preventDefault(){prevented++}});
assert.equal(chosen,1);assert.equal(prevented,1);
