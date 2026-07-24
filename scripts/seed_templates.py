"""Seed 6 code-builder templates for the public landing gallery.

Each is a fully working, self-contained HTML app (Tailwind + vanilla JS).
Idempotent: keyed by `slug`.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import db, now_iso

templates_col = db["builder_templates"]


TODO_HTML = '''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Minimal Todo</title><script src="https://cdn.tailwindcss.com"></script>
</head><body class="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-6">
<div class="w-full max-w-md bg-slate-900/60 backdrop-blur rounded-2xl border border-white/10 p-6 shadow-2xl">
<h1 class="text-2xl font-semibold mb-1">Today</h1>
<p class="text-sm text-slate-400 mb-4"><span id="left">0</span> left</p>
<form id="f" class="flex gap-2 mb-4"><input id="i" placeholder="Add a task…" class="flex-1 bg-slate-800/60 rounded-lg px-3 py-2 outline-none focus:ring-2 ring-indigo-400" autofocus/><button class="bg-indigo-500 hover:bg-indigo-400 rounded-lg px-3 py-2">Add</button></form>
<ul id="list" class="space-y-2"></ul></div>
<script>
const S=JSON.parse(localStorage.getItem("todo")||"[]");const $=(x)=>document.querySelector(x);
function save(){localStorage.setItem("todo",JSON.stringify(S));render();}
function render(){const u=S.filter(t=>!t.d).length;$("#left").textContent=u;
$("#list").innerHTML=S.map((t,i)=>`<li class="flex items-center gap-3 bg-slate-800/40 rounded-lg px-3 py-2"><input type="checkbox" ${t.d?"checked":""} data-i="${i}" class="w-4 h-4 accent-indigo-500"/><span class="flex-1 ${t.d?"line-through text-slate-500":""}">${t.t}</span><button data-x="${i}" class="text-slate-500 hover:text-red-400">×</button></li>`).join("");
document.querySelectorAll("[data-i]").forEach(el=>el.onchange=()=>{S[el.dataset.i].d=el.checked;save();});
document.querySelectorAll("[data-x]").forEach(el=>el.onclick=()=>{S.splice(el.dataset.x,1);save();});}
$("#f").onsubmit=(e)=>{e.preventDefault();const v=$("#i").value.trim();if(!v)return;S.unshift({t:v,d:false});$("#i").value="";save();};
render();
</script></body></html>'''


POMODORO_HTML = '''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Pomodoro</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="min-h-screen bg-gradient-to-br from-rose-900 via-slate-900 to-slate-950 text-white flex items-center justify-center p-6">
<div class="text-center space-y-6">
<div class="text-sm uppercase tracking-[0.3em] text-rose-300" id="mode">Focus</div>
<div class="text-8xl font-mono tabular-nums" id="t">25:00</div>
<div class="flex gap-3 justify-center">
<button id="s" class="px-6 py-3 rounded-full bg-white text-slate-900 font-medium hover:scale-105 transition">Start</button>
<button id="r" class="px-6 py-3 rounded-full border border-white/30 hover:bg-white/10">Reset</button>
</div>
<div class="text-sm text-slate-400">Sessions today: <span id="c">0</span></div></div>
<script>
let sec=25*60,run=false,focus=true,done=0,timer;const $=x=>document.getElementById(x);
function fmt(s){return String(s/60|0).padStart(2,"0")+":"+String(s%60).padStart(2,"0");}
function tick(){if(sec>0){sec--;$("t").textContent=fmt(sec);}else{run=false;clearInterval(timer);$("s").textContent="Start";
if(focus){done++;$("c").textContent=done;focus=false;sec=5*60;$("mode").textContent="Break";}else{focus=true;sec=25*60;$("mode").textContent="Focus";}
$("t").textContent=fmt(sec);}}
$("s").onclick=()=>{run=!run;$("s").textContent=run?"Pause":"Start";if(run)timer=setInterval(tick,1000);else clearInterval(timer);};
$("r").onclick=()=>{run=false;clearInterval(timer);sec=focus?25*60:5*60;$("t").textContent=fmt(sec);$("s").textContent="Start";};
</script></body></html>'''


CALC_HTML = '''<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Calc</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="min-h-screen bg-slate-950 text-white flex items-center justify-center p-4">
<div class="w-72 bg-slate-900 rounded-2xl p-4 shadow-2xl border border-white/10">
<div id="d" class="text-right text-3xl font-mono h-16 flex items-end justify-end pb-2 overflow-hidden">0</div>
<div class="grid grid-cols-4 gap-2 text-lg" id="g"></div></div>
<script>
const b=["C","±","%","÷","7","8","9","×","4","5","6","-","1","2","3","+","0",".","=",""];
let s="0";const $=x=>document.getElementById(x);
function upd(){$("d").textContent=s.length>12?s.slice(-12):s;}
document.getElementById("g").innerHTML=b.filter(x=>x).map((x)=>{
const op=["+","-","×","÷","="].includes(x),ac=["C","±","%"].includes(x);
return `<button data-v="${x}" class="py-3 rounded-lg ${op?"bg-orange-500 hover:bg-orange-400":ac?"bg-slate-700 hover:bg-slate-600":"bg-slate-800 hover:bg-slate-700"} ${x==="0"?"col-span-2":""}">${x}</button>`;}).join("");
document.querySelectorAll("[data-v]").forEach(el=>el.onclick=()=>{const v=el.dataset.v;
if(v==="C"){s="0";}else if(v==="±"){s=s.startsWith("-")?s.slice(1):"-"+s;}else if(v==="%"){s=(parseFloat(s)/100).toString();}
else if(v==="="){try{s=eval(s.replace(/×/g,"*").replace(/÷/g,"/")).toString();}catch(e){s="Error";}}
else{if(s==="0"&&!["+","-","×","÷","."].includes(v))s=v;else s+=v;}upd();});
</script></body></html>'''


PORTFOLIO_HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Portfolio</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-black text-white antialiased">
<nav class="fixed top-0 inset-x-0 backdrop-blur bg-black/60 border-b border-white/10 z-10"><div class="max-w-5xl mx-auto flex items-center px-6 h-14"><span class="font-semibold">alex.dev</span><div class="ml-auto flex gap-6 text-sm text-slate-400"><a href="#work" class="hover:text-white">Work</a><a href="#about" class="hover:text-white">About</a><a href="#contact" class="hover:text-white">Contact</a></div></div></nav>
<section class="min-h-[80vh] flex items-center px-6"><div class="max-w-5xl mx-auto"><p class="text-emerald-400 text-sm mb-4">// senior product engineer</p><h1 class="text-6xl md:text-7xl font-medium leading-[1.05] tracking-tight">Building calm software<br/>for anxious teams.</h1><p class="mt-6 text-slate-400 max-w-xl">I ship interfaces that feel obvious in retrospect. Currently at Stripe, previously at Linear.</p></div></section>
<section id="work" class="py-24 px-6 border-t border-white/10"><div class="max-w-5xl mx-auto"><h2 class="text-2xl mb-8">Recent work</h2><div class="grid md:grid-cols-2 gap-6">
<a class="rounded-xl border border-white/10 p-6 hover:bg-white/5"><div class="text-xs text-emerald-400 mb-2">2025 · Product</div><div class="text-xl">Zephyr — analytics for small ops teams</div><p class="text-slate-400 text-sm mt-2">Shipped v1 in 6 weeks. 12k weekly actives at launch.</p></a>
<a class="rounded-xl border border-white/10 p-6 hover:bg-white/5"><div class="text-xs text-emerald-400 mb-2">2024 · Open source</div><div class="text-xl">radix-motion — animation primitives</div><p class="text-slate-400 text-sm mt-2">4.3k stars. Used by ~200 production apps.</p></a>
</div></div></section>
<footer id="contact" class="py-16 px-6 border-t border-white/10 text-center text-slate-500 text-sm">Say hi — alex@dev.email</footer>
</body></html>'''


LANDING_HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Sprout</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-[#0b1120] text-white antialiased">
<nav class="max-w-6xl mx-auto flex items-center px-6 h-16"><span class="font-semibold text-lg">🌱 Sprout</span><div class="ml-auto flex items-center gap-6 text-sm text-slate-400"><a href="#">Features</a><a href="#">Pricing</a><a href="#">Docs</a><a href="#" class="text-white bg-emerald-500 hover:bg-emerald-400 rounded-lg px-4 py-2">Start free</a></div></nav>
<section class="py-24 px-6 text-center"><span class="inline-block px-3 py-1 rounded-full bg-emerald-500/10 text-emerald-400 text-xs border border-emerald-500/20 mb-6">v2 · Now with AI insights</span>
<h1 class="text-5xl md:text-7xl font-medium tracking-tight max-w-4xl mx-auto leading-[1.05]">The habit tracker that actually respects your time.</h1>
<p class="mt-6 text-slate-400 max-w-2xl mx-auto">A daily nudge, a weekly reflection, and zero streak-anxiety. Sprout is free forever for 3 habits.</p>
<form class="mt-10 flex max-w-md mx-auto gap-2"><input class="flex-1 bg-white/10 rounded-lg px-4 py-3 outline-none focus:ring-2 ring-emerald-400" placeholder="you@example.com"/><button class="bg-emerald-500 hover:bg-emerald-400 rounded-lg px-6 font-medium">Get invite</button></form></section>
<section class="max-w-5xl mx-auto grid md:grid-cols-3 gap-6 px-6 pb-24">
<div class="rounded-xl bg-white/5 border border-white/10 p-6"><div class="text-emerald-400 text-2xl mb-3">⚡</div><div class="font-medium mb-1">2-tap logging</div><div class="text-slate-400 text-sm">Log a habit in under a second.</div></div>
<div class="rounded-xl bg-white/5 border border-white/10 p-6"><div class="text-emerald-400 text-2xl mb-3">🌊</div><div class="font-medium mb-1">Flexible streaks</div><div class="text-slate-400 text-sm">Miss a day? No shame. Sprout adjusts.</div></div>
<div class="rounded-xl bg-white/5 border border-white/10 p-6"><div class="text-emerald-400 text-2xl mb-3">📈</div><div class="font-medium mb-1">Weekly AI review</div><div class="text-slate-400 text-sm">Gentle patterns spotted by AI, not shamed.</div></div>
</section>
</body></html>'''


WEATHER_HTML = '''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"/><title>Weather</title><script src="https://cdn.tailwindcss.com"></script></head>
<body class="bg-gradient-to-br from-sky-500 via-sky-700 to-indigo-900 text-white min-h-screen flex items-center justify-center p-6">
<div class="w-full max-w-sm bg-white/10 backdrop-blur-lg rounded-3xl border border-white/20 p-8 shadow-2xl text-center">
<div class="text-slate-200 text-sm mb-1" id="loc">Bengaluru</div>
<div class="text-8xl font-thin mt-2" id="temp">28°</div>
<div class="text-lg mb-6" id="desc">Partly cloudy</div>
<div class="text-6xl mb-6" id="ic">⛅</div>
<div class="grid grid-cols-4 gap-2 text-xs text-slate-200" id="week"></div></div>
<script>
const days=["Mon","Tue","Wed","Thu"],icons=["☀️","⛅","🌤️","🌦️"],temps=[29,27,30,26];
document.getElementById("week").innerHTML=days.map((d,i)=>`<div class="bg-white/10 rounded-xl p-3"><div>${d}</div><div class="text-2xl my-1">${icons[i]}</div><div class="text-white text-sm">${temps[i]}°</div></div>`).join("");
</script></body></html>'''


TEMPLATES = [
    {"slug": "todo", "name": "Minimalist Todo", "description": "Tap-to-add, persists via localStorage. Perfect starter.", "order": 1, "language": "html",
     "files": [{"path": "index.html", "content": TODO_HTML, "language": "html"}]},
    {"slug": "pomodoro", "name": "Pomodoro Focus Timer", "description": "25/5 work-break cycle with focus counter.", "order": 2, "language": "html",
     "files": [{"path": "index.html", "content": POMODORO_HTML, "language": "html"}]},
    {"slug": "calculator", "name": "iOS-style Calculator", "description": "Neumorphic calculator with keyboard-friendly layout.", "order": 3, "language": "html",
     "files": [{"path": "index.html", "content": CALC_HTML, "language": "html"}]},
    {"slug": "portfolio", "name": "Dev Portfolio", "description": "Minimal single-page portfolio for software engineers.", "order": 4, "language": "html",
     "files": [{"path": "index.html", "content": PORTFOLIO_HTML, "language": "html"}]},
    {"slug": "landing", "name": "SaaS Landing Page", "description": "Hero + features + email capture. Ready to ship.", "order": 5, "language": "html",
     "files": [{"path": "index.html", "content": LANDING_HTML, "language": "html"}]},
    {"slug": "weather", "name": "Weather Card", "description": "Glass-morphism weather widget with 4-day forecast.", "order": 6, "language": "html",
     "files": [{"path": "index.html", "content": WEATHER_HTML, "language": "html"}]},
]


async def seed():
    for t in TEMPLATES:
        t["updated_at"] = now_iso()
        await templates_col.update_one(
            {"slug": t["slug"]},
            {"$set": t, "$setOnInsert": {"created_at": now_iso()}},
            upsert=True,
        )
    print(f"Seeded {len(TEMPLATES)} builder templates.")


async def main():
    await seed()


if __name__ == "__main__":
    asyncio.run(main())
