/* Lumen learning-library — interactive wiring (interactive-light v1).
   Inlined into every built page. All features guarded: absent elements => no-op (index page reuses this file). */
(function(){
  "use strict";

  /* reading-progress bar + topic progress */
  var bar=document.getElementById('bar'), tp=document.getElementById('tprog');
  if(bar||tp){
    var onScroll=function(){var h=document.documentElement, p=h.scrollTop/((h.scrollHeight-h.clientHeight)||1);
      if(bar) bar.style.width=(p*100)+'%'; if(tp) tp.style.width=Math.min(100,p*115)+'%';};
    addEventListener('scroll',onScroll,{passive:true}); onScroll();
  }

  /* collapsible sections */
  document.querySelectorAll('.sechead').forEach(function(h){
    h.addEventListener('click',function(){var it=h.closest('.item'); var c=it.classList.toggle('collapsed'); h.setAttribute('aria-expanded',String(!c));});
  });

  /* auto table-of-contents + scroll-spy (density-adaptive: reads however many sections exist) */
  var secs=[].slice.call(document.querySelectorAll('.main .item[id]')), toc=document.getElementById('toc');
  if(toc && secs.length){
    var links={};
    secs.forEach(function(s){
      var a=document.createElement('a'); a.href='#'+s.id;
      a.textContent=s.getAttribute('data-toc')|| (s.querySelector('h2')?s.querySelector('h2').textContent:s.id);
      a.addEventListener('click',function(e){e.preventDefault(); s.scrollIntoView({behavior:'smooth',block:'start'});});
      toc.appendChild(a); links[s.id]=a;
    });
    if('IntersectionObserver' in window){
      var spy=new IntersectionObserver(function(es){es.forEach(function(en){
        if(en.isIntersecting){for(var k in links) links[k].classList.remove('on'); if(links[en.target.id]) links[en.target.id].classList.add('on');}
      });},{rootMargin:'-25% 0px -65% 0px'});
      secs.forEach(function(s){spy.observe(s);});
    }
  }

  /* interactive graph -> detail panel */
  document.querySelectorAll('.igraph').forEach(function(g){
    var detail=g.parentNode.querySelector('.detail')||document.querySelector('.detail');
    function pick(el){
      g.querySelectorAll('.inode.sel,.iedge.sel').forEach(function(e){e.classList.remove('sel');});
      el.classList.add('sel');
      if(detail){detail.classList.remove('empty');
        detail.innerHTML='<span class="badge">'+el.getAttribute('data-kind')+'</span><h4>'+el.getAttribute('data-title')+'</h4><p>'+el.getAttribute('data-desc')+'</p>';}
    }
    g.querySelectorAll('.inode,.iedge').forEach(function(el){
      el.addEventListener('click',function(){pick(el);});
      el.addEventListener('keydown',function(e){if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(el);}});
    });
  });

  /* glossary terms show their plain-language definition via a CSS hover/focus tooltip
     (.gloss::after = attr(data-def)) — no JS needed; works for prose + the graph detail panel. */

  /* step-through (GraphRAG-style). Reads steps from a JSON script tag if present. */
  document.querySelectorAll('.stepper').forEach(function(st){
    var dataEl=st.querySelector('script[type="application/json"]'); if(!dataEl) return;
    var steps; try{steps=JSON.parse(dataEl.textContent);}catch(e){return;}
    var cap=st.querySelector('.stepcap'), pos=st.querySelector('.pos'), sgs=[].slice.call(st.querySelectorAll('.sg')), i=0;
    function draw(){sgs.forEach(function(g){g.classList.toggle('on', (+g.getAttribute('data-i'))<=i);});
      if(cap) cap.innerHTML='<b>'+steps[i][0]+'</b> '+steps[i][1]; if(pos) pos.textContent=(i+1)+' / '+steps.length;}
    var nx=st.querySelector('.s-next'), pv=st.querySelector('.s-prev');
    if(nx) nx.addEventListener('click',function(){i=(i+1)%steps.length;draw();});
    if(pv) pv.addEventListener('click',function(){i=(i+steps.length-1)%steps.length;draw();});
    sgs.forEach(function(g){g.addEventListener('click',function(){i=+g.getAttribute('data-i');draw();});});
    draw();
  });

  /* quiz */
  document.querySelectorAll('.quiz').forEach(function(q){
    var fb=q.querySelector('.fb');
    q.querySelectorAll('.opt').forEach(function(o){
      o.addEventListener('click',function(){
        var ok=o.getAttribute('data-ok')==='1'; o.classList.add(ok?'right':'wrong');
        if(fb) fb.innerHTML=ok?('✓ '+(o.getAttribute('data-fb')||'Correct.')):('Not quite — '+(o.getAttribute('data-fb')||'try another.'));
      });
    });
  });

  /* inline tabs — switch which panel shows WITHIN each .tabs container only. Every query is
     scoped to its container `t`, so multiple tabs blocks on one page never cross-wire. Guarded:
     no .tabs => no-op (index page reuses this file). */
  document.querySelectorAll('.tabs').forEach(function(t){
    var btns=[].slice.call(t.querySelectorAll('.tab-btn')), panels=[].slice.call(t.querySelectorAll('.tab-panel'));
    btns.forEach(function(b){
      b.addEventListener('click',function(){
        var k=b.getAttribute('data-tab');
        btns.forEach(function(x){var on=x.getAttribute('data-tab')===k; x.classList.toggle('active',on); x.setAttribute('aria-selected',String(on));});
        panels.forEach(function(p){p.classList.toggle('on',p.getAttribute('data-tab')===k);});
      });
    });
  });

  /* shared wide modal — ONE generic handler for every block. Any element with class
     js-modal-open and attribute data-modal-src="<hidden-id>" fills .lib-modal-body from that
     hidden element's innerHTML (trace View I/O, code Expand, diagram Zoom all use this).
     Close on ×, on scrim, on Escape. Guarded: no #libModal => no-op (index page reuses this). */
  var libModal=document.getElementById('libModal');
  if(libModal){
    var mBody=libModal.querySelector('.lib-modal-body');
    var closeModal=function(){libModal.setAttribute('hidden','');};
    document.querySelectorAll('.js-modal-open').forEach(function(b){
      b.addEventListener('click',function(){var src=document.getElementById(b.getAttribute('data-modal-src'));
        if(src&&mBody){mBody.innerHTML=src.innerHTML; libModal.removeAttribute('hidden');}});
    });
    var mx=libModal.querySelector('.lib-modal-x'), msc=libModal.querySelector('.lib-modal-scrim');
    if(mx) mx.addEventListener('click',closeModal);
    if(msc) msc.addEventListener('click',closeModal);
    addEventListener('keydown',function(e){if(e.key==='Escape'&&!libModal.hasAttribute('hidden'))closeModal();});
  }

  /* hover-to-copy: builds a PRECISE /sb-tutor expand prompt — page-source filepath + section anchor-id + title */
  var toast=document.getElementById('toast'), TOPIC=document.body.getAttribute('data-topic')||'', SOURCE=document.body.getAttribute('data-source')||'';
  function copyText(t){
    if(navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
    return new Promise(function(res,rej){var ta=document.createElement('textarea'); ta.value=t; ta.style.position='fixed'; ta.style.opacity='0';
      document.body.appendChild(ta); ta.focus(); ta.select(); try{document.execCommand('copy'); res();}catch(e){rej(e);} document.body.removeChild(ta);});
  }

  /* code-block Copy — copies the adjacent visible <pre.code> text via copyText + toast (guarded) */
  document.querySelectorAll('.js-copy').forEach(function(b){
    b.addEventListener('click',function(){var wrap=b.closest('.codewrap'), pre=wrap&&wrap.querySelector('pre.code');
      if(!pre) return;
      copyText(pre.textContent).then(function(){b.innerHTML='✓ copied';
        if(toast){toast.textContent='code copied'; toast.classList.add('show');}
        setTimeout(function(){b.innerHTML='⧉ Copy'; if(toast) toast.classList.remove('show');},1500);});
    });
  });

  document.querySelectorAll('.main .item').forEach(function(el){
    var b=document.createElement('button'); b.className='copybtn'; b.type='button'; b.textContent='⧉ copy';
    b.setAttribute('aria-label','Copy a /sb-tutor prompt to expand this item');
    b.addEventListener('click',function(e){e.stopPropagation();
      var item=el.getAttribute('data-item')|| (el.querySelector('h2')?el.querySelector('h2').textContent.trim():'');
      var anchor=el.id||'';
      var txt='/sb-tutor expand the item ['+item+'] of the topic ['+TOPIC+'] (source: '+SOURCE+', section: #'+anchor+'). ';
      copyText(txt).then(function(){b.textContent='✓ copied';
        if(toast){toast.textContent='copied: '+txt.slice(0,46)+'…'; toast.classList.add('show');}
        setTimeout(function(){b.textContent='⧉ copy'; if(toast) toast.classList.remove('show');},1700);});
    });
    el.appendChild(b);
  });
})();
