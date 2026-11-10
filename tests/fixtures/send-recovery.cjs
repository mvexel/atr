const fs = require('fs'), vm = require('vm'), assert = require('assert');
const source = fs.readFileSync('web/index.html','utf8');
const code = source.slice(source.indexOf('async function post('), source.indexOf('function noteBox('));
const c = {base:'/', inflight:0, current:'original', drafts:{}, sent:{}, sending:{}, armed:{}, cardMeta:{}, cardFns:{}, navigator:{}, Date, noteOpen:new Set(), browserStore:{setItem(){}}, saveDrafts(){}, swapCard(){}, load(){}, dkey:d=>`original/${d.id}/${d.revision}`, window:{confirm:()=>false}};
vm.createContext(c);vm.runInContext(code,c);
(async()=>{
 const d={id:'D01',revision:'old',options:[{key:'A',text:'old'}]}, opt=d.options[0];
 let resolve, calls=0;
 c.fetch=()=>{calls++;return new Promise(r=>resolve=r)};
 const pending=c.answer('original',d,opt);await c.answer('original',d,opt);assert.equal(calls,1);
 c.current='elsewhere';resolve({json:async()=>{throw Error('lost response')}});await pending;
 const key='original/D01/old';assert(c.sent[key].uncertain);assert.equal(c.sent[key].room,'original');
 c.fetch=async url=>{assert(url.includes('room=original'));return {ok:true,json:async()=>({decision:{status:'answered',answer:'B) actual saved choice'}})}};
 await c.reconcile(key);assert(c.sent[key].text.includes('B) actual'));await c.answer('original',d,opt);assert.equal(calls,1);
 c.fetch=async()=>{throw Error('offline')};await c.reconcile(key);assert(c.sent[key].uncertain);
 delete c.sent[key];c.fetch=async()=>({status:409,ok:false,json:async()=>({ok:false})});await c.answer('original',d,opt);assert(c.sent[key].uncertain);
 c.fetch=async()=>({ok:true,json:async()=>({decision:{status:'open',revision:'new',options:[{key:'B',text:'changed'}]}})});await c.reconcile(key);assert.equal(c.sent[key].latest.revision,'new');c.reviewRecovery(key);assert(c.sent[key].uncertain);
 delete c.sent[key];c.drafts[key]='question';c.fetch=async()=>{throw Error('lost')};await c.askQuestion('original',d);assert.equal(c.sent[key].kind,'question');assert.equal(c.sent[key].revision,'old');
 // Render actual affirmative recovery and click its latest-revision option.
 function node(tag, attrs={}, ...kids) { return {tag,attrs,kids:kids.flat(Infinity).filter(x=>x!=null),append(...x){this.kids.push(...x.flat(Infinity).filter(y=>y!=null));}}; }
 Object.assign(c,{el:node,icon:()=>'',linked:x=>x,age:()=>'',safeDocumentLink:()=>null,openWhy:new Set(),armedAt:{},setTimeout:()=>{},openRecord(){},receiptCard:()=>node('receipt'),rewriteQA:x=>x});
 const cardCode=source.slice(source.indexOf('function noteBox('),source.indexOf('// ---------- activity chart:'));
 vm.runInContext(cardCode,c);
 c.current='original';c.window.confirm=()=>true;
 c.sent[key]={room:'original',id:'D01',uncertain:true,latest:{id:'D01',status:'open',revision:'new',title:'Latest',door:'two',options:[{key:'B',text:'New option'}]}};
 c.drafts[key]='preserved note';let card;c.swapCard=k=>{if(c.cardFns[k])card=c.cardFns[k]()};
 c.reviewRecovery(key);assert(card);assert.equal(card.attrs['data-a'],'card:original/D01/new');
 const flatten=n=>typeof n==='object'?[n,...n.kids.flatMap(flatten)]:[];
 const option=flatten(card).find(n=>n.tag==='button'&&n.attrs.class?.startsWith('opt'));
 let payload;c.fetch=async(url,opts)=>{payload=JSON.parse(opts.body);return {ok:true,json:async()=>({ok:true})}};
 option.attrs.onclick();await new Promise(r=>setImmediate(r));assert.equal(payload.revision,'new');assert.equal(payload.choice,'B');assert.equal(payload.note,'preserved note');
 // Restored stale drafts require deliberate copy; another room is not offered.
 delete c.sent[key];for(const k of Object.keys(c.drafts))delete c.drafts[k];c.drafts['original/D01/older']='old draft';c.drafts['other/D01/older']='private';
 card=c.askCard('original',{id:'D01',revision:'newest',options:[],title:'Now',door:'two'},100);
 const buttons=flatten(card).filter(n=>n.tag==='button');const copy=buttons.find(n=>n.kids.includes('Copy reviewed draft to latest revision'));
 assert(copy);assert(!c.drafts['original/D01/newest']);copy.attrs.onclick();assert.equal(c.drafts['original/D01/newest'],'old draft');assert.equal(c.drafts['other/D01/older'],'private');
 console.log('async send recovery fixtures passed');
})().catch(e=>{console.error(e);process.exitCode=1});
