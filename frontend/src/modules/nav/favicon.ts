// Explicit public-origin browser probes only. Never send a URL to the server.
export function faviconCandidates(source:string):string[]{
 try{const u=new URL(source),host=u.hostname.toLowerCase();
  if(!['https:','http:'].includes(u.protocol)||u.username||u.password||(u.port&&!['80','443'].includes(u.port)))return [];
  // Reject IPs (including IPv6/alternate normalized encodings), local names and reserved suffixes.
  if(!host.includes('.')||/^[\d.]+$/.test(host)||host.includes(':')||/(^|\.)(localhost|local|internal|home|lan|invalid|test|example)$/.test(host))return [];
  return ['/favicon.ico','/apple-touch-icon.png','/favicon.png'].map(p=>u.origin+p);
 }catch{return [];}
}
