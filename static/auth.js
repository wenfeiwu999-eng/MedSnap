(function(){
"use strict";
function initAuthBar(){
fetch("/api/auth/me").then(function(r){return r.json()}).then(function(data){
if(data.status!=="success"){window.location.href="/login";return}
renderAuthBar(data.user);
}).catch(function(){window.location.href="/login"});}
function renderAuthBar(user){
var bar=document.createElement("div");
bar.id="medsnap-auth-bar";
bar.style.cssText="position:fixed;top:0;right:0;z-index:9997;display:flex;align-items:center;gap:12px;padding:8px 20px;background:rgba(30,64,175,0.85);backdrop-filter:blur(8px);border-radius:0 0 0 12px;font-size:13px;color:white;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;";
var nameSpan=document.createElement("span");
nameSpan.textContent=user.display_name||user.username||"用户";
nameSpan.style.cssText="font-weight:600;";
bar.appendChild(nameSpan);
if(user.role==="admin"){
var adminBtn=document.createElement("a");
adminBtn.href="/admin";
adminBtn.textContent="管理后台";
adminBtn.style.cssText="padding:4px 12px;border:1px solid rgba(255,255,255,0.4);border-radius:6px;background:transparent;color:white;font-size:12px;cursor:pointer;text-decoration:none;transition:background 0.2s;";
adminBtn.onmouseenter=function(){this.style.background="rgba(255,255,255,0.15)"};
adminBtn.onmouseleave=function(){this.style.background="transparent"};
bar.appendChild(adminBtn);}
var logoutBtn=document.createElement("button");
logoutBtn.textContent="退出";
logoutBtn.style.cssText="padding:4px 12px;border:1px solid rgba(255,255,255,0.4);border-radius:6px;background:transparent;color:white;font-size:12px;cursor:pointer;transition:background 0.2s;";
logoutBtn.onmouseenter=function(){this.style.background="rgba(255,255,255,0.15)"};
logoutBtn.onmouseleave=function(){this.style.background="transparent"};
logoutBtn.onclick=function(){fetch("/api/auth/logout",{method:"POST"}).then(function(){window.location.href="/login"}).catch(function(){window.location.href="/login"})};
bar.appendChild(logoutBtn);document.body.appendChild(bar);}
if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",initAuthBar)}else{initAuthBar()}
})();
