import {expect,it} from 'vitest';
import {sample} from './catalog';
type NumericSchema=Parameters<typeof sample>[0];
const limits=['minimum','exclusiveMinimum','maximum','exclusiveMaximum'] as const;

// Independent range assertions, including JSON round-trip (NaN/Infinity become null).
function expectValid(schema:NumericSchema,value:unknown){
 expect(typeof value).toBe('number');
 const number=value as number;
 expect(Number.isFinite(number)).toBe(true);
 expect(Math.abs(number)).toBeLessThanOrEqual(Number.MAX_SAFE_INTEGER);
 expect(JSON.parse(JSON.stringify(number))).toBe(number);
 if(schema.type==='integer')expect(Number.isSafeInteger(number)).toBe(true);
 if(schema.minimum!==undefined)expect(number).toBeGreaterThanOrEqual(Number(schema.minimum));
 if(schema.exclusiveMinimum!==undefined)expect(number).toBeGreaterThan(Number(schema.exclusiveMinimum));
 if(schema.maximum!==undefined)expect(number).toBeLessThanOrEqual(Number(schema.maximum));
 if(schema.exclusiveMaximum!==undefined)expect(number).toBeLessThan(Number(schema.exclusiveMaximum));
 if(schema.enum)expect(schema.enum).toContain(number);
}
const ranges:NumericSchema[]=[
 {type:'integer'}, {type:'number'},
 {type:'integer',minimum:3}, {type:'integer',maximum:-3},
 {type:'integer',exclusiveMinimum:0}, {type:'integer',exclusiveMaximum:0},
 {type:'integer',minimum:1.2,maximum:2.2}, {type:'integer',minimum:-2.2,maximum:-1.2},
 {type:'integer',exclusiveMinimum:2,exclusiveMaximum:4},
 {type:'integer',exclusiveMinimum:-4,exclusiveMaximum:-2},
 {type:'integer',exclusiveMinimum:1.2,exclusiveMaximum:2.2},
 {type:'integer',exclusiveMinimum:-2.2,exclusiveMaximum:-1.2},
 {type:'integer',minimum:2,exclusiveMinimum:3,maximum:5,exclusiveMaximum:5},
 {type:'integer',minimum:3,maximum:3},
 {type:'number',minimum:0.2,maximum:0.3}, {type:'number',minimum:-0.3,maximum:-0.2},
 {type:'number',exclusiveMinimum:1,exclusiveMaximum:2},
 {type:'number',exclusiveMinimum:-2,exclusiveMaximum:-1},
 {type:'number',exclusiveMinimum:0}, {type:'number',exclusiveMaximum:0},
 {type:'number',minimum:0.1,exclusiveMinimum:0.2,maximum:0.4,exclusiveMaximum:0.3},
 {type:'number',minimum:0.5,maximum:0.5},
 // Adjacent representable endpoints, including the asymmetric spacing at -1.
 {type:'number',exclusiveMinimum:1,maximum:1+Number.EPSILON},
 {type:'number',exclusiveMinimum:-1,maximum:-1+Number.EPSILON/2},
 {type:'number',minimum:1-Number.EPSILON/2,exclusiveMaximum:1},
 {type:'integer',minimum:Number.MAX_SAFE_INTEGER},
 {type:'integer',maximum:-Number.MAX_SAFE_INTEGER},
];
it.each(ranges)('produces a safe value within numeric range %j',schema=>expectValid(schema,sample(schema)));

const impossible:NumericSchema[]=[
 {type:'number',minimum:2,maximum:1},
 {type:'number',minimum:1,exclusiveMaximum:1},
 {type:'number',exclusiveMinimum:1,maximum:1},
 {type:'integer',minimum:0.1,maximum:0.9},
 {type:'integer',minimum:-0.9,maximum:-0.1},
 {type:'integer',exclusiveMinimum:1,exclusiveMaximum:2},
 {type:'number',exclusiveMinimum:1,exclusiveMaximum:1+Number.EPSILON},
 {type:'number',exclusiveMinimum:Number.MAX_VALUE},
 {type:'integer',minimum:Number.MAX_SAFE_INTEGER+1},
 {type:'integer',maximum:-Number.MAX_SAFE_INTEGER-1},
 {type:'number',minimum:Number.MAX_SAFE_INTEGER+1},
 ...limits.flatMap(key=>[NaN,Infinity,-Infinity].map(value=>({type:'number',[key]:value}))),
];
it.each(impossible)('marks conflicting, non-finite or unsafe numeric range %j',schema=>{
 const result=sample(schema);
 expect(result).toMatch(/^<REPLACE_ME:.*数值.*>$/);
});

it.each([
 {schema:{type:'integer',minimum:1,default:7},expected:7},
 {schema:{type:'number',minimum:0.1,default:0.5},expected:0.5},
 {schema:{type:'integer',minimum:1,default:0,enum:[0,3]},expected:3},
 {schema:{type:'integer',minimum:1,default:8,enum:[2,4]},expected:2},
 {schema:{type:'integer',minimum:1,default:4,enum:[2,4]},expected:4},
 {schema:{type:'integer',minimum:1,enum:[0,1.5,2]},expected:2},
])('preserves only a valid numeric default or enum %j',({schema,expected})=>{
 expect(sample(schema)).toBe(expected);expectValid(schema,sample(schema));
});
it.each([NaN,Infinity,-Infinity,Number.MAX_SAFE_INTEGER+1,1.5,'invalid'])('replaces an invalid integer default %s',value=>{
 const schema={type:'integer',minimum:1,maximum:3,default:value};expectValid(schema,sample(schema));
});
it.each([[],[0],['invalid'],[Infinity],[1.5]].map(value=>({value})))('marks a numeric enum with no legal member $value',({value})=>{
 expect(sample({type:'integer',minimum:1,enum:value})).toMatch(/^<REPLACE_ME:.*数值.*>$/);
});
it('keeps secret-name placeholders ahead of numeric generation',()=>{
 expect(sample({type:'integer',minimum:1,default:123},'token')).toBe('<REPLACE_ME>');
});
