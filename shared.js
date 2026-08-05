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
