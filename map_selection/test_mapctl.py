import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import mapctl as m


class MapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.catalog=m.read_catalog(m.HERE/'maps.json')
        self.ctrack=copy.deepcopy(m.choose(self.catalog,'ctrack'))
        self.data=b'private fixture, not real map bytes'
        self.ctrack['artifact']={'file':'map.tar.zst','bytes':len(self.data),
                                 'sha256':hashlib.sha256(self.data).hexdigest()}
        self.sources=self.root/'sources.json'
        self.sources.write_text(json.dumps({'schema':1,'sources':{'ctrack':{
            'repository':'example/private-map','release_tag':'v1-test'}}}))
        self.cache=self.root/'cache'
        self.calls=[]

    def runner(self,args,**kwargs):
        self.calls.append(args)
        out=''
        if args[1:3]==['repo','view']:out='true'
        elif args[1:3]==['release','download']:
            (Path(args[args.index('--dir')+1])/'map.tar.zst').write_bytes(self.data)
        return subprocess.CompletedProcess(args,0,out,'')

    def test_catalog_has_multiple_maps(self):
        self.assertEqual({x['id'] for x in self.catalog['maps']},{'town01','town10hd','ctrack'})

    def test_unknown_map_refused(self):
        with self.assertRaises(m.MapError):m.choose(self.catalog,'unknown')

    def test_official_map_never_contacts_private_repo(self):
        def forbidden(*a,**kw):raise AssertionError('private access occurred')
        result=m.fetch(m.choose(self.catalog,'town01'),None,None,run=forbidden,which=forbidden)
        self.assertFalse(result['private_access'])
        self.assertFalse(result['downloaded'])

    def test_valid_cache_needs_neither_credentials_nor_network(self):
        self.cache.mkdir();(self.cache/'map.tar.zst').write_bytes(self.data)
        def forbidden(*a,**kw):raise AssertionError('network access occurred')
        result=m.fetch(self.ctrack,self.cache,offline=True,run=forbidden,which=forbidden)
        self.assertEqual(result['status'],'verified_cache')

    def test_bad_cache_preserved(self):
        self.cache.mkdir();p=self.cache/'map.tar.zst';p.write_bytes(b'bad')
        with self.assertRaises(m.MapError):m.fetch(self.ctrack,self.cache)
        self.assertEqual(p.read_bytes(),b'bad')

    def test_same_size_bad_hash_refused(self):
        self.cache.mkdir();(self.cache/'map.tar.zst').write_bytes(b'x'*len(self.data))
        with self.assertRaises(m.MapError):m.fetch(self.ctrack,self.cache)

    def test_symlink_cache_refused(self):
        self.cache.mkdir();p=self.root/'real';p.write_bytes(self.data)
        (self.cache/'map.tar.zst').symlink_to(p)
        with self.assertRaises(m.MapError):m.fetch(self.ctrack,self.cache)

    def test_offline_missing_does_not_create_cache(self):
        with self.assertRaises(m.MapError):m.fetch(self.ctrack,self.cache,offline=True)
        self.assertFalse(self.cache.exists())

    def test_missing_source_fails_without_network(self):
        with self.assertRaises(m.MapError):m.fetch(self.ctrack,self.cache)
        self.assertFalse(self.cache.exists())

    def test_missing_gh_has_actionable_error(self):
        with self.assertRaisesRegex(m.MapError,'CLI'):
            m.fetch(self.ctrack,self.cache,self.sources,which=lambda _:None)

    def test_private_download_checks_remote_privacy_and_pinned_tag(self):
        result=m.fetch(self.ctrack,self.cache,self.sources,run=self.runner,which=lambda _:'/mock/gh')
        self.assertEqual(result['status'],'downloaded_verified')
        self.assertEqual((self.cache/'map.tar.zst').read_bytes(),self.data)
        self.assertEqual(self.calls[0][1:3],['auth','status'])
        self.assertEqual(self.calls[1][1:3],['repo','view'])
        self.assertEqual(self.calls[2][1:4],['release','download','v1-test'])
        self.assertEqual((self.cache/'map.tar.zst').stat().st_mode & 0o777,0o600)
        self.assertFalse(list(self.cache.glob('.map-download-*')))

    def test_public_repo_refused_before_download(self):
        def public(args,**kwargs):
            self.calls.append(args)
            return subprocess.CompletedProcess(args,0,'false' if args[1]=='repo' else '','')
        with self.assertRaisesRegex(m.MapError,'비공개'):
            m.fetch(self.ctrack,self.cache,self.sources,run=public,which=lambda _:'/mock/gh')
        self.assertFalse(any(c[1]=='release' for c in self.calls))

    def test_auth_failure_does_not_echo_output(self):
        def denied(args,**kwargs):return subprocess.CompletedProcess(args,1,'secret-token','secret-token')
        with self.assertRaises(m.MapError) as exc:
            m.fetch(self.ctrack,self.cache,self.sources,run=denied,which=lambda _:'/mock/gh')
        self.assertNotIn('secret-token',str(exc.exception))

    def test_bad_download_kept_but_not_published(self):
        expected=self.ctrack['artifact']['sha256'];self.data=b'bad download'
        with self.assertRaises(m.MapError):
            m.fetch(self.ctrack,self.cache,self.sources,run=self.runner,which=lambda _:'/mock/gh')
        self.assertFalse((self.cache/'map.tar.zst').exists())
        self.assertTrue(list(self.cache.glob('.map-download-*/map.tar.zst')))
        self.assertEqual(self.ctrack['artifact']['sha256'],expected)

    def test_no_overwrite_when_concurrent_file_appears(self):
        def raced(args,**kwargs):
            result=self.runner(args,**kwargs)
            if args[1]=='release':(self.cache/'map.tar.zst').write_bytes(b'other bytes')
            return result
        with self.assertRaises(m.MapError):
            m.fetch(self.ctrack,self.cache,self.sources,run=raced,which=lambda _:'/mock/gh')
        self.assertEqual((self.cache/'map.tar.zst').read_bytes(),b'other bytes')

    def test_unsafe_names_refused(self):
        for name in ['../map','/map','*.tar.zst','-option','x/y']:
            record=dict(self.ctrack['artifact'],file=name)
            with self.subTest(name=name),self.assertRaises(m.MapError):m.valid_artifact(record)

    def test_repository_url_or_credentials_refused(self):
        for repo in ['https://github.com/example/map','token@github.com/example/map','-option/map']:
            self.sources.write_text(json.dumps({'schema':1,'sources':{'ctrack':{'repository':repo,'release_tag':'v1'}}}))
            with self.subTest(repo=repo),self.assertRaises(m.MapError):m.private_source(self.sources,'ctrack')

    def test_latest_refused(self):
        self.sources.write_text(json.dumps({'schema':1,'sources':{'ctrack':{'repository':'example/map','release_tag':'latest'}}}))
        with self.assertRaises(m.MapError):m.private_source(self.sources,'ctrack')

    def test_sils_selection_blocked_without_matching_profile(self):
        for item in self.catalog['maps']:
            out=self.root/(item['id']+'.json')
            with self.subTest(map=item['id']),self.assertRaises(m.MapError):m.select(item,'sils',out)
            self.assertFalse(out.exists())

    def test_carla_selection_has_map_version_and_no_auto_engage(self):
        out=self.root/'selection.json';p=m.select(self.ctrack,'carla',out)
        self.assertEqual(json.loads(out.read_text())['map_id'],'ctrack')
        self.assertFalse(p['auto_engage']);self.assertFalse(p['runtime_started'])

    def test_selection_never_overwrites(self):
        out=self.root/'selection.json';out.write_text('preserve me')
        with self.assertRaises(FileExistsError):m.select(self.ctrack,'carla',out)
        self.assertEqual(out.read_text(),'preserve me')

    def test_catalog_cannot_claim_unimplemented_runtime_ready(self):
        data=copy.deepcopy(self.catalog);data['maps'][0]['autoware']['ready']=True
        path=self.root/'catalog.json';path.write_text(json.dumps(data))
        with self.assertRaises(m.MapError):m.read_catalog(path)


if __name__=='__main__':unittest.main()
