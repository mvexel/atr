const fs=require('fs'),vm=require('vm'),assert=require('assert');
const src=fs.readFileSync('web/index.html','utf8');
let resolve,draws=0;
const c={settingsOpen:false,settingsSection:'accounts',sheetGeneration:0,sheetStack:[],roomsOpen:false,current:'a',recs:()=>({}),fetchRecord:()=>new Promise(r=>resolve=r),drawSheet:()=>draws++};
vm.createContext(c);
vm.runInContext(src.slice(src.indexOf('async function openRecord('),src.indexOf('function settingsButton()')),c);
(async()=>{
 for(const change of [()=>{c.settingsOpen=true},()=>{c.sheetGeneration++;c.sheetStack=[]},()=>{c.current='b'}]) {
 c.current='a';c.settingsOpen=false;c.sheetStack=[];
 const pending=c.openRecord('D01');const before=draws;change();resolve();await pending;assert.equal(draws,before,'late response redrew changed modal/context');
 }
 c.current='a';c.settingsOpen=false;const pending=c.openRecord('D01');const before=draws;resolve();await pending;assert.equal(draws,before+1);
 console.log('Settings async isolation passed');
})().catch(e=>{console.error(e);process.exitCode=1});
// Exercise Settings sections without touching room, drafts or record stack.
const make=(tag,attrs,...children)=>({tag,attrs,children,append(...nodes){this.children.push(...nodes)}});
const m={el:make,state:{rooms:[]},settingsOpen:false,settingsSection:'accounts',sheetGeneration:0,current:'a',lastRoom:'a',overview:false,sheetStack:['D01'],drafts:{D01:'keep'},document:{activeElement:{id:'settings-opener'}},drawSheet(){},sheetOpenerPending:null,processBlocks(){throw Error('no standing room')},closeSheet(){},showProcess(){}};
vm.createContext(m);vm.runInContext(src.slice(src.indexOf('function settingsButton()'),src.indexOf('function closeSheet()')),m);
m.openSettings();assert.equal(m.settingsOpen,true);assert.equal(m.current,'a');assert.equal(m.drafts.D01,'keep');assert.deepEqual(m.sheetStack,['D01']);
const host=make('host');m.drawSettings(host);const dialog=host.children[0].children[0];assert.equal(dialog.attrs.role,'dialog');assert.equal(dialog.attrs['aria-label'],'Settings');
const sections=dialog.children[1];sections.children[1].attrs.onclick();assert.equal(m.settingsSection,'process');assert.equal(m.lastRoom,'a');assert.equal(m.overview,false);

(async()=>{
 let resolveFetch;const standing={name:'process',standing:true};
 const n={state:{rooms:[standing]},sheetGeneration:1,settingsOpen:true,settingsSection:'process',settingsMaintenanceReady:false,settingsMaintenanceError:'',base:'/',recCache:{},recs:()=>({}),drawSheet(){},fetch:()=>new Promise(r=>resolveFetch=r)};
 vm.createContext(n);vm.runInContext(src.slice(src.indexOf('async function loadSettingsMaintenance('),src.indexOf('function drawSettings(')),n);
 let pending=n.loadSettingsMaintenance();resolveFetch({ok:true,json:async()=>({rooms:[{name:'process',records:{T01:{title:'Actual feedback'}},lanes:[]}]})});await pending;assert(n.settingsMaintenanceReady);assert(n.recCache.process.T01);
 n.settingsMaintenanceReady=false;n.recCache={};pending=n.loadSettingsMaintenance();n.sheetGeneration++;resolveFetch({ok:true,json:async()=>({rooms:[{name:'process',records:{T02:{}}}]})});await pending;assert(!n.settingsMaintenanceReady);assert(!n.recCache.process);
 n.fetch=async()=>{throw Error('offline')};await n.loadSettingsMaintenance();assert(n.settingsMaintenanceError.includes('offline'));
 console.log('Settings maintenance loading passed');
})().catch(e=>{console.error(e);process.exitCode=1});
