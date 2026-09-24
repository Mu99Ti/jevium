(() => {
  if (!document.body) return null;
  const cache = window.__jevFast ||= {ids:new WeakMap(), nodes:new Map(), next:1};
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e,cache.next++);
    const id=cache.ids.get(e); cache.nodes.set(id,e); return id;
  };
  for (const [id,e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const safe = e => !['password','file','hidden'].includes(e.type);
  const loginRoot = e => e.closest('form') || e.parentElement;
  const passwordFields = [...document.querySelectorAll('input[type="password"]')]
    .filter(e => e.getAttribute('autocomplete') !== 'new-password');
  const loginForms = new Set(passwordFields.map(loginRoot));
  const secretOf = e => {
    if (e.type === 'password') {
      return e.getAttribute('autocomplete') === 'new-password' ? null : 'password';
    }
    const form = e.form || loginRoot(e);
    const ac = (e.getAttribute('autocomplete') || '').toLowerCase();
    const hay = [e.name || '', e.id || '', e.placeholder || '',
      e.getAttribute('aria-label') || ''].join(' ');
    if (loginForms.has(form) && (
        ['username', 'email'].includes(ac) || e.type === 'email' ||
        /(^|[^a-z])(user(name)?|e-?mail|login|account)([^a-z]|$)/i.test(hay)
    )) return 'username';
    if (ac === 'cc-number' || /\b(card number|cardnumber|credit card)\b/i.test(hay)) return 'card_number';
    if (ac === 'cc-exp' || /\b(expiry|expiration|exp date)\b/i.test(hay)) return 'card_expiry';
    if (ac === 'cc-csc' || /\b(cvv|cvc|card security code)\b/i.test(hay)) return 'card_cvv';
    if (ac === 'cc-name' || /\b(cardholder|name on card)\b/i.test(hay)) return 'card_name';
    return null;
  };
  const visible = e => !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const name = (e,seen=new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const referenced=(e.getAttribute('aria-labelledby')||'').split(/\s+/)
      .map(id=>name(document.getElementById(id),seen)).filter(Boolean).join(' ');
    return referenced || e.getAttribute('aria-label') ||
      [...(e.labels||[])].map(l=>name(l,seen)).filter(Boolean).join(' ') ||
      (['button','submit','reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName==='INPUT' ? '' : [...e.childNodes].map(n=>n.nodeType===3 ? n.textContent :
        n.nodeType===1 && n.getAttribute('aria-hidden')!=='true' ? name(n,seen) : '').join(' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const roles=['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio',
    'option','gridcell','combobox','textbox','searchbox','spinbutton'];
  const selector='a[href],button,input,textarea,select,summary,[contenteditable="true"],'+
    roles.map(role=>'[role="'+role+'"]').join(',');
  const role = e => {
    const explicit=e.getAttribute('role');
    if (roles.includes(explicit)) return explicit;
    if (e.tagName==='BUTTON' || e.tagName==='SUMMARY') return 'button';
    if (e.tagName==='A') return 'link';
    if (e.tagName==='SELECT') return 'combobox';
    if (e.tagName==='TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName==='INPUT') {
      if (['checkbox','radio'].includes(e.type)) return e.type;
      if (['button','submit','reset','image'].includes(e.type)) return 'button';
      if (e.type==='search') return 'searchbox';
      if (e.type==='number') return 'spinbutton';
      if (e.type==='password') return 'textbox';
      if (['text','email','url','tel'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  cache.pageKey=()=>[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    [...document.querySelectorAll('input,textarea,select')].filter(e => safe(e) && !secretOf(e))
      .map(e=>[identity(e),e.value,e.checked,e.selectedIndex,e.disabled,e.readOnly])];
  cache.guard=e=>{
    if (!e?.isConnected || !visible(e)) return null;
    const scope=e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    const guardSecret=secretOf(e);
    const guardValue=guardSecret ? (e.value ? '***' : '') : (e.value ?? null);
    return [identity(e),role(e),name(e),guardValue,e.checked??null,e.selectedIndex??null,
      e.readOnly??null,e.matches(':disabled'),e.getAttribute('aria-disabled'),
      e.getAttribute('aria-expanded'),e.getAttribute('aria-checked'),e.getAttribute('aria-selected'),
      e.getAttribute('href'),scope?.innerText?.slice(0,6000)||''];
  };
  const riskOf = (e, secret) => {
    if (secret === 'password') return 'credential';
    if (secret === 'username') return 'username';
    if (secret) return secret;
    const hay = [e.getAttribute('autocomplete')||'', e.name||'', e.id||'', e.placeholder||'',
      e.getAttribute('aria-label')||'', e.value||'', e.innerText||''].join(' ');
    if (e.getAttribute('autocomplete')==='one-time-code' ||
        /(^|[^a-z])(otp|one[- ]?time|verification code|security code|2fa)([^a-z]|$)/i.test(hay)) return 'otp';
    if (/\b(pay now|pay|buy now|purchase|checkout|place order|order now|complete order|subscribe now|book now)\b/i.test(hay))
      return 'pay';
    return null;
  };
  const pageRiskSrc = f => {
    const src = f.getAttribute('src') || '';
    if (/recaptcha|hcaptcha|turnstile/i.test(src)) return 'captcha';
    if (/paypal/i.test(src)) return 'paypal';
    if (/stripe/i.test(src)) return 'stripe';
    return null;
  };
  const actions=[];
  for (const e of document.querySelectorAll(selector)) {
    const secret = secretOf(e);
    if ((!safe(e) && secret !== 'password') || !visible(e) || e.matches(':disabled') ||
        e.closest('[aria-disabled="true"]')) continue;
    const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2, rname=role(e);
    if (!rname || r.width<=0 || r.height<=0 || x<0 || y<0 || x>=innerWidth || y>=innerHeight) continue;
    if (rname==='gridcell' && e.querySelector('button,[role="button"]')) continue;
    const base={node:identity(e),role:rname,label:name(e)||rname,
      rect:{x:r.x,y:r.y,w:r.width,h:r.height}};
    if (secret) base.secret = secret;
    const testid = e.getAttribute('data-testid');
    if (testid) base.testid = testid;
    if (loginForms.has(e.form || loginRoot(e))) base.login_form = true;
    const risk = riskOf(e, secret);
    if (risk) base.risk = risk;
    for (const key of ['checked','selected','expanded']) {
      const value=e.getAttribute('aria-'+key);
      if (value!==null) base[key]=value;
    }
    if (['checkbox','radio'].includes(e.type)) base.checked=String(e.checked);
    if (e.tagName==='SELECT') {
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base,kind:'select',value:o.value,
          current_value:[...e.selectedOptions].map(o=>o.label).join(', '),label:base.label+' → '+o.label});
    } else {
      const editable=!e.readOnly && e.getAttribute('aria-readonly')!=='true' &&
        (['textbox','searchbox','spinbutton'].includes(rname) ||
          (rname==='combobox' && ['INPUT','TEXTAREA'].includes(e.tagName)));
      const raw='value' in e ? String(e.value) :
        e.isContentEditable || rname==='combobox' ? e.innerText.trim() : '';
      const value = secret ? (raw ? '***' : '') : raw;
      actions.push({...base,kind:editable?'fill':'click',value});
      if (editable) actions.push({...base,kind:'click',value,label:'Open '+base.label});
    }
  }
  const pageRiskSet = new Set();
  for (const f of document.querySelectorAll('iframe,embed')) {
    if (!visible(f)) continue;
    const r = pageRiskSrc(f);
    if (r) pageRiskSet.add(r);
  }
  const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  const range=document.createRange(); let node,length=0;
  while ((node=walker.nextNode()) && length<6000) {
    const value=node.textContent.trim(), parent=node.parentElement;
    if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
    range.selectNodeContents(node); const r=range.getBoundingClientRect();
    if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
      words.push(value); length+=value.length;
    }
  }
  const text=words.join('\n').slice(0,6000), height=document.documentElement.scrollHeight;
  const page_key=cache.pageKey(), guards={};
  for (const a of actions) if (!(a.node in guards)) guards[a.node]=cache.guard(cache.nodes.get(a.node));
  // Compare meaning and identity. Geometry is always resolved and hit-tested just before input.
  const semantics=actions.map(({rect,...action})=>action);
  const marker=[performance.timeOrigin,location.href,scrollX,scrollY,innerWidth,innerHeight,
    document.title,text,semantics,page_key[6]];
  const omitted_actions=Math.max(0,actions.length-250);
  actions.splice(250);
  actions.forEach((a,i)=>a.id='e'+(i+1));
  if (scrollY+innerHeight<height-2) actions.push({id:'scroll_down',kind:'scroll',label:'Scroll down',delta:560});
  if (scrollY>0) actions.push({id:'scroll_up',kind:'scroll',label:'Scroll up',delta:-560});
  actions.push({id:'wait',kind:'wait',label:'Wait for the page to update'});
  return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text,
    scroll:{y:scrollY,height},actions,marker,page_key,guards,omitted_actions,
    page_risks:[...pageRiskSet]};
})()
