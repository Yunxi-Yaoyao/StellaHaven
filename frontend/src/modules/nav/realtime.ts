type RevisionSocket=Pick<WebSocket,'onopen'|'onmessage'|'onclose'|'onerror'|'close'>;
/** Advisory revision only; callers always perform an authenticated authoritative GET. */
export function watchNavRevision(make:()=>RevisionSocket,hint:(revision:number)=>void,status:(online:boolean)=>void){
 let active=true,socket:RevisionSocket|undefined,timer:ReturnType<typeof setTimeout>|undefined,delay=2000;
 function connect(){
  if(!active)return;
  const current=make();socket=current;
  const valid=()=>active&&socket===current;
  current.onopen=()=>{if(valid()){delay=2000;status(true);}};
  current.onmessage=e=>{if(!valid())return;try{const p=JSON.parse(String(e.data));if(p.type==='nav_revision'&&Number.isSafeInteger(p.revision)&&p.revision>=0)hint(p.revision);}catch{}};
  current.onerror=()=>{if(valid())status(false);};
  current.onclose=e=>{if(!valid())return;status(false);socket=undefined;if(e.code===1008)return;timer=setTimeout(connect,delay);delay=Math.min(30000,delay*2);};
 }
 connect();
 return ()=>{active=false;clearTimeout(timer);socket?.close();status(false);};
}
