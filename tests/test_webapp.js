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
  f=fixture();f.run("key='hub-key';selectedLaptop='gaming'");
  let targetRequest;f.context.fetch=(url,options)=>{targetRequest=options;return new Promise(done=>{resolve=done})};
  const targetPending=f.run("api('/api/metrics')");f.run("selectedLaptop='local'");resolve({ok:true,json:async()=>({})});
  await assert.rejects(targetPending,/Connection changed/);assert.equal(targetRequest.headers['X-HomeControl-Device'],'gaming');
  f.context.fetch=async(url,options)=>{targetRequest=options;return {ok:true,json:async()=>({})}};
  f.run("selectedLaptop='gaming'");await f.run("api('/api/laptops')");assert.equal(targetRequest.headers['X-HomeControl-Device'],'local');
  assert.equal(targetRequest.headers['X-Access-Key'],'hub-key');
  f.run('document.hidden=true');assert.equal(f.run('pollingAllowed()'),false);
  f.run("document.hidden=false;document.getElementById('liveUpdates').checked=true");assert.equal(f.run('pollingAllowed()'),true);
  const page=fs.readFileSync(path.join(root,'dashboard.html'),'utf8');
  for(const failSave of [false,true]){
    const calls=[],elements=new Map(),checkboxes=[{dataset:{group:'usb',device:'spare-usb'}}];
    const get=id=>{if(!elements.has(id))elements.set(id,{value:id==='deviceGroup'?'usb':'',hidden:true,textContent:id==='featureMessage'?'Selection failed':''});return elements.get(id)};
    const context=vm.createContext({$:get,deviceDirty:true,devicesBusy:false,deviceData:{devices:[]},document:{querySelectorAll:()=>checkboxes},
      renderDevices:()=>{},refreshDevices:()=>{},feature:async(url,body)=>{calls.push({url,body});return url.endsWith('/selections')?(failSave?null:{selections:body.selections}):{results:[]}}});
    vm.runInContext(page.slice(page.indexOf('function currentDeviceSelections()'),page.indexOf("$('deviceEnable').onclick")),context);
    await vm.runInContext("deviceAction('restart')",context);
    assert.equal(calls[0].url,'/api/devices/selections');assert.equal(calls[0].body.selections.usb[0],'spare-usb');
    assert.equal(calls.length,failSave?1:2);
    if(failSave){assert.equal(get('deviceResult').hidden,false);assert.equal(get('deviceResult').textContent,'Selection failed')}
    else{assert.equal(calls[1].url,'/api/devices/action');assert.equal(calls[1].body.action,'restart')}
  }
  const confirmCalls=[],confirmElements=new Map();
  const confirmGet=id=>{if(!confirmElements.has(id))confirmElements.set(id,{value:id==='deviceGroup'?'usb':'',hidden:true,textContent:''});return confirmElements.get(id)};
  const confirmContext=vm.createContext({$:confirmGet,deviceDirty:false,devicesBusy:false,
    deviceData:{devices:[{id:'hub',name:'USB hub',requiresConfirmation:true,warning:'Disconnects child devices'}]},
    document:{querySelectorAll:()=>[{dataset:{group:'usb',device:'hub'}}]},renderDevices:()=>{},refreshDevices:()=>{},
    feature:async(url,body)=>{confirmCalls.push({url,body});return {results:[]}}});
  vm.runInContext(page.slice(page.indexOf('function currentDeviceSelections()'),page.indexOf("$('deviceEnable').onclick")),confirmContext);
  await vm.runInContext("deviceAction('restart')",confirmContext);
  assert.equal(confirmGet('deviceConfirm').hidden,false);assert.equal(confirmCalls.length,0);
  confirmGet('deviceConfirmCancel').onclick();assert.equal(confirmGet('deviceConfirm').hidden,true);assert.equal(confirmCalls.length,0);
  await vm.runInContext("deviceAction('restart')",confirmContext);await confirmGet('deviceConfirmContinue').onclick();
  assert.equal(confirmCalls[0].body.confirmed,true);assert.equal(confirmCalls[0].url,'/api/devices/action');
  assert(!page.includes('Start GPU workload'));assert(!page.includes('/api/gpu/load'));
  const networkCalls=[],networkElements=new Map();
  const networkGet=id=>{if(!networkElements.has(id))networkElements.set(id,{value:'',textContent:'',setAttribute:()=>{}});return networkElements.get(id)};
  const networkContext=vm.createContext({$:networkGet,api:async(url,body)=>{networkCalls.push({url,body});return {available:true,running:false,mbps:null}}});
  vm.runInContext(page.slice(page.indexOf('let networkDirty='),page.indexOf('</script>')),networkContext);
  assert.equal(vm.runInContext('networkRate(0)',networkContext),.1);assert.equal(vm.runInContext('networkRate(25)',networkContext),1);
  assert.equal(vm.runInContext('networkRate(100)',networkContext),1000);assert.equal(vm.runInContext('networkRate(101)',networkContext),null);
  await networkGet('networkUnlimited').onclick();assert.equal(networkCalls[0].url,'/api/network');assert.equal(networkCalls[0].body.mbps,null);
  assert.equal(networkGet('networkValue').textContent,'Unlimited');
  const tweakCalls=[],tweakElements=new Map();
  const tweakGet=id=>{if(!tweakElements.has(id))tweakElements.set(id,{hidden:true,disabled:false,textContent:''});return tweakElements.get(id)};
  const tweakContext=vm.createContext({$:tweakGet,Date,live:{tweakout:{preview:false}},powerDeadline:null,tweakoutDeadline:null,
    tweakoutActive:false,tweakoutBusy:false,pendingTweakoutTarget:null,selectedLaptop:'gaming',laptopList:[{id:'gaming',name:'Gaming laptop'}],
    refreshMetrics:async()=>{},feature:async(url,body)=>{tweakCalls.push({url,body});return {active:url.endsWith('/start'),seconds:body.preview?12:20,state:'cancelled'}}});
  vm.runInContext(page.slice(page.indexOf('function tweakoutCountdown('),page.indexOf('let networkDirty=')),tweakContext);
  tweakGet('tweakoutStart').onclick();assert.equal(tweakCalls.length,0);assert.equal(tweakGet('tweakoutConfirm').hidden,false);
  assert(tweakGet('tweakoutConfirmText').textContent.includes('Gaming laptop'));
  tweakGet('tweakoutBack').onclick();assert.equal(tweakCalls.length,0);assert.equal(tweakGet('tweakoutConfirm').hidden,true);
  tweakGet('tweakoutStart').onclick();vm.runInContext("selectedLaptop='local'",tweakContext);
  await tweakGet('tweakoutContinue').onclick();assert.equal(tweakCalls.length,0);
  vm.runInContext("selectedLaptop='gaming'",tweakContext);tweakGet('tweakoutStart').onclick();await tweakGet('tweakoutContinue').onclick();
  assert.equal(tweakCalls[0].url,'/api/tweakout/start');assert.equal(tweakCalls[0].body.confirmed,true);assert.equal(tweakCalls[0].body.preview,false);
  assert.equal(tweakGet('tweakoutCancel').hidden,false);
  await tweakGet('tweakoutCancel').onclick();assert.equal(tweakCalls[1].url,'/api/tweakout/cancel');
  await tweakGet('tweakoutPreview').onclick();assert.equal(tweakCalls[2].body.preview,true);assert.equal(tweakCalls[2].body.confirmed,false);
  vm.runInContext('renderTweakout({active:false,recoveryPending:true,state:"recovery_needed"})',tweakContext);
  assert.equal(tweakGet('tweakoutCancel').hidden,false);assert.equal(tweakGet('tweakoutStart').disabled,true);
  const appCalls=[],appElements=new Map();
  const appGet=id=>{if(!appElements.has(id))appElements.set(id,{value:'',textContent:'',disabled:false});return appElements.get(id)};
  const appContext=vm.createContext({$:appGet,setInterval:()=>{},key:'test-key',pollingAllowed:()=>true,
    updateOptions:(id,choices,selected)=>{appGet(id).value=selected;appGet(id).choices=choices},
    api:async(url,body)=>{appCalls.push({url,body});return url.endsWith('/launch')?{requested:true,name:'Calculator'}:{apps:[],ready:true,error:''}}});
  vm.runInContext(page.slice(page.indexOf('let launchCatalog='),page.indexOf('function tweakoutCountdown(')),appContext);
  vm.runInContext("renderLaunchApps({ready:true,error:'',apps:[{id:'calc',name:'Calculator',source:'Start menu'},{id:'game',name:'Spare Game',source:'Desktop shortcut'}]})",appContext);
  assert.equal(appGet('launchApp').choices.length,2);appGet('launchSearch').value='calculator';appGet('launchSearch').oninput();
  assert.equal(appGet('launchApp').choices.length,1);assert.equal(appGet('launchApp').value,'calc');
  await appGet('launchButton').onclick();assert.equal(appCalls[0].url,'/api/apps/launch');assert.equal(appCalls[0].body.id,'calc');
  assert(appGet('launchAppState').textContent.includes('Launch requested: Calculator'));
  appGet('launchApp').value='unknown';await appGet('launchButton').onclick();assert.equal(appCalls.length,1);
  await appGet('launchRefresh').onclick();assert.equal(appCalls[1].url,'/api/apps/refresh');assert.equal(appGet('launchButton').disabled,true);
  const switchElements=new Map();const switchGet=id=>{if(!switchElements.has(id))switchElements.set(id,{value:'old command',textContent:'old output',replaceChildren(){this.value=''}});return switchElements.get(id)};
  const switchContext=vm.createContext({$:switchGet,busy:false,terminalBusy:false,devicesBusy:false,networkBusy:false,tweakoutBusy:false,appLaunchBusy:true,laptopsLoading:false,
    selectedLaptop:'local',launchCatalog:{apps:[{id:'old'}]},laptopList:[],deviceDirty:true,networkDirty:true,deviceData:{},status:{},live:{},
    powerDeadline:10,powerAction:'restart',pendingTweakoutTarget:'local',tweakoutDeadline:20,tweakoutActive:true,
    refresh:async()=>{switchContext.status={}},renderLaptops:()=>{}});
  vm.runInContext(page.slice(page.indexOf('async function switchLaptop('),page.indexOf("$('laptopSelect').onchange")),switchContext);
  await vm.runInContext("switchLaptop('desktop')",switchContext);assert.equal(switchContext.selectedLaptop,'local');
  switchContext.appLaunchBusy=false;await vm.runInContext("switchLaptop('desktop')",switchContext);
  assert.equal(switchContext.selectedLaptop,'desktop');assert.equal(switchContext.launchCatalog,null);
  assert.equal(switchGet('command').value,'');assert.equal(switchGet('launchSearch').value,'');assert.equal(switchGet('launchButton').disabled,true);
  assert.equal(switchContext.pendingTweakoutTarget,null);
  // Parse the complete dashboard script as well as the isolated UI fixtures above.
  new vm.Script(page.split('<script>')[1].split('</script>')[0]);
  console.log('Web app checks passed: opt-in storage, relaunch, disconnect, invalid key, standalone, blocked storage, stale requests.');
  console.log('Device UI and internet slider checks passed: selections saved before action, failure aborts, Mbps mapping, Unlimited removes cap.');
  console.log('Tweakout UI checks passed: confirmation, selected laptop, effects-only preview and dashboard cancellation.');
  console.log('App launcher checks passed: search, selected registered app, refresh, invalid selection and computer-switch reset.');
})().catch(error=>{console.error(error);process.exitCode=1});
