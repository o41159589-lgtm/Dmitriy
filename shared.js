// TopLuck — shared helpers
// Redirects a banned user to banned.html with their ban reason.
// Call right after fetching /api/user/{uid} (or getting a 403 "banned" error from any action).
// Returns true if the user was redirected (caller should stop further execution).
function TL_guardBanned(user){
  if(user && user.banned){
    const reason = encodeURIComponent(user.ban_reason || '');
    location.replace('banned.html' + (reason ? ('?reason=' + reason) : ''));
    return true;
  }
  return false;
}

// Polls the server every `intervalMs` while the user is on a game/other page.
// If they get banned mid-session (even without doing anything), they're bounced
// to main.html first — which itself detects the ban and forwards to banned.html.
// This avoids duplicating the reason-lookup/redirect logic on every single page.
function TL_startBanPoll(uid, intervalMs){
  if(!uid) return;
  intervalMs = intervalMs || 8000;
  setInterval(async ()=>{
    try{
      const u = await fetch('/api/user/'+uid).then(r=>r.json());
      if(u && u.banned){ location.replace('main.html'); }
    }catch(e){ /* ignore transient network errors */ }
  }, intervalMs);
}

// ── TopLuck loading animation: two googly eyes tracking a wandering dot ──
// Pure JS + requestAnimationFrame (no video, no per-frame network/DOM thrash).
// Loops forever until .stop() is called. Use anywhere a loading state is shown
// (shop gift list, admin panel splash, etc.) instead of a static logo/spinner.
//   const loader = TL_mountEyesLoader(document.getElementById('my-container'));
//   ...later: loader.stop();
function TL_mountEyesLoader(container, opts){
  opts = opts || {};
  const W = opts.width || 220, H = opts.height || 130;
  const eyeR = opts.eyeR || 30, pupilR = opts.pupilR || 12, gap = opts.gap || 16;
  const cx = W/2, ey = H/2 + 4;
  const leftPos  = {x: cx - eyeR - gap/2, y: ey};
  const rightPos = {x: cx + eyeR + gap/2, y: ey};

  container.innerHTML = '';
  container.style.cssText = `position:relative;width:${W}px;height:${H}px;margin:0 auto;overflow:visible;`;

  function mkEye(pos){
    const eye = document.createElement('div');
    eye.style.cssText = `position:absolute;left:${pos.x-eyeR}px;top:${pos.y-eyeR}px;width:${eyeR*2}px;height:${eyeR*2}px;
      border-radius:50%;background:#fff;box-shadow:0 4px 14px rgba(20,40,90,.18);transform-origin:center;`;
    const pupil = document.createElement('div');
    pupil.style.cssText = `position:absolute;left:50%;top:50%;width:${pupilR*2}px;height:${pupilR*2}px;
      margin:${-pupilR}px 0 0 ${-pupilR}px;border-radius:50%;background:${opts.pupilColor||'#1A2040'};`;
    eye.appendChild(pupil);
    container.appendChild(eye);
    return {eye, pupil, pos};
  }
  const eyes = [mkEye(leftPos), mkEye(rightPos)];

  const dot = document.createElement('div');
  dot.style.cssText = `position:absolute;width:15px;height:15px;border-radius:50%;
    background:${opts.dotColor||'#FFD400'};box-shadow:0 0 10px rgba(255,212,0,.7);opacity:0;`;
  container.appendChild(dot);

  // Path the dot follows over one full loop (fractions of the cycle). Kept well
  // clear of both eye circles at all times — it passes near, never touches.
  const path = [
    {t:0.00, x:cx,      y:ey,    vis:0},
    {t:0.08, x:W+12,    y:6,     vis:0},
    {t:0.11, x:W-8,     y:4,     vis:1},
    {t:0.22, x:cx+42,   y:-4,    vis:1},
    {t:0.32, x:cx,      y:-10,   vis:1},
    {t:0.40, x:cx-42,   y:0,     vis:1},
    {t:0.46, x:cx,      y:-14,   vis:1},   // closest pass — directly above the gap, never touching
    {t:0.54, x:cx+70,   y:-26,   vis:1},   // starts accelerating away
    {t:0.60, x:W+40,    y:16,    vis:1},   // fast outward swirl
    {t:0.65, x:W+14,    y:H+14,  vis:1},
    {t:0.70, x:cx,      y:H+18,  vis:1},
    {t:0.75, x:cx,      y:ey,    vis:1},
    {t:0.79, x:cx,      y:ey,    vis:0},
    {t:1.00, x:cx,      y:ey,    vis:0},
  ];
  function smoothstep(a,b,t){ return a + (b-a) * (t*t*(3-2*t)); }
  function samplePath(frac){
    for(let i=0;i<path.length-1;i++){
      const a=path[i], b=path[i+1];
      if(frac>=a.t && frac<=b.t){
        const local=(frac-a.t)/((b.t-a.t)||1);
        return {x:smoothstep(a.x,b.x,local), y:smoothstep(a.y,b.y,local), vis:smoothstep(a.vis,b.vis,local)};
      }
    }
    return {x:cx, y:ey, vis:0};
  }

  // Blinks: one at rest, one exactly at the closest pass, two near the end.
  const blinkTimes = [0.03, 0.46, 0.85, 0.91];
  function blinkEnvelope(frac, cycle){
    let env = 0;
    for(const bt of blinkTimes){
      let dt = Math.min(Math.abs(frac-bt), Math.abs(frac-bt-1), Math.abs(frac-bt+1)) * cycle;
      if(dt < 120){ env = Math.max(env, 1 - dt/120); }
    }
    return env;
  }

  const CYCLE = opts.cycle || 8200;
  let startTs = null, raf = null, stopped = false;
  function frame(ts){
    if(stopped) return;
    if(startTs===null) startTs = ts;
    const frac = ((ts-startTs) % CYCLE) / CYCLE;
    const p = samplePath(frac);

    dot.style.left = (p.x - 7.5) + 'px';
    dot.style.top  = (p.y - 7.5) + 'px';
    dot.style.opacity = p.vis;

    // Track more intently (bigger pupil deflection) right as the dot passes closest overhead
    const boost = (frac>0.40 && frac<0.52) ? 1.3 : 1;

    eyes.forEach(({pupil,pos})=>{
      const dx=p.x-pos.x, dy=p.y-pos.y;
      const dist=Math.hypot(dx,dy) || 1;
      const maxOff=(eyeR-pupilR-4)*boost;
      const off=Math.min(maxOff, dist*0.22*boost);
      pupil.style.transform = `translate(${(dx/dist)*off*p.vis}px, ${(dy/dist)*off*p.vis}px)`;
    });

    const blink = blinkEnvelope(frac, CYCLE);
    eyes.forEach(({eye})=>{ eye.style.transform = `scaleY(${1-blink*0.85})`; });

    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);
  return { stop(){ stopped=true; if(raf) cancelAnimationFrame(raf); } };
}
