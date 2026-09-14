const statusLabels = {starting:'正在启动', connecting:'正在连接', connected:'已连接', retrying:'正在重连', stopping:'正在断开', disconnected:'未连接', error:'连接异常', saved:'设置已保存'};
const messages = {
  'Disconnect before changing settings':'请先断开连接，再修改设置',
  'Invalid transport':'连接方式无效', 'Invalid setting':'设置内容无效',
  'Use a local IPv4 address':'请输入局域网 IPv4 地址', 'Invalid port':'端口应为 1 至 65535 之间的整数',
  'Invalid autoconnect setting':'自动连接设置无效', 'Invalid pairing file':'配对文件格式不正确',
  'Invalid pairing key':'配对密钥无效', 'Settings saved on this computer':'设置已保存在本机',
  'Enter device IP and import pairing file first':'请先搜索设备并完成配对；旧版固件可展开兼容选项导入文件',
  'Connect first':'请先连接设备', 'Please wait five seconds between tests':'请间隔 5 秒再测试提醒',
  'Disconnect before scanning':'请先断开连接，再搜索设备', 'Unknown action':'不支持此操作',
  'Forbidden':'请求校验失败，请刷新网页后重试', 'Invalid request size':'请求内容大小无效',
  'Invalid request':'请求内容格式不正确',
  'Completion sent; sound follows device volume and quiet hours':'完成事件已发送；提示音遵循设备音量和夜间静音设置'
};
function localize(message) {
  if (messages[message]) return messages[message];
  if (statusLabels[message]) return statusLabels[message];
  if (/FileNotFoundError/.test(message)) return '未检测到 Codex，请先打开并登录 Codex 桌面应用或 CLI，然后重新连接；特殊安装位置可在高级设置中手动指定';
  if (/Usage refresh failed/.test(message)) return '用量刷新失败，稍后自动重试';
  if (/Task refresh failed/.test(message)) return '任务状态刷新失败，稍后自动重试';
  if (/TimeoutError/.test(message)) return '连接超时，请检查设备、网络或是否有其他电脑占用连接';
  if (/check device, network and Codex login/.test(message)) return '连接异常，请检查设备、网络和 Codex 登录状态';
  if (/operation failed/.test(message)) return '操作失败，请检查设备连接及系统权限后重试';
  if (/JSON|Unexpected token|Unexpected end|non-hexadecimal/.test(message)) return '文件或请求格式不正确，请使用有效的配对 JSON 文件';
  if (/Failed to fetch|NetworkError|fetch/.test(message)) return '无法连接本机控制台，请确认后台程序仍在运行';
  if (/Address|Octet|octet|IPv4|Expected 4/.test(message)) return 'IP 地址格式不正确，请输入例如 192.168.1.100 的地址';
  return message;
}
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="passport-token"]').content;
let initialized = false, pairing = null, busy = false, exited = false, restarting = false;
let onboarding = false, guideStep = 'environment', editing = false, lastState = null;
let lanDevices=[], pairSession=null, completedPair=null;
async function api(action, data) {
  const response = await fetch('/api/' + action, {method:data === undefined?'GET':'POST',headers:{'X-Passport-Token':token,'Content-Type':'application/json'},body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function notice(message, error=false) { $('notice').textContent=message; $('notice').classList.toggle('error',error); }
function mode() { return document.querySelector('input[name=mode]:checked').value; }
function toggleMode() { $('lan-fields').hidden=mode()!=='lan'; $('ble-fields').hidden=mode()!=='ble'; $('connection-help').textContent=mode()==='ble'?'打开设备设置中的蓝牙开关，让设备靠近电脑，再点击搜索。':'让设备和电脑连接同一路由器，点击搜索，找到后核对校验码完成配对。'; }
document.querySelectorAll('[name=mode]').forEach(el=>el.addEventListener('change',toggleMode));
function configuration() { const cfg={mode:mode(),host:$('host').value,device:$('device').value,port:Number($('port').value),codex:$('codex').value,codex_auto:$('codex-auto').checked,autoconnect:$('autoconnect').checked,voice_enabled:$('voice-enabled').checked,voice_output:$('voice-output').value,voice_ime:$('voice-ime').value,voice_hotkeys:$('voice-hotkeys').checked,voice_doubao_compat:$('voice-doubao-compat').checked,voice_start_key:$('voice-start-key').value,voice_stop_key:$('voice-stop-key').value}; if(pairing)cfg.pairing=pairing; return cfg; }
async function operation(work) { if(busy)return;busy=true;document.body.setAttribute('aria-busy','true');try{await work();if(!exited)await refresh();}catch(error){notice(localize(error.message),true);}finally{busy=false;document.body.removeAttribute('aria-busy');} }
$('pairing').addEventListener('change',async()=>{try{const file=$('pairing').files[0];if(!file)return;if(file.size>65536)throw new Error('配对文件过大');const value=JSON.parse(await file.text());if(!/^[0-9a-f]{64}$/i.test(value.key||''))throw new Error('配对文件格式不正确');pairing={key:value.key};$('key-state').textContent='待保存';notice('配对文件已载入，点击保存即可留在本机。');}catch(error){pairing=null;notice(localize(error.message),true);}});
async function save(){await api('save',configuration());pairing=null;$('pairing').value='';notice('设置已保存。');}
$('settings').addEventListener('submit',event=>{event.preventDefault();operation(async()=>{if(mode()==='ble'&&!$('device').value.trim())throw new Error('请先搜索并选择你的设备，或在高级设置中填写设备名称。');await save();const result=await api('connect',{});$('authorize').hidden=!result.needs_authorization;notice(result.needs_authorization?'豆包需要额外权限，请点击“授权并连接”，在 Windows 弹窗中确认。':'正在连接… 首次蓝牙配对可能会弹出系统配对窗口。');});});
$('save').onclick=()=>operation(save);
$('disconnect').onclick=()=>operation(async()=>{await api('disconnect',{});notice('已断开连接，设置已保留，下次可直接连接。');});
$('test').onclick=()=>operation(async()=>{await api('test',{});notice('完成提醒已排队，请查看活动日志确认发送结果。');});
$('scan').onclick=()=>operation(async()=>{notice('正在搜索蓝牙设备…');$('scan').disabled=true;try{const result=await api('scan',{});$('devices').replaceChildren();for(const device of result.devices){const option=document.createElement('option');option.value=device.address;option.textContent=device.name+' · '+device.address;$('devices').append(option);}$('devices').hidden=!result.devices.length;$('devices-label').hidden=!result.devices.length;if(result.devices.length===1)$('device').value=result.devices[0].address;else if(result.devices.length>1){$('devices').prepend(new Option('请选择你的设备',''));$('devices').value='';$('device').value='';}notice(result.devices.length?'请在下方选择你的 Passport。':'未找到 Passport，请确认设备处于蓝牙模式并靠近电脑。');}finally{$('scan').disabled=false;}});
$('devices').onchange=()=>{$('device').value=$('devices').value;};
async function refresh(){const state=await api('status');lastState=state;if(state.pairing?.status==='success'&&completedPair!==state.pairing.id){completedPair=state.pairing.id;initialized=false;notice('配对已保存，正在连接设备…');}if(!initialized){onboarding=!state.config.setup_complete;for(const id of ['host','device','port','codex'])$(id).value=state.config[id];$('autoconnect').checked=state.config.autoconnect;$('codex-auto').checked=state.config.codex_auto!==false;$('codex-manual').hidden=$('codex-auto').checked;document.querySelector(`input[name=mode][value="${state.config.mode}"]`).checked=true;toggleMode();
for(const field of ['enabled','hotkeys','doubao-compat'])$('voice-'+field).checked=Boolean(state.config['voice_'+field.replaceAll('-','_')]);
for(const field of ['ime','start-key','stop-key'])$('voice-'+field).value=state.config['voice_'+field.replaceAll('-','_')]||'';
if(state.config.voice_output && state.config.voice_output!=="meter"){const option=new Option(state.config.voice_output,state.config.voice_output);$('voice-output').append(option);$('voice-output').value=state.config.voice_output;}
if(state.config.voice_output==="meter")$('voice-output').value="meter";
if(onboarding){$('autoconnect').checked=true;checkEnvironment();}notice(state.status==='connected'?'已连接，正在陪伴你。':'准备好了，随时可以连接。');initialized=true;}
renderNavigation(state);const voice=state.voice||{}; const voiceLabels={off:'语音输入未启用',ready:state.config.voice_output==='meter'?'麦克风测试已就绪，不触发输入法':'麦克风就绪，首页短按下键开始',recording:'正在录音，再次短按下键结束',error:voice.message||'语音连接异常'};
$('voice-status').textContent=voiceLabels[voice.status]||(state.config.voice_enabled?'语音输入将在连接后就绪':'语音输入未启用');
$('voice-meter').hidden=voice.status!=='recording';$('voice-meter').value=voice.peak||0;
const active=['starting','connecting','connected','retrying','stopping'].includes(state.status),connected=state.status==='connected';$('badge').textContent=(statusLabels[state.status] || '状态未知');$('pet').classList.toggle('awake',connected);$('activity').textContent=connected?(state.running?'正在陪你完成任务':'随时迎接下一个灵感'):(active?'正在寻找小伙伴…':'正在休息一会儿');$('detail').textContent=connected?'设备正在接收实时状态更新。':(active?(state.config.mode==='ble'?'请保持设备蓝牙开启；首次连接请在系统窗口输入设备上的六位配对码。':'请保持设备联网，并确认没有被其他电脑占用。'):'连接设备，让小伙伴上线陪你。');$('tasks').textContent=connected?state.running:'—';$('sync').textContent=state.synced_at?new Date(state.synced_at*1000).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}):'—';$('test').disabled=!connected;$('connect').hidden=active;$('save').hidden=active;$('disconnect').hidden=!active;for(const input of document.querySelectorAll('#settings input, #settings select, #scan, #voice-devices'))input.disabled=active;$('key-state').textContent=pairing?'待保存':state.key_present?'✓ 配对密钥已保存在本机':'尚未保存配对密钥';$('usage').replaceChildren();for(const key of ['primary','secondary']){const w=state.usage[key];if(!w||!w.duration)continue;const remaining=Math.max(0,Math.min(100,100-w.used));const row=document.createElement('p');const label=document.createElement('span');label.textContent=w.duration>=1440?`${w.duration/1440} 天`:`${w.duration/60} 小时`;const value=document.createElement('span');value.textContent=`剩余 ${Math.round(remaining)}%`;row.append(label,value);const bar=document.createElement('progress');bar.max=100;bar.value=remaining;$('usage').append(row,bar);}$('logs').replaceChildren();for(const entry of state.logs.slice().reverse()){const li=document.createElement('li'),time=document.createElement('time');time.textContent=new Date(entry.at*1000).toLocaleTimeString('zh-CN');li.append(time,document.createTextNode(localize(entry.message)));$('logs').append(li);}renderPairing(state);}
async function poll(){if(exited)return;if(restarting){setTimeout(poll,2000);return;}try{await refresh();}catch(error){notice('无法连接本机控制台，请重新运行启动程序。',true);}setTimeout(poll,2000);}poll();

$('exit-console').onclick=()=>operation(async()=>{if(window.pywebview?.api){await window.pywebview.api.quit();return;}await api('exit',{});exited=true;document.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);notice('后台已退出，设备已断开。如果页面未自动关闭，可以手动关闭此页。');window.close();});

