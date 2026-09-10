const statusLabels = {starting:'正在启动', connecting:'正在连接', connected:'已连接', retrying:'正在重连', stopping:'正在断开', disconnected:'未连接', error:'连接异常', saved:'设置已保存'};
const messages = {
  'Disconnect before changing settings':'请先断开连接，再修改设置',
  'Invalid transport':'连接方式无效', 'Invalid setting':'设置内容无效',
  'Use a local IPv4 address':'请输入局域网 IPv4 地址', 'Invalid port':'端口应为 1 至 65535 之间的整数',
  'Invalid autoconnect setting':'自动连接设置无效', 'Invalid pairing file':'配对文件格式不正确',
  'Invalid pairing key':'配对密钥无效', 'Settings saved on this computer':'设置已保存在本机',
  'Enter device IP and import pairing file first':'请先填写设备 IP 地址并导入配对文件',
  'Connect first':'请先连接设备', 'Please wait five seconds between tests':'请间隔 5 秒再测试提醒',
  'Disconnect before scanning':'请先断开连接，再搜索设备', 'Unknown action':'不支持此操作',
  'Forbidden':'请求校验失败，请刷新网页后重试', 'Invalid request size':'请求内容大小无效',
  'Invalid request':'请求内容格式不正确',
  'Completion sent; sound follows device volume and quiet hours':'完成事件已发送；提示音遵循设备音量和夜间静音设置'
};
function localize(message) {
  if (messages[message]) return messages[message];
  if (statusLabels[message]) return statusLabels[message];
  if (/TimeoutError/.test(message)) return '连接超时，请检查设备、网络或是否有其他电脑占用连接';
  if (/FileNotFoundError/.test(message)) return '未找到 Codex 程序，请检查高级设置中的可执行文件路径';
  if (/Usage refresh failed/.test(message)) return '用量刷新失败，稍后自动重试';
  if (/Task refresh failed/.test(message)) return '任务状态刷新失败，稍后自动重试';
  if (/check device, network and Codex login/.test(message)) return '连接异常，请检查设备、网络和 Codex 登录状态';
  if (/operation failed/.test(message)) return '操作失败，请检查设备连接及系统权限后重试';
  if (/JSON|Unexpected token|Unexpected end|non-hexadecimal/.test(message)) return '文件或请求格式不正确，请使用有效的配对 JSON 文件';
  if (/Failed to fetch|NetworkError|fetch/.test(message)) return '无法连接本机控制台，请确认后台程序仍在运行';
  if (/Address|Octet|octet|IPv4|Expected 4/.test(message)) return 'IP 地址格式不正确，请输入例如 192.168.1.100 的地址';
  return message;
}
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="passport-token"]').content;
let initialized = false, pairing = null, busy = false;
async function api(action, data) {
  const response = await fetch('/api/' + action, {method:data === undefined?'GET':'POST',headers:{'X-Passport-Token':token,'Content-Type':'application/json'},body:data === undefined?undefined:JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '请求失败');
  return result;
}
function notice(message, error=false) { $('notice').textContent=message; $('notice').classList.toggle('error',error); }
function mode() { return document.querySelector('input[name=mode]:checked').value; }
function toggleMode() { $('lan-fields').hidden=mode()!=='lan'; $('ble-fields').hidden=mode()!=='ble'; }
document.querySelectorAll('[name=mode]').forEach(el=>el.addEventListener('change',toggleMode));
function configuration() { const cfg={mode:mode(),host:$('host').value,device:$('device').value,port:Number($('port').value),codex:$('codex').value,autoconnect:$('autoconnect').checked}; if(pairing)cfg.pairing=pairing; return cfg; }
async function operation(work) { if(busy)return;busy=true;try{await work();await refresh();}catch(error){notice(localize(error.message),true);}finally{busy=false;} }
$('pairing').addEventListener('change',async()=>{try{const file=$('pairing').files[0];if(!file)return;if(file.size>65536)throw new Error('配对文件过大');const value=JSON.parse(await file.text());if(!/^[0-9a-f]{64}$/i.test(value.key||''))throw new Error('配对文件格式不正确');pairing={key:value.key};$('key-state').textContent='待保存';notice('配对文件已载入，点击保存即可留在本机。');}catch(error){pairing=null;notice(localize(error.message),true);}});
async function save(){await api('save',configuration());pairing=null;$('pairing').value='';notice('设置已保存。');}
$('settings').addEventListener('submit',event=>{event.preventDefault();operation(async()=>{await save();await api('connect',{});notice('正在连接… 首次蓝牙配对可能会弹出系统配对窗口。');});});
$('save').onclick=()=>operation(save);
$('disconnect').onclick=()=>operation(async()=>{await api('disconnect',{});notice('已断开连接，设置已保留，下次可直接连接。');});
$('test').onclick=()=>operation(async()=>{await api('test',{});notice('完成提醒已排队，请查看活动日志确认发送结果。');});
$('scan').onclick=()=>operation(async()=>{notice('正在搜索蓝牙设备…');$('scan').disabled=true;try{const result=await api('scan',{});$('devices').replaceChildren();for(const device of result.devices){const option=document.createElement('option');option.value=device.address;option.textContent=device.name+' · '+device.address;$('devices').append(option);}$('devices').hidden=!result.devices.length;if(result.devices.length)$('device').value=result.devices[0].address;notice(result.devices.length?'请在下方选择你的 Passport。':'未找到 Passport，请确认设备处于蓝牙模式并靠近电脑。');}finally{$('scan').disabled=false;}});
$('devices').onchange=()=>{$('device').value=$('devices').value;};
async function refresh(){const state=await api('status');if(!initialized){for(const id of ['host','device','port','codex'])$(id).value=state.config[id];$('autoconnect').checked=state.config.autoconnect;document.querySelector(`input[name=mode][value="${state.config.mode}"]`).checked=true;toggleMode();initialized=true;}
const active=['starting','connecting','connected','retrying','stopping'].includes(state.status),connected=state.status==='connected';$('badge').textContent=(statusLabels[state.status] || '状态未知');$('pet').classList.toggle('awake',connected);$('activity').textContent=connected?(state.running?'正在陪你完成任务':'随时迎接下一个灵感'):(active?'正在寻找小伙伴…':'正在休息一会儿');$('detail').textContent=connected?'设备正在接收实时状态更新。':(active?'请检查设备模式、IP 地址，以及是否有其他电脑正在连接。':'连接设备，让小伙伴上线陪你。');$('tasks').textContent=connected?state.running:'—';$('sync').textContent=state.synced_at?new Date(state.synced_at*1000).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}):'—';$('test').disabled=!connected;$('connect').hidden=active;$('save').hidden=active;$('disconnect').hidden=!active;for(const input of document.querySelectorAll('#settings input, #settings select, #scan'))input.disabled=active;$('key-state').textContent=pairing?'待保存':state.key_present?'✓ 配对密钥已保存在本机':'尚未保存配对密钥';$('usage').replaceChildren();for(const key of ['primary','secondary']){const w=state.usage[key];if(!w||!w.duration)continue;const remaining=Math.max(0,Math.min(100,100-w.used));const row=document.createElement('p');const label=document.createElement('span');label.textContent=w.duration>=1440?`${w.duration/1440} 天`:`${w.duration/60} 小时`;const value=document.createElement('span');value.textContent=`剩余 ${Math.round(remaining)}%`;row.append(label,value);const bar=document.createElement('progress');bar.max=100;bar.value=remaining;$('usage').append(row,bar);}$('logs').replaceChildren();for(const entry of state.logs.slice().reverse()){const li=document.createElement('li'),time=document.createElement('time');time.textContent=new Date(entry.at*1000).toLocaleTimeString('zh-CN');li.append(time,document.createTextNode(localize(entry.message)));$('logs').append(li);}}
async function poll(){try{await refresh();}catch(error){notice('无法连接本机控制台，请重新运行启动程序。',true);}setTimeout(poll,2000);}poll();
