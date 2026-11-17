const scales:Record<string,bigint>={byte:1n,GB:1000000000n,GiB:1073741824n,TB:1000000000000n,TiB:1099511627776n,'bit/s':1n,Mbps:1000000n,'%':1n};
export function toBase(value:string,unit:string):string {
 if(!/^\d+(\.\d+)?$/.test(value))throw new Error('请输入非负数');
 const [whole,fraction='']=value.split('.');const scale=scales[unit];if(!scale)throw new Error('未知单位');
 const denominator=10n**BigInt(fraction.length);const numerator=BigInt(whole+fraction)*scale;
 if(unit==='%' || unit==='Mbps' || unit==='bit/s')return String(Number(value)*Number(scale));
 if(numerator%denominator)throw new Error('累计阈值必须换算为整数字节');
 return String(numerator/denominator);
}
export function fromBase(value:string,unit:string):string {
 const scale=scales[unit];if(!scale)throw new Error('未知单位');
 if(unit==='%' || unit==='Mbps' || unit==='bit/s')return String(Number(value)/Number(scale));
 const n=BigInt(value),whole=n/scale;let rem=n%scale;let fraction='';
 while(rem){rem*=10n;fraction+=String(rem/scale);rem%=scale;}
 return String(whole)+(fraction?'.'+fraction:'');
}
