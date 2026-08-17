import{o as R,w as q,c as i,a as n,b as O,v as P,F as y,r as w,d as f,t as o,e as Q,f as A,g as v,h as T,n as W,i as a,j as S,k as X}from"./index-DKuOVyg1.js";import{_ as Y}from"./_plugin-vue_export-helper-DlAUqK2U.js";const Z={class:"chat-view"},ee={class:"chat-sessions"},te={class:"chat-search"},se={class:"chat-session-list"},ne=["onClick"],le={class:"chat-session-info"},ie={class:"chat-session-title"},ae={class:"chat-session-meta"},oe={key:0,class:"chat-session-skills"},ce=["onClick"],re={key:0,style:{padding:"20px","text-align":"center",color:"var(--text-muted)","font-size":"12px"}},ue={class:"chat-area"},de={class:"chat-area-head"},ve={class:"chat-area-head-left"},he={class:"chat-area-title"},pe={key:0,class:"chat-area-skills"},fe={class:"chat-area-head-right"},me={class:"chat-bubble-wrap"},ke=["innerHTML"],_e={class:"chat-time"},ge={key:0,style:{display:"flex",flex:"1","align-items":"center","justify-content":"center",color:"var(--text-muted)",gap:"10px"}},ye={class:"chat-input-area"},we=["onKeydown"],Ce={class:"skill-picker-modal"},be={class:"skill-picker-header"},Se={class:"skill-picker-title"},xe={class:"skill-picker-body"},$e={key:0,class:"skill-picker-empty"},Ie=["onClick"],De={class:"skill-picker-check"},Me={class:"skill-picker-info"},Ae={class:"skill-picker-name"},Te={class:"skill-picker-desc"},Le={key:0,class:"skill-picker-disabled"},Ne={class:"skill-picker-footer"},ze={class:"skill-picker-count"},Ve={style:{display:"flex",gap:"8px"}},Be={__name:"ChatView",setup(He){const c=v([]),h=v(null),C=v(""),x=v(""),b=v(null),m=v(!1),$=v([]),d=v([]),_=v(null),p=T(()=>c.value.find(e=>e.id===h.value)),L=T(()=>{var e;return((e=p.value)==null?void 0:e.messages)||[]}),N=T(()=>{const e=x.value.trim().toLowerCase();return e?c.value.filter(t=>t.title.toLowerCase().includes(e)):c.value});function z(e){return e?new Date(e).toLocaleString("zh-CN",{month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}):""}function j(e){return e?e.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/```(\w*)\n([\s\S]*?)```/g,"<pre><code>$2</code></pre>").replace(/`([^`]+)`/g,"<code>$1</code>").replace(/^### (.+)$/gm,"<h3>$1</h3>").replace(/^## (.+)$/gm,"<h2>$1</h2>").replace(/^# (.+)$/gm,"<h1>$1</h1>").replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/\n/g,"<br>"):""}function I(){try{const e=localStorage.getItem("skills");e&&($.value=JSON.parse(e))}catch{}}function V(e){return d.value.some(t=>t.id===e)}function E(e){if(!e.enabled)return;const t=d.value.findIndex(l=>l.id===e.id);t>=0?d.value.splice(t,1):d.value.push({id:e.id,name:e.name,icon:e.icon,type:e.type,url:e.url})}function D(){I(),_.value=null,d.value=[],m.value=!0}function B(){const e=p.value;e&&(I(),_.value=e.id,d.value=[...e.skills||[]],m.value=!0)}function F(){if(_.value){const e=c.value.find(t=>t.id===_.value);e&&(e.skills=[...d.value],g())}else{const e=Date.now().toString();c.value.unshift({id:e,title:"新对话",time:Date.now(),messages:[],skills:[...d.value]}),h.value=e,g()}m.value=!1}function J(e){var t;confirm("确定删除该会话？")&&(c.value=c.value.filter(l=>l.id!==e),h.value===e&&(h.value=((t=c.value[0])==null?void 0:t.id)||null),g())}function K(){const e=p.value;e&&confirm("确定清空当前会话的消息记录吗？")&&(e.messages=[{role:"ai",text:"当前会话已清空，请重新输入。",time:Date.now()}],g())}function U(e,t){const l=e.toLowerCase().trim();if(/^(你好|您好|hi|hello|嗨|hey|哈喽)/i.test(l))return"你好！我是淘飞AI助手，有什么可以帮你的吗？\n\n你可以问我问题，或者使用 `@技能名` 来调用已安装的技能。";if(/^(你是谁|介绍.*自己|你叫什么)/i.test(l))return`我是**淘飞AI助手**，一个集成式的AI工作平台助手。

我可以帮助你：
- 回答问题和进行对话
- 调用已安装的技能（如代码审查、天气查询等）
- 管理和编排任务

有什么需要帮忙的？`;if(/天气|weather/i.test(l)){const u=l.match(/([\u4e00-\u9fa5]{2,})\s*天气/)||l.match(/天气.*?([\u4e00-\u9fa5]{2,})/);return`如需查询天气，请前往「集成管理 → 天气查询」页面，输入城市名即可获取实时天气数据。

当前查询城市：${u?u[1]:"北京"}
（天气数据由 Open-Meteo API 提供）`}if(/时间|几点|现在/i.test(l))return`现在是 **${new Date().toLocaleString("zh-CN",{dateStyle:"full",timeStyle:"short"})}**`;if(/谢谢|感谢|thx|thanks/i.test(l))return"不客气！有问题随时问我 😊";if(/再见|拜拜|bye/i.test(l))return"再见！期待下次与你交流 👋";if(/代码|code|bug|错误|报错/i.test(l))return t&&t.some(s=>s.name.includes("code")||s.name.includes("Code"))?`检测到你已启用 **code-reviewer** 技能。

请将需要审查的代码粘贴到对话框中，我会帮你分析代码质量、潜在问题和改进建议。`:`我可以帮你分析代码问题。请将代码粘贴到对话框中，包括错误信息（如果有）。

你也可以在「集成管理 → 技能管理」中添加 **Claude Code** 或 **code-reviewer** 技能来获得更专业的代码审查能力。`;if(/技能|skill|功能/i.test(l)){const u=t?t.length:0;if(u>0){const s=t.map(r=>`- ${r.icon||"🛠️"} ${r.name}`).join(`
`);return`当前会话已携带 **${u}** 个技能：
${s}

你可以通过对话让我调用这些技能，或在「集成管理」中管理更多技能。`}return`当前会话未携带技能。

你可以在新建会话时选择技能，或前往「集成管理 → 技能管理」添加和管理技能。

可用的技能模板包括：Claude Code、Cursor AI、GitHub Copilot、网页搜索、图片生成、PDF 解析等。`}if(/帮助|help|怎么用|使用/i.test(l))return`## 使用指南

**1. 对话交流** — 直接输入问题，我会尽力回答

**2. 技能调用** — 新建会话时选择技能，AI 会自动调用

**3. 天气查询** — 在「集成管理 → 天气查询」中查天气

**4. 技能管理** — 在「集成管理 → 技能管理」中添加/管理技能

**5. 任务编排** — 在「任务编排」中创建自动化工作流`;if(l.includes("?")||l.includes("？")||l.includes("什么")||l.includes("怎么")||l.includes("如何"))return`关于「${e}」这个问题，我的理解是：

这是一个很好的问题。目前我作为一个本地AI助手，能够处理常见的对话和任务。

如果你需要更专业的能力，建议：
- 添加相关技能（如 Claude Code 用于编程、网页搜索用于信息检索）
- 在任务编排中创建自动化流程

有什么其他问题我可以帮忙解答吗？`;const k=[`收到你的消息：「${e}」

我理解你想了解更多关于这方面的信息。请告诉我更具体的需求，我会尽力帮助你。

💡 提示：你可以使用「帮助」查看完整的使用指南。`,`关于「${e}」，我的想法是：

这取决于具体的使用场景。如果你能提供更多上下文，我可以给出更有针对性的建议。

你可以尝试：
- 输入「帮助」查看功能列表
- 输入「技能」查看可用技能
- 输入「天气 + 城市名」获取天气信息`,`这是一个有意思的话题。目前我作为本地AI助手，主要支持：

- 日常对话与问答
- 技能管理与调用
- 天气查询
- 使用指南

请告诉我你具体需要什么帮助，我会尽力协助你。`];return k[Math.floor(Math.random()*k.length)]}async function H(){const e=C.value.trim();if(!e)return;const t=p.value;if(!t){D();return}t.messages.push({role:"user",text:e,time:Date.now()}),t.title=e.slice(0,20),C.value="",await M();try{await new Promise(k=>setTimeout(k,600+Math.random()*400));const l=U(e,t.skills);t.messages.push({role:"ai",text:l,time:Date.now()}),t.time=Date.now()}catch(l){t.messages.push({role:"ai",text:"请求失败："+l.message,time:Date.now()})}g(),await M()}async function M(){await W(),b.value&&(b.value.scrollTop=b.value.scrollHeight)}function g(){localStorage.setItem("chatSessions",JSON.stringify(c.value))}function G(){var e;try{const t=localStorage.getItem("chatSessions");t&&(c.value=JSON.parse(t),h.value=((e=c.value[0])==null?void 0:e.id)||null)}catch(t){console.error("加载会话失败",t)}}return R(()=>{G(),I(),c.value.length||D()}),q(h,()=>M()),(e,t)=>{var l,k,u;return a(),i("div",Z,[n("div",ee,[n("div",{class:"chat-sessions-head"},[t[5]||(t[5]=n("h3",null,"会话列表",-1)),n("button",{class:"chat-new-btn",onClick:D},"+ 新对话")]),n("div",te,[O(n("input",{"onUpdate:modelValue":t[0]||(t[0]=s=>x.value=s),type:"text",placeholder:"搜索会话"},null,512),[[P,x.value]])]),n("div",se,[(a(!0),i(y,null,w(N.value,s=>(a(),i("div",{key:s.id,class:S(["chat-session",{active:s.id===h.value}]),onClick:r=>h.value=s.id},[n("div",le,[n("div",ie,o(s.title),1),n("div",ae,o(z(s.time))+" · "+o(s.messages.length)+" 条消息",1),s.skills&&s.skills.length?(a(),i("div",oe,[(a(!0),i(y,null,w(s.skills,r=>(a(),i("span",{key:r.id,class:"session-skill-chip"},o(r.icon||"🛠️")+" "+o(r.name),1))),128))])):f("",!0)]),n("button",{class:"chat-session-delete",onClick:A(r=>J(s.id),["stop"])},"🗑",8,ce)],10,ne))),128)),N.value.length?f("",!0):(a(),i("div",re," 暂无会话 "))])]),n("div",ue,[n("div",de,[n("div",ve,[n("span",he,o(((l=p.value)==null?void 0:l.title)||"新对话"),1),(u=(k=p.value)==null?void 0:k.skills)!=null&&u.length?(a(),i("div",pe,[(a(!0),i(y,null,w(p.value.skills,s=>(a(),i("span",{key:s.id,class:"chat-skill-tag"},o(s.icon||"🛠️")+" "+o(s.name),1))),128)),n("button",{class:"chat-skill-edit",onClick:B,title:"管理技能"},"⚙️")])):f("",!0)]),n("div",fe,[p.value?(a(),i("button",{key:0,class:"btn-ghost",onClick:B},"管理技能")):f("",!0),n("button",{class:"btn-ghost",onClick:K},"清空当前")])]),n("div",{class:"chat-messages",ref_key:"messagesEl",ref:b},[(a(!0),i(y,null,w(L.value,(s,r)=>(a(),i("div",{key:r,class:S(["chat-msg",s.role])},[n("div",{class:S(["chat-avatar",s.role])},o(s.role==="user"?"我":"AI"),3),n("div",me,[n("div",{class:"chat-bubble",innerHTML:j(s.text)},null,8,ke),n("div",_e,o(z(s.time)),1)])],2))),128)),L.value.length?f("",!0):(a(),i("div",ge,[...t[6]||(t[6]=[n("span",{style:{"font-size":"42px",opacity:".4"}},"💬",-1),n("span",null,"开始新对话",-1)])]))],512),n("div",ye,[O(n("textarea",{"onUpdate:modelValue":t[1]||(t[1]=s=>C.value=s),rows:"1",placeholder:"输入问题，例如：帮我生成一份行业调研报告…",onKeydown:Q(A(H,["exact","prevent"]),["enter"])},null,40,we),[[P,C.value]]),n("button",{class:"chat-send",onClick:H},"➤")])]),m.value?(a(),i("div",{key:0,class:"skill-picker-overlay",onClick:t[4]||(t[4]=A(s=>m.value=!1,["self"]))},[n("div",Ce,[n("div",be,[n("div",Se,o(_.value?"管理会话技能":"选择会话技能"),1),n("button",{class:"skill-picker-close",onClick:t[2]||(t[2]=s=>m.value=!1)},"✕")]),t[7]||(t[7]=n("div",{class:"skill-picker-sub"},"选择要在本次对话中携带的技能，AI 将自动调用它们",-1)),n("div",xe,[$.value.length?f("",!0):(a(),i("div",$e," 暂无可用技能，请先在「集成管理 → 技能管理」中添加 ")),(a(!0),i(y,null,w($.value,s=>(a(),i("div",{key:s.id,class:S(["skill-picker-item",{selected:V(s.id),disabled:!s.enabled}]),onClick:r=>E(s)},[n("div",De,o(V(s.id)?"✓":""),1),n("div",{class:"skill-picker-icon",style:X({background:s.color||"rgba(139, 92, 246, 0.12)"})},o(s.icon||"🛠️"),5),n("div",Me,[n("div",Ae,o(s.name),1),n("div",Te,o(s.desc),1)]),s.enabled?f("",!0):(a(),i("span",Le,"已停用"))],10,Ie))),128))]),n("div",Ne,[n("span",ze,"已选 "+o(d.value.length)+" 个技能",1),n("div",Ve,[n("button",{class:"btn-ghost",onClick:t[3]||(t[3]=s=>m.value=!1)},"取消"),n("button",{class:"btn-primary",onClick:F},"确认")])])])])):f("",!0)])}}},je=Y(Be,[["__scopeId","data-v-3069a7a2"]]);export{je as default};
