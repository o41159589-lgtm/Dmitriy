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
