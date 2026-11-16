(() => {
  const P='\u2063',S='\u2064',V=0xFE00,STORE='wathiq.translationInspector.enabled',POSITION_STORE='wathiq.translationInspector.position';
  const ATTR=['aria-label','title','placeholder'];
  const state={authorized:false,enabled:false,pinned:null,active:null,highlighted:null,panel:null,labels:{},listening:false};
  const textData=new WeakMap(),attrData=new WeakMap(),entriesByElement=new WeakMap();
  const selectorHex=s=>[...s].map(c=>(c.codePointAt(0)-V).toString(16)).join('');
  function key(s){const h=selectorHex(s),p=h.match(/.{2}/g);return p?new TextDecoder().decode(new Uint8Array(p.map(x=>parseInt(x,16)))):'';}
  function parse(value){
    if(typeof value!=='string'||!value.includes(P))return{value,entries:[]};
    let at=0,out='';const entries=[];
    while(at<value.length){const a=value.indexOf(P,at);if(a<0){out+=value.slice(at);break;}out+=value.slice(at,a);
      const b=value.indexOf(S,a+1),c=b<0?-1:value.indexOf(S,b+1),d=c<0?-1:value.indexOf(S,c+1);
      if(b<0||c<0||d<0){out+=value.slice(a);break;}
      try{const k=key(value.slice(a+1,b)),n=parseInt(selectorHex(value.slice(c+1,d)),16),rest=value.slice(d+1),rendered=[...rest].slice(0,n).join('');
        if(!k||!Number.isSafeInteger(n)||[...rendered].length!==n)throw Error();out+=rendered;entries.push({key:k,fallback:value.codePointAt(b+1)===V+1,rendered});at=d+1+rendered.length;
      }catch(_){out+=P;at=a+1;}}
    return{value:out,entries};
  }
  function refresh(el){if(!(el instanceof Element))return;const all=[];for(const n of el.childNodes)if(n.nodeType===3)all.push(...(textData.get(n)?.entries||[]));for(const a of (attrData.get(el)||new Map()).values())all.push(...a.entries);
    const unique=all.filter((x,i)=>all.findIndex(y=>y.key===x.key&&y.rendered===x.rendered&&y.fallback===x.fallback)===i);
    if(unique.length){entriesByElement.set(el,unique);el.dataset.i18nKey=unique[0].key;}else{entriesByElement.delete(el);delete el.dataset.i18nKey;}}
  function skipped(n) {
    const element = n instanceof Element ? n : n.parentElement;
    return !!element?.closest('#wathiq-translation-inspector,script,style');
  }
  function scanText(node) {
    const original = node.nodeValue;
    const p = parse(original);
    const previous = textData.get(node);
    if(p.entries.length||!previous||previous.value!==p.value)textData.set(node,p);
    if (p.value !== original) node.nodeValue = p.value;
    refresh(node.parentElement);
  }
  function scanAttributes(element) {
    for (const name of ATTR) {
      let attributes = attrData.get(element);
      if (!element.hasAttribute(name)) {
        attributes?.delete(name);
        continue;
      }
      const original = element.getAttribute(name);
      const p = parse(original);
      const previous = attributes?.get(name);
      if (p.entries.length || previous) {
        if (!attributes) {
          attributes = new Map();
          attrData.set(element, attributes);
        }
        if (p.entries.length || previous.value !== p.value) attributes.set(name, p);
      }
      if (p.value !== original) element.setAttribute(name, p.value);
    }
    refresh(element);
  }
  function scan(root) {
    if (skipped(root)) return;
    if (root.nodeType === Node.TEXT_NODE) {
      scanText(root);
      return;
    }
    if (!(root instanceof Element)) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
      acceptNode: node => skipped(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
    });
    scanAttributes(root);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (node.nodeType === Node.TEXT_NODE) scanText(node);
      else scanAttributes(node);
    }
  }
  function place(p,left,top){const margin=8,maxLeft=Math.max(margin,innerWidth-p.offsetWidth-margin),maxTop=Math.max(margin,innerHeight-p.offsetHeight-margin);p.style.inset='auto';p.style.left=`${Math.min(Math.max(margin,left),maxLeft)}px`;p.style.top=`${Math.min(Math.max(margin,top),maxTop)}px`;}
  function restorePosition(p){try{const saved=JSON.parse(sessionStorage.getItem(POSITION_STORE)||'null');if(saved&&Number.isFinite(saved.left)&&Number.isFinite(saved.top))place(p,saved.left,saved.top);}catch(_){sessionStorage.removeItem(POSITION_STORE);}}
  function makeMovable(p){const h=p.querySelector('.wathiq-i18n-panel-header');let drag=null;h.addEventListener('pointerdown',e=>{if(e.button!==0||e.target.closest('button,select,input,a'))return;const r=p.getBoundingClientRect();drag={x:e.clientX-r.left,y:e.clientY-r.top};h.setPointerCapture(e.pointerId);h.classList.add('is-dragging');e.preventDefault();});h.addEventListener('pointermove',e=>{if(drag)place(p,e.clientX-drag.x,e.clientY-drag.y);});const finish=e=>{if(!drag)return;drag=null;h.classList.remove('is-dragging');const r=p.getBoundingClientRect();sessionStorage.setItem(POSITION_STORE,JSON.stringify({left:r.left,top:r.top}));if(h.hasPointerCapture(e.pointerId))h.releasePointerCapture(e.pointerId);};h.addEventListener('pointerup',finish);h.addEventListener('pointercancel',finish);addEventListener('resize',()=>{if(p.style.left){const r=p.getBoundingClientRect();place(p,r.left,r.top);}});}
  function panel(){if(state.panel)return state.panel;const p=document.createElement('aside');p.id='wathiq-translation-inspector';p.className='wathiq-translation-inspector';p.role='complementary';p.ariaLive='off';p.dataset.inspectorIgnore='true';p.innerHTML='<div class="wathiq-i18n-panel-header"><strong class="wathiq-i18n-panel-title" data-x="title"></strong><span class="wathiq-i18n-panel-actions"><button data-a="copy">content_copy</button><button data-a="open">open_in_new</button></span></div><select data-x="keys" dir="ltr"></select><dl><div><dt data-x="ll"></dt><dd data-x="lang"></dd></div><div><dt data-x="fl"></dt><dd data-x="fallback"></dd></div></dl><div class="wathiq-i18n-rendered" data-x="rendered"></div><div class="wathiq-i18n-panel-guidance" data-x="guide"></div>';p.hidden=true;
    p.addEventListener('click',async e=>{const a=e.target.closest?.('[data-a]')?.dataset.a;if(!a)return;e.stopPropagation();const x=current();if(!x)return;if(a==='copy'){try{await navigator.clipboard.writeText(x.key);}catch(_){}}else{const b=document.getElementById('translation-inspector-bridge');if(b){b.dataset.translationKey=x.key;b.click();}}});p.querySelector('select').onchange=update;document.body.appendChild(p);makeMovable(p);return state.panel=p;}
  const list=()=>state.active?(entriesByElement.get(state.active)||[]):[];const current=()=>list()[+(panel().querySelector('select').value||0)];
  function update(){const p=panel(),x=current();p.querySelector('[data-x=lang]').textContent=document.documentElement.lang||'en';p.querySelector('[data-x=fallback]').textContent=x?.fallback?state.labels.yes:state.labels.no;p.querySelector('[data-x=rendered]').textContent=x?.rendered||'';}
  function show(target){const p=panel();if(!state.enabled){p.hidden=true;state.highlighted?.classList.remove('wathiq-i18n-inspected');state.highlighted=null;return;}if(target===state.active&&!p.hidden)return;state.active=target;p.hidden=false;if(!p.dataset.positionRestored){restorePosition(p);p.dataset.positionRestored='true';}state.highlighted?.classList.remove('wathiq-i18n-inspected');state.highlighted=target;target?.classList.add('wathiq-i18n-inspected');p.querySelector('[data-x=title]').textContent=state.labels.title||'';p.querySelector('[data-x=ll]').textContent=state.labels.language||'';p.querySelector('[data-x=fl]').textContent=state.labels.fallback||'';p.querySelector('[data-x=guide]').textContent=target?state.labels.clickGuidance:state.labels.guidance;const s=p.querySelector('select');s.replaceChildren(...list().map((x,i)=>{const o=document.createElement('option');o.value=i;o.textContent=x.key;return o;}));s.hidden=!target;for(const b of p.querySelectorAll('[data-a]')){b.hidden=!target;const l=b.dataset.a==='copy'?state.labels.copy:state.labels.open;b.title=l;b.ariaLabel=l;}update();}
  const candidate=e=>{const o=e.target instanceof Element?e.target:e.target?.parentElement;return o?.closest('[data-inspector-ignore]')?null:o?.closest('[data-i18n-key]')||null;};
  const handlers={over:e=>{if(!state.pinned&&!e.target?.closest?.('#wathiq-translation-inspector'))show(candidate(e));},out:e=>{if(!state.pinned&&!e.relatedTarget?.closest?.('#wathiq-translation-inspector'))show(e.relatedTarget instanceof Element?e.relatedTarget.closest('[data-i18n-key]'):null);},focus:e=>{if(!state.pinned)show(candidate(e));},blur:e=>{if(!state.pinned&&!e.relatedTarget?.closest?.('#wathiq-translation-inspector'))show(e.relatedTarget instanceof Element?e.relatedTarget.closest('[data-i18n-key]'):null);},click:e=>{if(!e.target?.closest?.('#wathiq-translation-inspector')){const t=candidate(e);if(t){e.preventDefault();e.stopPropagation();state.pinned=t;show(t);}}},key:e=>{if(e.key==='Escape'){state.pinned=null;show(null);}}};
  const events=[['pointerover','over'],['pointerout','out'],['focusin','focus'],['focusout','blur'],['click','click'],['keydown','key']];function listen(on){if(on===state.listening)return;for(const [e,h] of events)document[on?'addEventListener':'removeEventListener'](e,handlers[h],true);state.listening=on;}
  const observer = new MutationObserver(records => {
    const added = new Set();
    for (const record of records) {
      if (skipped(record.target)) continue;
      if (record.type === 'childList') {
        for (const node of record.addedNodes) added.add(node);
        if (record.removedNodes.length) refresh(record.target);
      } else if (record.type === 'attributes') {
        scanAttributes(record.target);
      } else {
        scanText(record.target);
      }
    }
    for (const node of added) {
      if (node.isConnected && !added.has(node.parentNode)) scan(node);
    }
    if (state.pinned && !state.pinned.isConnected) {
      state.pinned = null;
      show(null);
    }
  });
  window.wathiqTranslationInspector={initialize(labels){state.labels={...labels};panel();return true;},
    setAuthorized(value) {
      if (state.authorized === !!value) return state.authorized;
      state.authorized = !!value;
      if (state.authorized) {
        // Collect and remove transport markers even while inspection is switched off.
        scan(document.documentElement);
        observer.observe(document.documentElement, {
          subtree:true, childList:true, characterData:true, attributes:true, attributeFilter:ATTR,
        });
      } else {
        observer.disconnect();
        this.setEnabled(false);
      }
      return state.authorized;
    },
    setEnabled(v){state.enabled=state.authorized&&!!v;state.pinned=null;state.active=null;state.enabled?sessionStorage.setItem(STORE,'true'):sessionStorage.removeItem(STORE);listen(state.enabled);show(null);return state.enabled;},
    restore(){return this.setEnabled(state.authorized&&sessionStorage.getItem(STORE)==='true');},
    clearSession(){sessionStorage.removeItem(STORE);return this.setAuthorized(false);}
  };
})();