$('codex-auto').onchange=()=>{$('codex-manual').hidden=$('codex-auto').checked;};

$('voice-devices').onclick=()=>operation(async()=>{const previous=$('voice-output').value;const result=await api('voice_devices',{});$('voice-output').replaceChildren(new Option('请选择虚拟音频设备',''),new Option('仅测试麦克风（不传给输入法）','meter'));for(const d of result.devices)$('voice-output').append(new Option(d.name+' · '+d.api,d.id));if(previous==='meter'||result.devices.some(d=>d.id===previous))$('voice-output').value=previous;else if(result.devices.length)$('voice-output').value=result.devices[0].id;notice(result.devices.length?'已找到虚拟音频设备，请确认输入法的麦克风也已选好。':'未检测到虚拟音频线，请先安装 VB-CABLE（Windows）或 BlackHole（Mac），再刷新。');});
$('voice-ime').onchange=()=>{$('voice-doubao-compat').checked=$('voice-ime').value==='doubao';const preset={xunfei:'f6',doubao:'alt+v'}[$('voice-ime').value]||'';$('voice-start-key').value=preset;$('voice-stop-key').value=preset;notice(preset?'已填入快捷键预设，请确认与输入法设置一致，再保存并连接。':'请填写所选输入法的开始和结束快捷键。');};

