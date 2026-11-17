"""Exact operator-approved direct Immich pair on its persisted generic module ID.

No wildcard DNS trust or automatic public/private derivation for external sites.
These tests never construct an SSH transport or write to a deployment target.
"""
import copy
import json
import unittest
from unittest.mock import patch
from test_production_release import load
from test_production_entry_overlay import registry, overlay, extended_inventory

IMMICH_MODULE = '663a649f37dc44288f6f7d8e8795d72a'

def direct_registry():
    return [row for row in registry() if row['service_id'] != 'gallery'] + [
        {'service_id':IMMICH_MODULE,'public':'https://immich.xiya.live','private':'https://immich.p.xiya.live'}]


class DirectOwnedModuleRegistryTests(unittest.TestCase):
    def validate(self, rows):
        node=load('node_production')
        release=load('production_release')
        env=overlay(rows)
        with patch.object(node,'run',side_effect=AssertionError('no external command')), \
             patch.object(node.Path,'mkdir',side_effect=AssertionError('no filesystem mutation')):
            self.assertIs(node.validate_application_env_overrides(env),env)
            inv=extended_inventory(env)
            self.assertEqual(release.validate_inventory(inv),inv)
            node.Node(dict(node='nas',inventory=inv,op='probe'))
            node.Node(dict(node='nyarch',inventory=inv,op='probe'))
        return env

    def reject(self, rows):
        node=load('node_production')
        release=load('production_release')
        env=overlay(rows)
        with self.assertRaises(ValueError):node.validate_application_env_overrides(env)
        with self.assertRaises(ValueError):release.validate_inventory(extended_inventory(env))

    def test_persisted_generic_immich_id_accepts_its_exact_explicit_owned_pair(self):
        rows=direct_registry()
        before=copy.deepcopy(rows)
        env=self.validate(rows)
        self.assertEqual(rows,before)
        self.assertNotIn('https://immich.p.xiya.live',env['STELLA_TRUSTED_ORIGINS'])
        self.assertNotIn('https://immich.xiya.live',env['STELLA_TRUSTED_ORIGINS'])

    def test_legacy_gallery_and_derived_isolated_modules_still_work(self):
        self.validate(registry())
        rows=direct_registry()+[{'service_id':'125398b55f1847c7a9ebb70cc651baee',
            'public':'https://app-125398b55f1847c7a9ebb70cc651baee.xiya.live',
            'private':'https://app-125398b55f1847c7a9ebb70cc651baee.p.xiya.live'}]
        self.validate(rows)

    def test_direct_pair_requires_exact_persisted_module_id_shape_and_both_lanes(self):
        for sid in ['gallery-alias','IMMICH',IMMICH_MODULE.upper(),'f'*31,'f'*33,'g'*32,'',None,1]:
            rows=direct_registry();rows[-1]['service_id']=sid
            with self.subTest(sid=sid):self.reject(rows)
        rows=direct_registry();del rows[-1]['private'];self.reject(rows)

    def test_unknown_direct_hosts_and_noncanonical_owned_urls_fail_closed(self):
        for lane in ['public','private']:
            for url in ['https://other.xiya.live','https://immich.evil.example','http://immich.xiya.live',
                        'https://immich.xiya.live/','https://immich.xiya.live:443',
                        'https://user:pass@immich.xiya.live','https://*.xiya.live','https://immich.xiya.live?x=1']:
                rows=direct_registry();rows[-1][lane]=url
                with self.subTest(lane=lane,url=url):self.reject(rows)
        rows=direct_registry();rows[-1]['public'],rows[-1]['private']=rows[-1]['private'],rows[-1]['public'];self.reject(rows)

    def test_duplicate_direct_alias_and_foreign_module_authority_stay_rejected(self):
        self.reject(direct_registry()+[registry()[-1]])
        rows=direct_registry();rows[-1]['private']='https://app-'+IMMICH_MODULE+'.p.xiya.live';self.reject(rows)
        rows=direct_registry();rows[-1]['public']='https://app-'+'a'*32+'.xiya.live';self.reject(rows)

    def test_direct_pair_does_not_expand_main_trust_or_allow_partial_environment(self):
        node=load('node_production')
        for origin in ['https://immich.xiya.live','https://immich.p.xiya.live']:
            env=overlay(direct_registry());env['STELLA_TRUSTED_ORIGINS']+=','+origin
            with self.assertRaises(ValueError):node.validate_application_env_overrides(env)
        env=overlay(direct_registry());del env['STELLA_BACKUP_DIRECTORY']
        with self.assertRaises(ValueError):node.validate_application_env_overrides(env)

if __name__=='__main__':unittest.main()
