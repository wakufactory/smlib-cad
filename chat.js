/* CAD-specific conversations; credentials stay in the local Codex process. */
(() => {
  let sessionId = null, busy = false, ready = false, undo = null, proposal = null;
  let editorRevision = 0, loginTimer = null;
  let transcript = [], restoredContext = null;
  const history = $('chat-history');
  function entry(role, text, error = false, record = true) {
    if(record){
      transcript.push({role,text,...(error ? {error:true} : {})});
      if(transcript.length>100)transcript.shift();
    }
    const box = document.createElement('div'), label = document.createElement('strong');
    box.className = `chat-entry ${role}${error ? ' error' : ''}`;
    label.textContent = {user: 'あなた', assistant: 'GPT', system: 'CAD'}[role];
    box.append(label, document.createTextNode(text));
    history.append(box);
    while (history.children.length > 100) history.firstChild.remove();
    history.scrollTop = history.scrollHeight;
  }
  function controls() {
    $('chat-send').disabled = busy || !ready;
    $('chat-stop').disabled = !busy || !sessionId;
    $('chat-reset').disabled = busy;
    $('chat-undo').disabled = busy || !undo;
    $('chat-apply').disabled = busy || !proposal;
    $('chat-input').disabled = busy;
    $('chat-login').disabled = busy;
    $('chat-connect').disabled = busy;
    $('chat-proposal').hidden = !proposal;
  }
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
    if (busy || !ready || !$('chat-input').value.trim()) return;
    let document;
    try { document = modelDocument(); }
    catch (error) { entry('system', error.message, true); return; }
    const text = $('chat-input').value.trim(), revision = editorRevision;
    const {source, mode, parameters} = document;
    const previewError = previewFailure?.source === source && previewFailure?.mode === mode ? previewFailure.error : null;
    busy = true; proposal = null; controls();
    entry('user', text); $('chat-input').value = '';
    $('chat-status').textContent = '送信中…';
    try {
      const sent = await api('/chat/send', {sessionId, message: text, source, mode, parameters, previewError,
        ...(restoredContext ? {restoredHistory:restoredContext} : {})});
      sessionId = sent.sessionId; restoredContext=null; controls();
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
    if (busy) return;
    try {
      if (sessionId) await api('/chat/reset', {sessionId});
    } catch (error) { entry('system', error.message, true); return; }
    sessionId = null; proposal = null; undo = null; restoredContext=null; transcript=[]; history.replaceChildren();
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
    snapshot: () => transcript.length ? {version:1,messages:transcript.map(item=>({...item}))} : undefined,
    assertIdle: () => {if(busy)throw Error('チャットの応答を待つか、停止してからJSONを読み込んでください');},
    restore: chat => {
      globalThis.ModelChat.assertIdle();
      const previous=sessionId;
      sessionId=null; proposal=null; undo=null; transcript=[]; history.replaceChildren();
      $('chat-input').value=''; changed();
      const messages=chat?.messages || [];
      for(const item of messages)entry(item.role,item.text,!!item.error);
      restoredContext=messages.length ? messages.map(item=>({...item})) : null;
      controls();
      if(previous)api('/chat/reset',{sessionId:previous}).catch(()=>{});
    }
  };
  entry('system', 'モデルの変更を指示してください。現在のソースを送信し、編集結果を反映してプレビューします。', false, false);
  connect();
})();