$('authorize').onclick=()=>operation(async()=>{
  restarting=true;
  try {
    notice('请在 Windows 授权窗口中确认，随后自动准备并重新连接…');
    const result=await api('authorize',{});
    if(!result.restarting){restarting=false;$('authorize').hidden=true;return;}
    for(let i=0;i<240;i++){
      await new Promise(resolve=>setTimeout(resolve,1000));
      try{
        const response=await fetch('/api/setup',{headers:{'X-Passport-Token':token}});
        if(response.status===403){location.reload();return;}
        if(response.ok){const state=await response.json();notice(state.message);if(state.message.includes('失败'))throw new Error(state.message);}
      }catch(error){if(error.message.includes('失败'))throw error;}
    }
    throw new Error('授权切换尚未完成，请刷新页面检查或重试；后台日志位于本机配置目录。');
  }finally{restarting=false;}
});

function renderNavigation(state) {
  const connected=state.status==='connected';
  const active=['starting','connecting','connected','retrying','stopping'].includes(state.status);
  if(onboarding && connected && state.synced_at) guideStep='ready';
  if(onboarding && guideStep==='ready' && !connected) guideStep='device';
  document.body.classList.toggle('onboarding-device',onboarding && guideStep==='device');
  $('welcome').hidden=!onboarding;
  $('home-actions').hidden=onboarding;
  $('environment-panel').hidden=guideStep!=='environment';
  $('ready-panel').hidden=guideStep!=='ready';
  $('workspace').hidden=onboarding && guideStep==='environment';
  $('connection-panel').hidden=onboarding?guideStep!=='device':!editing;
  $('workspace').classList.toggle('dashboard', $('connection-panel').hidden);
  $('close-settings').hidden=onboarding;
  $('voice-settings').hidden=onboarding;
  $('quick-connect').hidden=active;
  $('edit-settings').setAttribute('aria-expanded',String(editing));
  $('guide-title').textContent={environment:'让小伙伴来到你的桌面',device:'找到你的 Passport',ready:'连接成功，开始陪伴'}[guideStep];
  $('guide-description').textContent=guideStep==='device'?'设备连上 Wi-Fi 后可直接搜索配对，也可以选择蓝牙。':'只需连接一次，以后打开就能继续陪伴你。';
  for(const step of ['environment','device','ready']) {
    if(step===guideStep) $('step-'+step).setAttribute('aria-current','step');
    else $('step-'+step).removeAttribute('aria-current');
  }
}
async function checkEnvironment() {
  $('check-environment').disabled=true;
  $('environment-result').textContent='正在检查电脑…';
  try {
    const result=await api('check_environment',{});
    $('environment-result').textContent=result.codex_found?'✓ 已找到 Codex。连接设备后将验证登录与同步。':'尚未找到 Codex。请打开并登录 Codex 后重新检查，也可继续并在高级设置中指定程序位置。';
  } catch(error) { $('environment-result').textContent=localize(error.message); }
  finally { $('check-environment').disabled=false; }
}
$('check-environment').onclick=checkEnvironment;
$('guide-next').onclick=()=>{guideStep='device';renderNavigation(lastState);notice(mode()==='lan'?'设备连上 Wi-Fi 后，点击“搜索局域网设备”。':'打开设备蓝牙，点击“搜索蓝牙设备”。');};
$('finish-setup').onclick=()=>operation(async()=>{await api('finish_setup',{});onboarding=false;editing=false;notice('设置完成。语音输入可稍后在“连接与功能设置”中启用。');});
$('edit-settings').onclick=()=>{editing=!editing;renderNavigation(lastState);};
$('close-settings').onclick=()=>{editing=false;renderNavigation(lastState);};
$('quick-connect').onclick=()=>operation(async()=>{const result=await api('connect',{});$('authorize').hidden=!result.needs_authorization;if(result.needs_authorization){editing=true;notice('语音输入需要授权，请点击“授权并连接”。');}else notice('正在连接已保存的设备…');});
window.addEventListener('pywebviewready',()=>{$('lifecycle-hint').textContent='关闭窗口后在托盘继续运行；右键托盘图标可以退出。';});

