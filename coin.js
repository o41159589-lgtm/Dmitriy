// Новая монета: заменяет эмодзи 🪙 на картинку textures/coin.webp везде (и в динамически создаваемом тексте).
(function(){
  const SRC='textures/coin.webp',COIN='\u{1FA99}';
  const st=document.createElement('style');
  st.textContent='.coin-emoji{display:inline-block;width:1.1em;height:1.1em;vertical-align:-0.22em;margin:0 .05em;object-fit:contain;-webkit-user-drag:none;user-select:none}';
  (document.head||document.documentElement).appendChild(st);
  const SKIP={SCRIPT:1,STYLE:1,TEXTAREA:1,OPTION:1,TITLE:1,NOSCRIPT:1};
  function rep(n){
    if(!n.parentNode||SKIP[n.parentNode.nodeName]||n.nodeValue.indexOf(COIN)<0)return;
    const parts=n.nodeValue.split(COIN),frag=document.createDocumentFragment();
    parts.forEach((t,i)=>{
      if(t)frag.appendChild(document.createTextNode(t));
      if(i<parts.length-1){const im=document.createElement('img');im.src=SRC;im.className='coin-emoji';im.alt='';im.draggable=false;frag.appendChild(im);}
    });
    n.parentNode.replaceChild(frag,n);
  }
  function walk(root){
    if(!root)return;
    if(root.nodeType===3){rep(root);return;}
    if(root.nodeType!==1)return;
    const tw=document.createTreeWalker(root,NodeFilter.SHOW_TEXT,{acceptNode:n=>(!SKIP[n.parentNode&&n.parentNode.nodeName]&&n.nodeValue.indexOf(COIN)>=0)?NodeFilter.FILTER_ACCEPT:NodeFilter.FILTER_REJECT});
    const list=[];while(tw.nextNode())list.push(tw.currentNode);list.forEach(rep);
  }
  let queue=new Set(),scheduled=false;
  function flush(){scheduled=false;const q=queue;queue=new Set();q.forEach(walk);}
  function init(){
    walk(document.body);
    new MutationObserver(ms=>{
      for(const m of ms){
        if(m.type==='characterData')queue.add(m.target);
        else m.addedNodes.forEach(n=>queue.add(n));
      }
      if(!scheduled){scheduled=true;requestAnimationFrame(flush);}
    }).observe(document.body,{childList:true,subtree:true,characterData:true});
  }
  if(document.body)init();else document.addEventListener('DOMContentLoaded',init);
})();
