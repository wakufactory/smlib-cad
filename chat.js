/* CAD-specific conversations; credentials stay in the local Codex process. */
(() => {
  let sessionId = null, busy = false, ready = false, undo = null, proposal = null;
  let editorRevision = 0, loginTimer = null;
  let transcript = [], restoredContext = null;
  let attachments = [], readingImages = false;
  const history = $('chat-history');
  function entry(role, text, error = false, record = true, images = []) {
    if(record){
      transcript.push({role,text,...(error ? {error:true} : {}),...(images.length?{images:images.map(item=>({...item}))}:{})});
      if(transcript.length>100)transcript.shift();
    }
    const box = document.createElement('div'), label = document.createElement('strong');
    box.className = `chat-entry ${role}${error ? ' error' : ''}`;
    label.textContent = {user: 'あなた', assistant: 'GPT', system: 'CAD'}[role];
    box.append(label, document.createTextNode(text));
    for(const image of images){const img=document.createElement('img');img.src=image.dataUrl;img.alt=image.name;box.append(img);}
    history.append(box);
    while (history.children.length > 100) history.firstChild.remove();
    history.scrollTop = history.scrollHeight;
  }
  function controls() {
    $('chat-send').disabled = busy || readingImages || !ready;
    $('chat-stop').disabled = !busy || !sessionId;
    $('chat-reset').disabled = busy || readingImages;
    $('chat-undo').disabled = busy || !undo;
    $('chat-apply').disabled = busy || !proposal;
    $('chat-input').disabled = busy;
    $('chat-login').disabled = busy;
    $('chat-connect').disabled = busy;
    $('chat-proposal').hidden = !proposal;
    $('chat-attach').disabled=busy || readingImages;
    $('chat-files').disabled=busy || readingImages;
    for(const button of $('chat-images').children)if(button.removeButton)button.removeButton.disabled=busy || readingImages;
  }
  function showAttachments(){
    const area=$('chat-images');area.replaceChildren();area.hidden=!attachments.length;
    attachments.forEach((image,index)=>{
      const item=document.createElement('div'),img=document.createElement('img'),remove=document.createElement('button');
      item.className='chat-image';img.src=image.dataUrl;img.alt=image.name;
      remove.type='button';remove.textContent='削除';remove.setAttribute('aria-label',`${image.name} を削除`);
      remove.onclick=()=>{if(busy || readingImages)return;attachments.splice(index,1);showAttachments();controls();};
      item.removeButton=remove;item.append(img,document.createTextNode(image.name),remove);area.append(item);
    });
  }
  $('chat-attach').onclick=()=>$('chat-files').click();
  $('chat-files').onchange=async event=>{
    if(busy || readingImages)return;
    const files=Array.from(event.target.files || []);
    readingImages=true;controls();
    try{
      if(attachments.length+files.length>3)throw Error('画像は3枚まで添付できます');
      const added=[];
      for(const file of files){
        if(!['image/png','image/jpeg','image/webp'].includes(file.type) || !file.size || file.size>2*1024*1024)throw Error('画像はPNG・JPEG・WebP、1枚2 MiB以下にしてください');
        const dataUrl=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('画像を読み込めませんでした'));reader.readAsDataURL(file);});
        added.push({name:file.name.slice(0,200),dataUrl});
      }
      attachments=ModelFile.images([...attachments,...added]);showAttachments();
    }catch(error){entry('system',error.message,true);}
    finally{event.target.value='';readingImages=false;controls();}
  };
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || 'チャットの処理に失敗しました');
    return data;
  }
  async function connect() {
    try {
      const state = await api('/chat/status');
      ready = state.ready;
      $('chat-status').textContent = state.message;
      $('chat-login').hidden = !state.available || ready;
      if (ready || state.login?.error) {
        clearTimeout(loginTimer); loginTimer = null;
        $('chat-login-link').hidden = true;
        if (state.login?.error) $('chat-status').textContent = state.login.error;
      } else if (state.login?.pending) {
        loginTimer = setTimeout(connect, 2000);
      }
    } catch (error) {
      ready = false;
      $('chat-status').textContent = error.message;
    }
    controls();
  }
  function changed() { editorRevision++; }
  for (const [id, event] of [['source', 'input'], ['mode', 'change'], ['example', 'click'], ['model-file', 'change']]) {
    $(id).addEventListener(event, changed);
  }
  async function apply(source, mode) {
    undo = {source: $('source').value, mode: $('mode').value};
    $('source').value = source; $('mode').value = mode; $('sample').value = 'default';
    changed(); proposal = null; controls();
    $('export').disabled = true; $('export-usdz').disabled = true;
    const ok = await preview();
    if (ok === false) entry('system', `プレビューでエラーが出ました。次の送信時にこの内容も添えます。\n${previewFailure?.error || message.textContent}`, true);
  }
  async function send() {
    if (busy || readingImages || !ready || (!$('chat-input').value.trim() && !attachments.length)) return;
    let document;
    try { document = modelDocument(); }
    catch (error) { entry('system', error.message, true); return; }
    const text = $('chat-input').value.trim() || '添付画像を参考にモデルを編集してください。', revision = editorRevision;
    const images=attachments.map(item=>({...item}));
    const {source, mode, parameters} = document;
    const previewError = previewFailure?.source === source && previewFailure?.mode === mode ? previewFailure.error : null;
    busy = true; proposal = null; controls();
    entry('user', text, false, true, images); $('chat-input').value = '';
    $('chat-status').textContent = '送信中…';
    try {
      const sent = await api('/chat/send', {sessionId, message: text, source, mode, parameters, previewError,
        ...(images.length ? {images} : {}),
        ...(restoredContext ? {restoredHistory:restoredContext} : {})});
      sessionId = sent.sessionId; restoredContext=null; attachments=[];showAttachments();controls();
      const deadline = Date.now() + 330000;
      let state;
      do {
        state = await api('/chat/poll', {sessionId});
        if (state.state !== 'running') break;
        if (Date.now() > deadline) throw Error('応答の確認が時間切れになりました。停止を押して再試行してください。');
        $('chat-status').textContent = state.progress || '考えています…';
        await new Promise(resolve => setTimeout(resolve, 700));
      } while (true);
      if (state.state === 'cancelled') {
        entry('system', '停止しました。ソースは変更していません。');
      } else if (state.state === 'failed') {
        throw Error(state.error || 'Codex の処理に失敗しました');
      } else if (state.state === 'completed') {
        entry('assistant', state.result.message);
        if (state.result.source !== null && state.result.source !== source) {
          if (revision !== editorRevision || $('source').value !== source || $('mode').value !== mode) {
            proposal = {source: state.result.source, mode};
            entry('system', '応答待ちの間にソースが変更されたため、変更案を保留しました。');
          } else {
            await apply(state.result.source, mode);
          }
        }
      } else throw Error('チャットの状態を読み取れませんでした');
      $('chat-status').textContent = 'ChatGPT 接続済み';
    } catch (error) {
      entry('system', error.message, true);
      $('chat-status').textContent = '送信に失敗しました';
      // Best effort interruption also covers a lost polling connection.
      if (sessionId) api('/chat/cancel', {sessionId}).catch(() => {});
      if (!sessionId) $('chat-input').value = text;
    } finally { busy = false; controls(); }
  }
  $('chat-send').onclick = send;
  $('chat-connect').onclick = () => { clearTimeout(loginTimer); connect(); };
  $('chat-input').addEventListener('keydown', event => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey) && !event.isComposing) {
      event.preventDefault(); send();
    }
  });
  $('chat-login').onclick = async () => {
    $('chat-login').disabled = true;
    try {
      const state = await api('/chat/login', {}), link = $('chat-login-link');
      const url = new URL(state.url);
      if (url.protocol !== 'https:' || !['auth.openai.com', 'auth0.openai.com', 'chatgpt.com'].includes(url.hostname)) throw Error('ログインURLを確認できませんでした');
      link.href = url.href; link.hidden = false;
      $('chat-status').textContent = 'ログインを開き、サーバーのMacで認証してください';
      clearTimeout(loginTimer); loginTimer = setTimeout(connect, 2000);
    } catch (error) { $('chat-status').textContent = error.message; }
    finally { controls(); }
  };
  $('chat-stop').onclick = async () => {
    $('chat-stop').disabled = true;
    try { await api('/chat/cancel', {sessionId}); $('chat-status').textContent = '停止しています…'; }
    catch (error) { entry('system', error.message, true); controls(); }
  };
  $('chat-reset').onclick = async () => {
    if (busy || readingImages) return;
    try {
      if (sessionId) await api('/chat/reset', {sessionId});
    } catch (error) { entry('system', error.message, true); return; }
    sessionId = null; proposal = null; undo = null; restoredContext=null; transcript=[]; attachments=[];showAttachments();history.replaceChildren();
    controls(); await connect();
  };
  $('chat-undo').onclick = async () => {
    if (!undo || busy) return;
    const previous = undo; undo = null; proposal = null;
    $('source').value = previous.source; $('mode').value = previous.mode;
    $('sample').value = 'default'; changed(); controls();
    entry('system', 'チャットによる変更の直前のソースに戻しました。');
    await preview();
  };
  $('chat-apply').onclick = async () => {
    if (!proposal || busy) return;
    busy = true; controls();
    try { await apply(proposal.source, proposal.mode); }
    finally { busy = false; controls(); }
  };
  globalThis.ModelChat = {
    snapshot: () => transcript.length ? {version:1,messages:transcript.map(item=>({...item,...(item.images?{images:item.images.map(image=>({...image}))}:{})}))} : undefined,
    assertIdle: () => {if(busy || readingImages)throw Error('チャットの応答・画像読み込みを待つか、停止してからJSONを読み込んでください');},
    restore: chat => {
      globalThis.ModelChat.assertIdle();
      const previous=sessionId;
      sessionId=null; proposal=null; undo=null; transcript=[]; attachments=[];showAttachments();history.replaceChildren();
      $('chat-input').value=''; changed();
      const messages=chat?.messages || [];
      for(const item of messages)entry(item.role,item.text,!!item.error,true,item.images || []);
      restoredContext=messages.length ? messages.map(item=>({...item})) : null;
      controls();
      if(previous)api('/chat/reset',{sessionId:previous}).catch(()=>{});
    }
  };
  entry('system', 'モデルの変更を指示してください。現在のソースを送信し、編集結果を反映してプレビューします。', false, false);
  connect();
})();
