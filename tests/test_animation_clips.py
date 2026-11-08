"""Named clip selection, initial TRS references and direct-node export contracts."""
import io
import json
import math
import unittest
import zipfile

from animation import (parse_animation, resolve_animation_source, prepare_animation,
                       select_clip, sample_track)
from model_export import to_glb, to_usdz
from json_to_glb import build_glb, build_usdz, validate_document
from server import run_model_request
from test_animation import mesh, decode_glb, clip
from test_json_to_glb import MODEL
from test_modeler import FakeBrep


SOURCE = '''animation move loop 4
track rotor
key 0 position base.position.x base.position.y base.position.z
key 4 position (base.position.x + 20) base.position.y base.position.z
end
end
animation turn loop 2
track rotor
for i in range(3)
key i euler base.euler.x base.euler.y (base.euler.z + i * 90)
end
end
end'''


def stage(data):
    return zipfile.ZipFile(io.BytesIO(data)).read('model.usda').decode()


class AnimationClipTests(unittest.TestCase):
    def test_omitted_name_is_main_in_parser_resolver_and_exports(self):
        named = SOURCE.replace('animation move loop', 'animation main loop')
        omitted = SOURCE.replace('animation move loop', 'animation loop')
        numeric = resolve_animation_source(named, meshes=[mesh()])
        short_numeric = resolve_animation_source(omitted, meshes=[mesh()])
        self.assertEqual(numeric, short_numeric)
        self.assertEqual(parse_animation(short_numeric)['clips'][0]['name'], 'main')
        self.assertEqual(parse_animation(clip().replace('animation main loop', 'animation loop')),
                         parse_animation(clip()))
        validate_document({**MODEL, 'animationSource':omitted})
        for export in (to_glb,to_usdz):
            self.assertEqual(export([mesh()],animation_source=named),
                             export([mesh()],animation_source=omitted))
        for duplicate in (omitted + '\n' + clip(),
                          omitted + '\n' + clip().replace('animation main loop','animation loop')):
            with self.assertRaisesRegex(ValueError, 'duplicate clip name'):
                resolve_animation_source(duplicate, meshes=[mesh()])

    def test_base_is_local_immutable_and_recomputed_from_new_meshes(self):
        initial = dict(name='rotor', position=[10,20,30], euler=[5,15,25], scale=[2,3,4])
        m = mesh([dict(name='parent', position=[100,0,0], euler=[0,0,0], scale=[1,1,1]), initial])
        before = json.dumps(m)
        numeric = resolve_animation_source(SOURCE, mode='python', meshes=[m])
        collection, bindings = prepare_animation(numeric, [m])
        self.assertEqual([c['name'] for c in collection['clips']], ['move','turn'])
        first, second = [b[('parent','rotor')] for b in bindings]
        self.assertEqual(sample_track(first,2)['position'], [20,20,30])
        self.assertEqual(sample_track(first,2)['euler'], [5,15,25])
        self.assertEqual(sample_track(first,2)['scale'], [2,3,4])
        self.assertEqual(sample_track(second,1)['position'], [10,20,30])
        self.assertEqual(sample_track(second,1)['euler'], [5,15,115])
        self.assertEqual(json.dumps(m), before)
        initial['position'][0] = 50
        updated = parse_animation(resolve_animation_source(SOURCE, mode='python', meshes=[m]))
        self.assertEqual(updated['clips'][0]['tracks'][0]['channels']['position'][0][1], [50,20,30])

    def test_base_scope_ambiguity_and_invalid_attribute(self):
        for bad in (SOURCE.replace('base.position.x', 'base.position.w'),
                    SOURCE.replace('base.position.x', 'base.__class__')):
            with self.assertRaises(ValueError):
                resolve_animation_source(bad, meshes=[mesh()])
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            resolve_animation_source(SOURCE, meshes=[])
        with self.assertRaisesRegex(ValueError, 'inside a track'):
            resolve_animation_source(SOURCE.replace('loop 2', 'loop base.position.x'), meshes=[mesh()])
        a = mesh(); b = mesh([dict(name='parent', **{k:v for k,v in a['groupPath'][0].items() if k!='name'}), a['groupPath'][0]])
        with self.assertRaisesRegex(ValueError, 'unambiguous'):
            resolve_animation_source(SOURCE, meshes=[a,b])

    def test_unique_names_invalid_names_and_invalid_later_clip(self):
        numeric = resolve_animation_source(SOURCE, meshes=[mesh()])
        for bad in (numeric.replace('animation turn', 'animation move'),
                    numeric.replace('animation move loop', 'animation 9bad loop'),
                    numeric.replace('animation turn loop 2', 'animation turn loop 0'),
                    numeric + '\nend'):
            with self.assertRaises(ValueError):
                parse_animation(bad)
        for export in (to_glb,to_usdz):
            with self.assertRaisesRegex(ValueError, 'missing'):
                export([mesh()], animation_source=numeric.replace('animation turn loop 2\ntrack rotor','animation turn loop 2\ntrack missing'))

    def test_glb_all_clips_target_original_node_and_keep_rest_pose(self):
        m = mesh(); m['groupPath'][0]['scale'] = [2,3,4]
        numeric = resolve_animation_source(SOURCE, meshes=[m])
        doc, accessor = decode_glb(to_glb([m],scale=.5,animation_source=numeric))
        self.assertEqual([c['name'] for c in doc['animations']], ['move','turn'])
        node = next(i for i,n in enumerate(doc['nodes']) if n['name']=='rotor')
        self.assertEqual(len(doc['nodes']),2)
        self.assertEqual(doc['nodes'][node]['translation'], [5,0,0])
        self.assertEqual(doc['nodes'][node]['scale'], [2,4,3])
        for animation, path, duration in zip(doc['animations'], ('translation','rotation'), (4,2)):
            self.assertEqual(len(animation['channels']),1)
            channel = animation['channels'][0]
            self.assertEqual(channel['target'], {'node':node,'path':path})
            sampler = animation['samplers'][channel['sampler']]
            self.assertEqual(accessor(sampler['input'])[-1], duration)
            if path=='translation':
                self.assertEqual(accessor(sampler['output']), (5,0,0,15,0,0))

    def test_usdz_selected_clip_and_unknown_selection(self):
        numeric = resolve_animation_source(SOURCE, meshes=[mesh()])
        self.assertEqual(to_glb([mesh()], animation_source=SOURCE), to_glb([mesh()], animation_source=numeric))
        first = stage(to_usdz([mesh()], animation_source=numeric))
        second = stage(to_usdz([mesh()], animation_source=numeric, animation_clip='turn'))
        self.assertIn('endTimeCode = 240',first)
        self.assertIn('xformOp:translate.timeSamples',first)
        self.assertNotIn('xformOp:rotateXYZ.timeSamples',first)
        self.assertIn('endTimeCode = 120',second)
        self.assertIn('xformOp:rotateXYZ.timeSamples',second)
        self.assertNotIn('xformOp:translate.timeSamples',second)
        self.assertNotIn('Animation_',second)
        self.assertIn('xformOp:translate = (10, 0, 0)',second)
        with self.assertRaisesRegex(ValueError,'Unknown animation clip'):
            to_usdz([mesh()],animation_source=numeric,animation_clip='missing')
        self.assertEqual(select_clip(parse_animation(numeric),'turn')['duration'],2)

    def test_quaternion_base_euler_and_rotation_override(self):
        m = mesh(); m['groupPath'][0]['quaternion'] = [0,0,math.sqrt(.5),math.sqrt(.5)]
        numeric = resolve_animation_source(SOURCE, meshes=[m])
        collection, bindings = prepare_animation(numeric, [m])
        position = sample_track(bindings[0][('rotor',)],1)
        rotation = sample_track(bindings[1][('rotor',)],1)
        self.assertIn('quaternion',position)
        self.assertNotIn('quaternion',rotation)
        self.assertAlmostEqual(rotation['euler'][2],180)
        usd = stage(to_usdz([m],animation_source=numeric,animation_clip='turn'))
        self.assertNotIn('xformOp:orient',usd)
        self.assertIn('xformOp:rotateXYZ.timeSamples',usd)
        self.assertIn('xformOp:orient',stage(to_usdz([m],animation_source=numeric,animation_clip='move')))

    def test_worker_resolves_cached_groups_without_executing_python(self):
        request = {'source':'raise RuntimeError("must not execute")','mode':'python',
                   'animationSource': SOURCE, 'animationGroups':[{'groupPath':mesh()['groupPath']}]}
        result = json.loads(run_model_request(request,'/animation/resolve'))
        self.assertIn('key 4 position 30 0 0',result['resolvedAnimationSource'])

    def test_document_validation_defers_initial_value_dependent_arithmetic(self):
        model = 'group rotor\nscale .25 .25 .25\nbox body 0 0 0 1 1 1\nend'
        source = 'animation size loop 2\ntrack rotor\n'
        source += 'for i in range(3)\nkey i scale (1 - base.scale.x) (1 / (base.scale.y - 1)) (-base.scale.z)\nend\nend\nend'
        # Syntax checking must not evaluate a fabricated base=1 (division by zero).
        document = {**MODEL, 'source':model, 'animationSource':source}
        validate_document(document)
        # Real evaluation still rejects the actual negative scale components.
        with self.assertRaisesRegex(ValueError,'scale must be positive'):
            build_glb(document,FakeBrep())

    def test_document_exports_resolve_real_geometry_and_saved_selection(self):
        model = 'group rotor\nposition 10 20 30\nbox body 0 0 0 1 1 1\nend'
        document = {**MODEL, 'source':model,'animationSource':SOURCE,'animationClip':'turn'}
        doc, _ = decode_glb(build_glb(document,FakeBrep()))
        self.assertEqual(len(doc['animations']),2)
        usd = stage(build_usdz(document,FakeBrep()))
        self.assertIn('endTimeCode = 120',usd)
        self.assertIn('xformOp:translate = (10, 20, 30)',usd)


if __name__=='__main__':
    unittest.main()
