type KeyCrypto={randomUUID?:()=>string;getRandomValues:(array:Uint8Array<ArrayBuffer>)=>Uint8Array<ArrayBuffer>};
/** Idempotency identity, not an authentication token. HTTP LAN exposes
 * getRandomValues but may not expose secure-context-only randomUUID. */
export function websiteSaveKey(source:KeyCrypto=globalThis.crypto):string {
 if(typeof source.randomUUID==='function')return source.randomUUID();
 const bytes=source.getRandomValues(new Uint8Array(16));
 return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');
}
