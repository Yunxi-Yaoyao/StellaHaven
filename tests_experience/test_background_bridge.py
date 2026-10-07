"""The actual template JS, AST extracted: never imports app/database."""
import ast
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


def background_js():
    tree = ast.parse((ROOT / 'app/services/openlist_compat.py').read_text())
    value = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'BACKGROUND_JS' for t in n.targets))
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        value = value.func.value
    return ast.literal_eval(value).replace('event.origin!==location.origin', 'event.origin!=="https://main.example"').replace('const parentOrigin=location.origin', 'const parentOrigin="https://main.example"')


HARNESS = r'''
const vm=require('node:vm'),assert=require('node:assert/strict');
const source=JSON.parse(process.argv[1]), scenario=process.argv[2];
const events={},docEvents={},frames=[],microtasks=[],messages=[],storage=new Map();
function el(){const values=new Map();return {dataset:{},style:{getPropertyValue:k=>values.get(k)?.[0]||'',getPropertyPriority:k=>values.get(k)?.[1]||'',setProperty:(k,v,p)=>values.set(k,[v,p]),removeProperty:k=>values.delete(k)},removeAttribute:k=>{if(k==='data-bg-mode')delete html.dataset.bgMode}}}
const html=el();let body=el(),root=el();
const metaValues=new Map([['content','dark']]);const meta={hasAttribute:k=>metaValues.has(k),getAttribute:k=>metaValues.get(k)||null,setAttribute:(k,v)=>metaValues.set(k,v),removeAttribute:k=>metaValues.delete(k)};
if(scenario==='late')root=null;
const document={documentElement:html,get body(){return body},getElementById:()=>root,querySelectorAll:s=>s.startsWith('meta')?[meta]:[],readyState:'complete',addEventListener:(k,f)=>docEvents[k]=f};
const parent={postMessage:(data,origin)=>messages.push({data,origin})};
const window={parent,addEventListener:(k,f)=>events[k]=f};
const observers=[];class MutationObserver{constructor(cb){this.cb=cb;observers.push(this)}observe(){}disconnect(){}}
const sandbox={window,document,location:{origin:'https://frame.example',search:''},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},URLSearchParams,MutationObserver,queueMicrotask:f=>microtasks.push(f),requestAnimationFrame:f=>frames.push(f),cancelAnimationFrame:()=>{},Map,console};
vm.runInNewContext(source,sandbox);
const flush=()=>{for(let i=0;i<8&&(frames.length||microtasks.length);i++){const callbacks=[...microtasks.splice(0),...frames.splice(0)];for(const f of callbacks)f();}};
const send=(data,origin='https://main.example',sender=parent)=>events.message({data,origin,source:sender});
const data={type:'stella-bg-mode',mode:'image',module_id:'module-a',request_id:'generation-1'};
if(scenario==='request'){assert(messages.some(m=>m.data.type==='stella-bg-request'&&m.origin==='https://main.example'));}
if(scenario==='ready'){send(data);assert.equal(messages.filter(m=>m.data.type==='stella-bg-ready').length,0);flush();const a=messages.find(m=>m.data.type==='stella-bg-ready');assert(a);assert.equal(a.origin,'https://main.example');assert.deepEqual(JSON.parse(JSON.stringify(a.data)),{type:'stella-bg-ready',mode:'image',module_id:'module-a',request_id:'generation-1'});assert.equal(html.style.getPropertyValue('background-color'),'transparent');assert.equal(body.style.getPropertyValue('background-color'),'transparent');assert.equal(root.style.getPropertyValue('background-color'),'transparent');}
if(scenario==='late'){send(data);flush();assert.equal(messages.filter(m=>m.data.type==='stella-bg-ready').length,0);root=el();for(const o of observers)o.cb();flush();assert(messages.some(m=>m.data.type==='stella-bg-ready'));assert.equal(root.style.getPropertyValue('background-color'),'transparent');}
if(scenario==='untrusted'){send(data,'https://evil.example');send(data,'https://main.example',{});flush();assert.equal(messages.filter(m=>m.data.type==='stella-bg-ready').length,0);assert.equal(html.dataset.bgMode,undefined);}
if(scenario==='superseded'){send(data);send({...data,mode:'solid',request_id:'generation-2'});flush();const a=messages.filter(m=>m.data.type==='stella-bg-ready');assert.equal(a.length,1);assert.equal(a[0].data.request_id,'generation-2');assert.equal(a[0].data.mode,'solid');assert.equal(html.dataset.bgMode,undefined);assert.equal(html.style.getPropertyValue('background-color'),'');}
if(scenario==='invalid'){send({...data,request_id:{evil:true}});flush();assert.equal(messages.filter(m=>m.data.type==='stella-bg-ready').length,0);}
if(scenario==='meta'){send(data);flush();assert.equal(meta.getAttribute('content'),'normal');send({...data,mode:'solid',request_id:'generation-2'});flush();assert.equal(meta.getAttribute('content'),'dark');}
if(scenario==='late-meta'){send(data);flush();meta.setAttribute('content','dark');for(const o of observers)o.cb();flush();assert.equal(meta.getAttribute('content'),'normal');}
if(scenario==='hidden'){send(data);for(const f of microtasks.splice(0))f();assert(messages.some(m=>m.data.type==='stella-bg-ready'),'hidden cross-site rAF must not be required for style readiness');}
console.log('PASS '+scenario);
'''


class BackgroundBridge(unittest.TestCase):
    def run_case(self, scenario):
        p = subprocess.run(['node', '-e', HARNESS, json.dumps(background_js()), scenario], capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_marker_is_visible_in_template(self):
        self.assertIn('/* stella:background-ready:v1 */', background_js())

    def test_requests_current_parent_mode(self): self.run_case('request')
    def test_ack_after_paint_for_exact_generation(self): self.run_case('ready')
    def test_waits_for_late_root(self): self.run_case('late')
    def test_untrusted_origin_and_window_never_apply_or_ack(self): self.run_case('untrusted')
    def test_superseded_ack_cannot_reveal_old_mode(self): self.run_case('superseded')
    def test_invalid_ack_envelope_ignored(self): self.run_case('invalid')
    def test_canvas_metadata_override_is_reversible(self): self.run_case('meta')
    def test_dynamic_canvas_metadata_remains_transparent(self): self.run_case('late-meta')
    def test_hidden_frame_ack_does_not_need_animation_frame(self): self.run_case('hidden')


if __name__ == '__main__':
    unittest.main()
