// No browser or network: exercise the dashboard's authentication lifecycle in isolated storage.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(root,'dashboard.html'),'utf8').split('<script>')[1].split('function duration(')[0];
function storage(initial={}){const values=new Map(Object.entries(initial));return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,v),removeItem:k=>values.delete(k)}}
function fixture({local=storage(),session=storage(),standalone=false,fragment=''}={}){
  const elements=new Map();const context=vm.createContext({document:{getElementById:id=>{if(!elements.has(id))elements.set(id,{value:'',checked:false,hidden:false,textContent:''});return elements.get(id)}},
    localStorage:local,sessionStorage:session,window:{matchMedia:()=>({matches:standalone})},navigator:{standalone},
    location:{hash:fragment,pathname:'/'},history:{replaceState:()=>{}},URLSearchParams,
    fetch:async()=>({ok:true,status:200,json:async()=>({})})});
  vm.runInContext(source,context);return {context,elements,local,session,run:s=>vm.runInContext(s,context)};
}
(async()=>{
  let f=fixture();f.run("key='test-key';keepSessionKey(key)");await f.run("api('/api/status')");
  assert.equal(f.local.getItem('homecontrol.key'),null);
  f.elements.get('rememberKey').checked=true;await f.run("api('/api/status')");
  assert.equal(f.local.getItem('homecontrol.key'),'test-key');
  let relaunch=fixture({local:f.local});assert.equal(relaunch.run('key'),'test-key');
  assert.equal(relaunch.elements.get('rememberKey').checked,true);
  relaunch.run('forgetKey()');assert.equal(f.local.getItem('homecontrol.key'),null);
  f=fixture({local:storage({'homecontrol.key':'old-key'})});
  f.context.fetch=async()=>({ok:false,status:401,json:async()=>({error:'denied'})});
  await assert.rejects(f.run("api('/api/status')"),/denied/);
  assert.equal(f.local.getItem('homecontrol.key'),null);assert.equal(f.run('key'),'');
  f=fixture({standalone:true,fragment:'#key=test-key'});
  assert.equal(f.elements.get('installHelp').hidden,true);assert.equal(f.local.getItem('homecontrol.key'),null);
  const blocked={getItem:()=>{throw Error('blocked')},setItem:()=>{throw Error('blocked')},removeItem:()=>{throw Error('blocked')}};
  f=fixture({local:blocked,session:blocked});f.run("key='test-key';keepSessionKey(key);forgetKey()");
  let resolve;f=fixture();f.run("key='test-key'");f.context.fetch=()=>new Promise(done=>{resolve=done});
  const pending=f.run("api('/api/status')");f.run('forgetKey()');resolve({ok:true,json:async()=>({})});
  await assert.rejects(pending,/Connection changed/);
  console.log('Web app checks passed: opt-in storage, relaunch, disconnect, invalid key, standalone, blocked storage, stale requests.');
})().catch(error=>{console.error(error);process.exitCode=1});
