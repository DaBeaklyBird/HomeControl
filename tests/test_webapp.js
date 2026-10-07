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
  const page=fs.readFileSync(path.join(root,'dashboard.html'),'utf8');
  for(const failSave of [false,true]){
    const calls=[],elements=new Map(),checkboxes=[{dataset:{group:'usb',device:'spare-usb'}}];
    const get=id=>{if(!elements.has(id))elements.set(id,{value:id==='deviceGroup'?'usb':'',hidden:true,textContent:id==='featureMessage'?'Selection failed':''});return elements.get(id)};
    const context=vm.createContext({$:get,deviceDirty:true,devicesBusy:false,deviceData:{},document:{querySelectorAll:()=>checkboxes},
      renderDevices:()=>{},refreshDevices:()=>{},feature:async(url,body)=>{calls.push({url,body});return url.endsWith('/selections')?(failSave?null:{selections:body.selections}):{results:[]}}});
    vm.runInContext(page.slice(page.indexOf('function currentDeviceSelections()'),page.indexOf("$('deviceEnable').onclick")),context);
    await vm.runInContext("deviceAction('restart')",context);
    assert.equal(calls[0].url,'/api/devices/selections');assert.equal(calls[0].body.selections.usb[0],'spare-usb');
    assert.equal(calls.length,failSave?1:2);
    if(failSave){assert.equal(get('deviceResult').hidden,false);assert.equal(get('deviceResult').textContent,'Selection failed')}
    else{assert.equal(calls[1].url,'/api/devices/action');assert.equal(calls[1].body.action,'restart')}
  }
  const networkCalls=[],networkElements=new Map();
  const networkGet=id=>{if(!networkElements.has(id))networkElements.set(id,{value:'',textContent:'',setAttribute:()=>{}});return networkElements.get(id)};
  const networkContext=vm.createContext({$:networkGet,api:async(url,body)=>{networkCalls.push({url,body});return {available:true,running:false,mbps:null}}});
  vm.runInContext(page.slice(page.indexOf('let networkDirty='),page.indexOf('</script>')),networkContext);
  assert.equal(vm.runInContext('networkRate(0)',networkContext),.1);assert.equal(vm.runInContext('networkRate(25)',networkContext),1);
  assert.equal(vm.runInContext('networkRate(100)',networkContext),1000);assert.equal(vm.runInContext('networkRate(101)',networkContext),null);
  await networkGet('networkUnlimited').onclick();assert.equal(networkCalls[0].url,'/api/network');assert.equal(networkCalls[0].body.mbps,null);
  assert.equal(networkGet('networkValue').textContent,'Unlimited');
  console.log('Web app checks passed: opt-in storage, relaunch, disconnect, invalid key, standalone, blocked storage, stale requests.');
  console.log('Device UI and internet slider checks passed: selections saved before action, failure aborts, Mbps mapping, Unlimited removes cap.');
})().catch(error=>{console.error(error);process.exitCode=1});
