"""Copy-equivalence guards for the source-only contract loader's test dependency."""
import copy,importlib.util,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]

def helper():
 p=ROOT/'tests_isolated/evidence_graph_copy.py'
 assert p.is_file(),'Evidence copy helper is not implemented'
 spec=importlib.util.spec_from_file_location('graph_copy_under_test',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_fresh_graph_aliases_cycles_and_mutation_are_preserved():
 m=helper();shared={'fields':['name','icon']};value={'a':shared,'b':shared};value['cycle']=value
 result=m.graph_copy(value)
 assert result is not value and result['a'] is result['b'] and result['cycle'] is result
 result['a']['fields'].append('changed');assert value['a']['fields']==['name','icon']
 value['a']['fields'].append('later');new=m.graph_copy(value)
 assert new['a']['fields']==['name','icon','later'] and result['a']['fields']==['name','icon','changed']
 # Large real component graphs must not silently fall back to the slow copier.
 from unittest.mock import patch
 large={'items':['leaf']*100001}
 with patch.object(m,'_ORIGINAL',side_effect=AssertionError('large plain graph fell back')):
  cloned=m.graph_copy(large)
  assert cloned==large and cloned['items'] is not large['items']
 large['items'].append('new-input')
 assert len(m.graph_copy(large)['items'])==100002 and len(cloned['items'])==100001

def test_custom_objects_and_non_json_keys_use_original_copy_semantics():
 m=helper()
 class Custom:
  def __deepcopy__(self,memo):return 'original-deepcopy-marker'
  def __reduce__(self):raise AssertionError('custom reducers must never reach the fast copier')
 assert m.graph_copy({'x':Custom()})=={'x':'original-deepcopy-marker'}
 assert m.graph_copy({(1,2):'tuple-key'})==copy.deepcopy({(1,2):'tuple-key'})
 class LooksAtomic(type):
  def __eq__(cls,other):return True
  __hash__=type.__hash__
 class Pretender(metaclass=LooksAtomic):
  def __deepcopy__(self,memo):return 'metaclass-original-marker'
  def __reduce__(self):raise AssertionError('spoofed exact type must not be trusted')
 assert m.graph_copy({'x':Pretender()})=={'x':'metaclass-original-marker'}
 # A built-in subclass is not a plain built-in: no unsafe reducer may reach
 # native serialization, even when deeply nested in an otherwise plain graph.
 class UnsafeList(list):
  def __deepcopy__(self,memo):return ['safe-original']
  def __reduce_ex__(self,protocol):raise AssertionError('unsafe __reduce__ canary')
 from unittest.mock import patch
 with patch.object(m,'_ORIGINAL',wraps=m._ORIGINAL) as original:
  assert m.graph_copy({'nested':[UnsafeList([1])]})=={'nested':[['safe-original']]}
  import math
  assert math.isnan(m.graph_copy({'nan':float('nan')})['nan'])
  assert m.graph_copy({(1,2):'tuple-key'})=={(1,2):'tuple-key'}
  assert original.call_count==3

@pytest.mark.parametrize('value',[{'a':[None,True,False,1,1.5,'雪']},{'deep':{'items':[{'one':1},{'two':2}]}},[1,{'x':'y'}]])
def test_plain_graph_is_equal_and_independently_mutable(value):
 m=helper();result=m.graph_copy(value);assert result==copy.deepcopy(value) and result is not value


def test_explicit_memo_is_honored_and_dependency_patch_is_scoped():
 m=helper();x={'x':1};replacement={'replacement':True};original=copy.deepcopy
 assert m.graph_copy(x,{id(x):replacement}) is replacement
 with m.contract_copy_dependency():assert copy.deepcopy is m.graph_copy
 assert copy.deepcopy is original
 with pytest.raises(ValueError):
  with m.contract_copy_dependency():raise ValueError('fixture')
 assert copy.deepcopy is original
