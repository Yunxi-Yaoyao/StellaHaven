import {it,expect} from 'vitest';
const helpers=import.meta.glob('../../shell/builtinAdminMessage.ts',{eager:true});
it('accepts management notice only from the expected origin and currently mounted iframe',()=>{
 const handler=(helpers['../../shell/builtinAdminMessage.ts'] as any)?.isBuiltinAdminNotice;
 expect(handler,'strict current-frame validator missing').toBeTypeOf('function');
 const frame=document.createElement('iframe'),old=document.createElement('iframe');document.body.append(frame,old);
 const data={type:'stella-admin-required',site:'drive',code:'admin_elevation_required',manual_retry:true};
 const event={origin:'https://stella.xiya.live',source:frame.contentWindow,data};
 expect(handler(event,frame,'https://stella.xiya.live')).toBe(true);
 expect(handler({...event,origin:'https://evil.invalid'},frame,'https://stella.xiya.live')).toBe(false);
 expect(handler({...event,source:old.contentWindow},frame,'https://stella.xiya.live')).toBe(false);
 expect(handler(event,null,'https://stella.xiya.live')).toBe(false);
 expect(handler({...event,data:{...data,manual_retry:false}},frame,'https://stella.xiya.live')).toBe(false);
 expect(handler({...event,data:{...data,code:'other_error'}},frame,'https://stella.xiya.live')).toBe(false);
 frame.remove();old.remove();
});