async function scanLan(host='') { return operation(async()=>{
  $('scan-lan').disabled=true;
  $('lan-scan-result').textContent=host?'正在查找指定 IP 的 Passport…':'正在寻找同一网络中的 Passport…';
  try {
    const result=await api('scan_lan',host?{host}:{});lanDevices=result.devices;
    $('lan-devices').replaceChildren(new Option('请选择你的设备',''));
    for(let i=0;i<lanDevices.length;i++) $('lan-devices').append(new Option(lanDevices[i].name+(lanDevices[i].available?'':' · 已被连接'),String(i)));
    $('lan-devices-label').hidden=!lanDevices.length;
    $('pair-lan').hidden=!lanDevices.length;
    if(lanDevices.length===1)$('lan-devices').value='0';
    $('lan-scan-result').textContent=lanDevices.length?'找到设备。请选择要配对的那一台。':(host?'该 IP 未响应。请检查设备地址、网络连通性和固件版本。':'未找到设备。跨子网可展开“按 IP 查找”；旧固件可展开手动连接。');
  }finally{$('scan-lan').disabled=false;}
});}
$('scan-lan').onclick=()=>scanLan();
$('find-lan-ip').onclick=()=>{const host=$('discover-host').value.trim();if(!host){notice('请输入设备 IP 地址',true);return;}return scanLan(host);};
$('pair-lan').onclick=()=>operation(async()=>{
  const value=$('lan-devices').value;
  if(value==='')throw Error('请选择你的设备');
  const device=lanDevices[Number(value)];
  if(!device?.available)throw Error('请先在旧电脑上断开这台设备');
  await save();
  const result=await api('pair_start',{id:device.id,host:device.host});
  pairSession=result.id;notice('请核对电脑和设备上的号码，只在一致时确认。30 秒后自动取消。');
});
$('pair-confirm').onclick=()=>operation(async()=>{await api('pair_confirm',{id:pairSession});notice('等待设备确认，请在设备上按 OK。');});
$('pair-cancel').onclick=()=>operation(async()=>{await api('pair_cancel',{id:pairSession});pairSession=null;notice('已取消配对，原有配对信息不变。');});
function renderPairing(state){
  const pair=state.pairing;
  const pending=pair&&['compare','waiting_device'].includes(pair.status);
  if(pending){editing=true;guideStep='device';renderNavigation(state);}
  $('connect').disabled=Boolean(pending);$('save').disabled=Boolean(pending);
  $('pair-panel').hidden=!pending;
  if(pending){pairSession=pair.id;$('pair-code').textContent=pair.code;$('pair-confirm').disabled=pair.status==='waiting_device';$('pair-instruction').textContent=pair.status==='waiting_device'?'电脑已确认，请在设备上按 OK；未操作会自动超时。':'核对两端号码，一致时在设备上按 OK，并点击下方确认。不同则取消。';}
  for(const element of document.querySelectorAll('#settings input,#settings select,#scan,#scan-lan,#find-lan-ip,#pair-lan,#connect,#save')) {
    if(pending)element.disabled=true;
  }
  if(!pending){$('find-lan-ip').disabled=false;$('scan-lan').disabled=false;$('pair-lan').disabled=false;}
  $('paired-state').textContent=state.key_present?'✓ 已保存配对，之后可直接连接。':'';
  if(pair?.status==='error')notice(pair.message,true);
}
