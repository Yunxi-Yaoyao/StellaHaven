/** Optional parent UI hook. Never replays a request or grants management access. */
export function isBuiltinAdminNotice(event:Pick<MessageEvent,'origin'|'source'|'data'>,currentFrame:HTMLIFrameElement|null,expectedOrigin:string):boolean {
 if(!currentFrame?.contentWindow||event.source!==currentFrame.contentWindow||event.origin!==expectedOrigin)return false;
 const value=event.data;
 return !!value&&typeof value==='object'&&value.type==='stella-admin-required'&&value.site==='drive'&&value.manual_retry===true&&typeof value.code==='string'&&/^admin_[a-z_]{1,80}$/.test(value.code);
}
