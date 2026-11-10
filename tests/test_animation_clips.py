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

    def test_duration_cycle_time_and_values_share_numeric_syntax(self):
        source = """# comment
animation motion loop (02 + 2)
track rotor
cycle position ${8 / 2}
key 0 position 0 0 0
key (2 * 2) position (9007199254740993 - 9007199254740992) ${6 / 2} 0
end
end"""
        animation = parse_animation(source)
        self.assertEqual(animation, parse_animation(resolve_animation_source(source, meshes=[mesh()])))
        self.assertEqual(animation["clips"][0]["tracks"][0]["channels"]["position"][-1],
                         [4, [1, 3, 0]])
        for syntax_only in (False, True):
            with self.assertRaisesRegex(ValueError, "Animation line 6:"):
                resolve_animation_source(source.replace("${6 / 2}", "0x10"), syntax_only=syntax_only)

    def test_loop_expansion_can_exceed_authored_source_limit(self):
        source = """animation long loop 511.875
track rotor
for i in range(4096)
key (i / 8) position (i / 7) 0 0
end
end
end"""
        self.assertGreater(len(resolve_animation_source(source, meshes=[mesh()])), 100_000)
        model = "group rotor\nbox body 0 0 0 1 1 1\nend"
        document = {**MODEL, "source": model, "animationSource": source}
        glb, accessor = decode_glb(build_glb(document, FakeBrep()))
        self.assertEqual(len(accessor(glb["animations"][0]["samplers"][0]["input"])), 4096)
        self.assertIn("endTimeCode = 30712.5", stage(build_usdz(document, FakeBrep())))

    def test_shared_globals_and_loops_generate_geometry_clips_and_tracks(self):
        model = """let width = 4
fn spacing(x) = x + width
let count = copies
for i in range(count)
  group rotor_${i}
    position (i * pitch) 0 0
    box body_${i} 0 0 0 width (width / 2) sqrt(width)
  end
end"""
        source = "\n".join((
            "LET copies = 2",
            "LET pitch = spacing(3)",
            "FOR shot IN RANGE(copies)",
            "  ANIMATION take_${shot} LOOP " + "\\",
            "    (shot + 1)",
            "    for i in range(count)",
            "      TRACK rotor_${i}",
            "        KEY 0 POSITION base.position.x 0 0",
            "        KEY (shot + 1) POSITION (base.position.x + pitch) 0 0",
            "      END", "    end", "  END", "END",
        ))
        document = {**MODEL, "source": model, "animationSource": source, "animationClip": "take_1"}
        validate_document(document)
        response = json.loads(run_model_request(document, "/preview"))
        tracks = parse_animation(response["resolvedAnimationSource"])["clips"]
        self.assertEqual([c["name"] for c in tracks], ["take_0", "take_1"])
        self.assertEqual([t["target"] for t in tracks[1]["tracks"]], ["rotor_0", "rotor_1"])
        self.assertEqual(tracks[1]["tracks"][1]["channels"]["position"], [[0, [7, 0, 0]], [2, [14, 0, 0]]])
        glb, _ = decode_glb(build_glb(document, FakeBrep()))
        self.assertEqual([c["name"] for c in glb["animations"]], ["take_0", "take_1"])
        self.assertIn("endTimeCode = 120", stage(build_usdz(document, FakeBrep())))

    def test_shared_declarations_fail_on_duplicates_cycles_and_local_animation_let(self):
        for model, animation, error in (
            ("let rate = 1", "LET rate = 2", "Animation line 1: duplicate variable: rate"),
            ("fn rate() = 1", "let rate = 2", "Animation line 1: duplicate function or variable: rate"),
            ("", "let rate = 1\nlet rate = 2", "Animation line 2: duplicate variable: rate"),
            ("let rate = pace", "let pace = rate", "cyclic global definition"),
            ("", "for i in range(2)\nlet rate = i\nend", "Animation line 2: let is only allowed at the top level"),
            ("", "animation loop 1\nlet rate = 2\nend", "Animation line 2: let is only allowed at the top level"),
            ("", "let rate = base.position.x", "Animation line 1:"),
        ):
            with self.subTest(model=model, animation=animation), self.assertRaisesRegex(ValueError, error):
                resolve_animation_source(animation, model)

    def test_animation_let_without_clips_can_drive_model(self):
        document = {**MODEL, "source": "group g\nposition lift 0 0\nbox a 0 0 0 1 1 1\nend",
                    "animationSource": "let lift = 3"}
        response = json.loads(run_model_request(document, "/preview"))
        self.assertEqual(response["meshes"][0]["groupPath"][0]["position"], [3, 0, 0])
        self.assertEqual(response["resolvedAnimationSource"], "")

    def test_clip_duplicates_are_checked_after_expanding_outer_loops(self):
        source = f"for i in range(0)\n{clip()}\nend\n{clip()}"
        resolve_animation_source(source, syntax_only=True)
        self.assertEqual(parse_animation(source), parse_animation(clip()))
        with self.assertRaisesRegex(ValueError, "duplicate clip name"):
            parse_animation(source.replace("range(0)", "range(1)"))


if __name__=='__main__':
    unittest.main()
