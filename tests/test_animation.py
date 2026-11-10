"""Loop validation and independently decoded GLB/USDZ animation data."""
import io
import json
import math
from pathlib import Path
import struct
import unittest
import zipfile

from animation import parse_animation, bind_animation, sample_track, sample_times, resolve_animation_source
from model_export import to_glb, to_usdz
from json_to_glb import validate_document
from test_export_hierarchy import glb_world, usd_world


def parse_clip(source="", **kwargs):
    collection = parse_animation(source, **kwargs)
    return collection["clips"][0] if collection else None


def glb_first_pose(data):
    doc, accessor = decode_glb(data)
    for channel in doc.get('animations', [{}])[0].get('channels', []):
        target = channel['target']
        values = accessor(doc['animations'][0]['samplers'][channel['sampler']]['output'])
        doc['nodes'][target['node']][target['path']] = list(values[:4 if target['path']=='rotation' else 3])
    encoded = json.dumps(doc).encode()
    encoded += b' ' * (-len(encoded) % 4)
    original_length = struct.unpack_from('<I', data, 12)[0]
    return data[:12] + struct.pack('<I4s',len(encoded),b'JSON') + encoded + data[20+original_length:]


def clip(channel='euler', middle='', last='0 0 360', first='0 0 0', target='rotor'):
    return f'animation main loop 4\ntrack {target}\nkey 0 {channel} {first}\n{middle}\nkey 4 {channel} {last}\nend\nend'


def mesh(path=None):
    return dict(name='blade', positions=[10, 0, 0, 12, 0, 0, 10, 1, 0],
                normals=[0, 0, 1]*3, material={}, group='rotor', groupPath=path or [
                    dict(name='rotor', position=[10,0,0], euler=[0,0,0], scale=[1,1,1])])


def decode_glb(data):
    length = struct.unpack_from('<I', data, 12)[0]
    doc = json.loads(data[20:20+length])
    binary = data[28+length:]

    def accessor(index):
        acc = doc['accessors'][index]
        view = doc['bufferViews'][acc['bufferView']]
        width = {'VEC3':3, 'VEC4':4, 'SCALAR':1}[acc['type']]
        return struct.unpack_from('<' + 'f'*(acc['count']*width), binary, view['byteOffset'])
    return doc, accessor


class AnimationTests(unittest.TestCase):
    def test_model_root_calculations_resolve_to_numeric_keys(self):
        model = ('let rpm = 120\nfn angle(seconds) = 360 * rpm * seconds / 60\n'
                 'group rotor\nlet rpm = 999\nfn angle(t) = t\nend\n'
                 'let period = 4\n')
        source = ('animation main loop ${period}\ntrack rotor\n'
                  'key 0 euler 0 0 0\nkey ${period} euler 0 0 ${angle(period)}\nend\nend')
        numeric = resolve_animation_source(source, model)
        self.assertNotIn('${', numeric)
        track = parse_clip(numeric)['tracks'][0]
        self.assertEqual(sample_track(track, 2)['euler'], [0, 0, 1440])
        self.assertEqual(parse_clip(resolve_animation_source(source.replace('${angle(period)}', 'angle(period)'), model)),
                         parse_clip(numeric))

    def test_animation_cannot_access_local_definitions(self):
        for block in ('group g', 'for i in range(1)', 'if 1', 'part p'):
            model = f'{block}\nlet local = 360\nfn local_fn() = 360\nend\n'
            for expression in ('local', 'local_fn()'):
                with self.subTest(block=block, expression=expression), self.assertRaisesRegex(ValueError, 'unknown'):
                    resolve_animation_source(clip(last=f'0 0 ${{{expression}}}'), model)
        with self.assertRaisesRegex(ValueError, 'unknown variable: rpm'):
            resolve_animation_source(clip(last='0 0 ${rpm}'), 'rpm = 360', 'python')

    def test_animation_expression_errors_and_closures(self):
        model = ('let base = 360\nfn turn(n) = n * base\nfn twice(n) = turn(n) * 2\n')
        numeric = resolve_animation_source(clip(last='0 0 ${twice(2)}'), model)
        self.assertEqual(parse_clip(numeric)['tracks'][0]['channels']['euler'][-1][1], [0, 0, 1440])
        for expression, message in [('missing', 'unknown variable'), ('turn()', 'expected 1 positional'),
                                    ('1/0', 'invalid arithmetic'), ('exp(10000)', 'invalid argument'),
                                    ('1e308*10', 'finite')]:
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, 'Animation line 5:.*' + message):
                resolve_animation_source(clip(last=f'0 0 ${{{expression}}}'), model)

    def test_model_references_in_position_scale_and_duration(self):
        model = 'let period = 4\nlet offset = 3\nfn size() = 2\n'
        source = ('animation main loop ${period}\ntrack rotor\n'
                  'key 0 position offset 0 0\nkey (period / 2) position (offset * 2) 0 0\n'
                  'key period position offset 0 0\n'
                  'key 0 scale size() 1 1\nkey period scale size() 1 1\nend\nend')
        animation = parse_clip(resolve_animation_source(source, model))
        self.assertEqual(sample_track(animation['tracks'][0], 1)['position'], [4.5, 0, 0])
        self.assertEqual(sample_track(animation['tracks'][0], 1)['scale'], [2, 1, 1])

    def test_compact_independent_cycles_and_export(self):
        source = ("animation main loop 120\ntrack rotor\ncycle euler 2\ncycle position 3\n"
                  "key 0 euler 0 0 0\nkey 2 euler 0 0 -720\n"
                  "key 0 position 0 0 0\nkey 1.5 position 12 0 0\nkey 3 position 0 0 0\nend\nend")
        animation = parse_clip(source)
        track = animation['tracks'][0]
        self.assertEqual(sum(map(len, track['channels'].values())), 5)
        for t, angle, x in [(0,0,0), (2,-720,8), (7.5,-2700,12), (120,-43200,0)]:
            self.assertEqual(sample_track(track,t)['euler'], [0,0,angle])
            self.assertEqual(sample_track(track,t)['position'], [x,0,0])
        times = sample_times(track,120)
        self.assertTrue({0,1.5,3,118.5,120}.issubset(times))
        self.assertEqual(parse_clip(resolve_animation_source(source)), animation)
        # Portable exports match a fully written timeline, including rotation direction.
        expanded = 'animation main loop 120\ntrack rotor\n'
        for i in range(61):
            expanded += f'key {i*2} euler 0 0 {-720*i}\n'
        for i in range(81):
            expanded += f'key {i*1.5} position {12 if i%2 else 0} 0 0\n'
        expanded += 'end\nend'
        for export in (to_glb, to_usdz):
            self.assertEqual(export([mesh()],animation_source=source),
                             export([mesh()],animation_source=expanded))

    def test_long_single_axis_cycles_use_angular_samples(self):
        source = ('animation main loop 720\ntrack second\ncycle euler 1\n'
                  'key 0 euler 0 0 0\nkey 1 euler 0 0 -360\nend\n'
                  'track first_assembly\ncycle euler 2\nkey 0 euler 0 0 0\n'
                  'key 2 euler 0 0 360\nend\nend')
        animation = parse_clip(source)
        self.assertEqual([len(sample_times(t,720)) for t in animation['tracks']], [5761,2881])
        for track, angle in zip(animation['tracks'], [-259200,129600]):
            times = sample_times(track,720)
            values = [sample_track(track,t)['euler'][2] for t in times]
            self.assertEqual(values[-1],angle)
            self.assertTrue(all(abs(b-a)<=45.000001 for a,b in zip(values,values[1:])))
        # Coupled Euler interpolation retains its temporal sampling density.
        coupled = parse_clip(clip(last='360 360 0'))['tracks'][0]
        self.assertGreaterEqual(len(sample_times(coupled,4)),241)
        static = parse_clip(clip(last='0 0 0'))['tracks'][0]
        self.assertEqual(sample_times(static,4),[0,4])

    def test_decimal_cycle_seams_and_scale(self):
        source = ('animation main loop 1\ntrack rotor\ncycle euler 0.1\ncycle scale 0.2\n'
                  'key 0 euler 0 0 0\nkey 0.1 euler 0 0 360\n'
                  'key 0 scale 1 1 1\nkey 0.1 scale 2 2 2\nkey 0.2 scale 1 1 1\nend\nend')
        track = parse_clip(source)['tracks'][0]
        for time in (0.1, 0.3, 0.6, 1):
            self.assertAlmostEqual(sample_track(track,time)['euler'][2], time * 3600)
        for value in sample_track(track,0.5)['scale']:
            self.assertAlmostEqual(value, 2)
        self.assertEqual(sample_track(track,1)['scale'], [1,1,1])

    def test_cycle_validation_and_expressions(self):
        source = ('animation main loop 4\ntrack rotor\ncycle euler 2\n'
                  'key 0 euler 0 0 0\nkey 2 euler 0 0 360\nend\nend')
        model = 'let period = 2\n'
        resolved = resolve_animation_source(source.replace('cycle euler 2', 'cycle euler (period * 1)'), model)
        self.assertEqual(parse_clip(resolved), parse_clip(source))
        for bad in [source.replace('cycle euler 2','cycle euler 0'),
                    source.replace('cycle euler 2','cycle euler 5'),
                    source.replace('cycle euler 2','cycle euler 2\ncycle euler 2'),
                    source.replace('cycle euler 2','cycle scale 2'),
                    source.replace('key 2 euler','key 4 euler'),
                    source.replace('cycle euler 2','cycle euler 0.00000001')]:
            with self.subTest(source=bad), self.assertRaises(ValueError):
                parse_clip(bad)
        with self.assertRaisesRegex(ValueError, 'samples'):
            parse_clip(source.replace('loop 4','loop 1000').replace('0 0 360','0 0 360000'))

    def test_track_for_loops(self):
        source = ('animation main loop 4\ntrack rotor\nfor i in range(5)\n'
                  'key i euler 0 0 ${i * 360}\nend\nend\nend')
        expected = clip(middle='key 1 euler 0 0 360\nkey 2 euler 0 0 720\nkey 3 euler 0 0 1080', last='0 0 1440')
        self.assertEqual(parse_clip(source),parse_clip(expected))
        self.assertEqual(to_glb([mesh()],animation_source=source),to_glb([mesh()],animation_source=expected))
        resolved = resolve_animation_source(source.replace('range(5)', 'range(count)').replace('i * 360', 'turn(i)'),
                                            'let count = 5\nfn turn(i) = i * 360\n')
        self.assertEqual(parse_clip(resolved),parse_clip(expected))
        nested = source.replace('for i in range(5)', 'for j in range(1)\nfor i in range(0, 5, 1)').replace('end\nend\nend', 'end\nend\nend\nend')
        self.assertEqual(parse_clip(nested),parse_clip(expected))
        periodic = source.replace('animation main loop 4', 'animation main loop 120').replace('track rotor', 'track rotor\ncycle euler 4')
        self.assertEqual(len(parse_clip(periodic)['tracks'][0]['channels']['euler']),5)
        with self.assertRaisesRegex(ValueError, 'expansion limit'):
            parse_clip('animation main loop 4\ntrack rotor\nfor i in range(4096)\nfor j in range(4096)\nend\nend\nend\nend')
        deep = 'animation main loop 4\ntrack rotor\n' + ''.join(f'for i{n} in range(1)\n' for n in range(33)) + 'end\n'*35
        with self.assertRaisesRegex(ValueError, 'nesting limit'):
            parse_clip(deep)
        for bad in [source.replace('range(5)', 'range(0,5,0)'),
                    source.replace('range(5)', 'range(5000)'),
                    source.replace('range(5)', 'range(1.5)'),
                    source.replace('key i', 'key 0'),
                    source.replace('for i in range(5)', 'for i in range(5)\ncycle euler 4'),
                    source.replace('track rotor\n', ''),
                    source.replace('key i euler 0 0 ${i * 360}', 'key i euler 0 0 ${missing}'),
                    source + '\nkey i euler 0 0 0']:
            with self.subTest(source=bad),self.assertRaises(ValueError):
                parse_clip(bad)

    def test_empty_and_comments(self):
        self.assertIsNone(parse_clip('# none\n'))
        self.assertNotIn('animations', decode_glb(to_glb([mesh()]))[0])

    def test_unwrapped_rotation(self):
        track = parse_clip(clip(last='0 0 720'))['tracks'][0]
        self.assertEqual(sample_track(track, 1)['euler'], [0,0,180])
        self.assertEqual(sample_track(track, 1)['scale'], [1,1,1])
        self.assertGreater(len(sample_times(track,4)),2)

    def test_position_and_scale(self):
        for channel, first, mid in [('position','0 0 0','20 0 0'), ('scale','1 1 1','2 3 4')]:
            track = parse_clip(clip(channel, f'key 2 {channel} {mid}', first, first))['tracks'][0]
            expected = [(a+b)/2 for a,b in zip(map(float,first.split()),map(float,mid.split()))]
            self.assertEqual(sample_track(track,1)[channel],expected)

    def test_large_euler_values(self):
        for base in (1e12, -1e12):
            track = parse_clip(clip(first=f'0 0 {base}', last=f'0 0 {base+360}'))['tracks'][0]
            self.assertEqual(sample_track(track, 2)['euler'], [0, 0, base+180])
        for value in ('1e999', '-1e999', 'NaN'):
            with self.assertRaisesRegex(ValueError, 'finite'):
                parse_clip(clip(first=f'0 0 {value}', last=f'0 0 {value}'))
        for channel in ('position', 'scale'):
            with self.assertRaisesRegex(ValueError, 'within ±1e9'):
                parse_clip(clip(channel, first='1e12 1 1', last='1e12 1 1'))

    def test_euler_expressions(self):
        cases = [('360*10', 3600), ('(360 * (2 + 3))', 1800),
                 ('${360 * (2 + 3)}', 1800), ('-360*2', -720),
                 ('(1e3 - 280) / 2', 360), ('360/2/2*4', 360),
                 ('(.5 + .5) * 360', 360)]
        for expression, expected in cases:
            # Wrap expressions with whitespace to preserve the XYZ boundaries.
            expression = expression if expression.startswith('${') else f'({expression})'
            with self.subTest(expression=expression):
                source = clip(last=f'0 0 {expression}')
                track = parse_clip(source)['tracks'][0]
                self.assertEqual(track['channels']['euler'][-1][1], [0, 0, expected])
                self.assertEqual(sample_track(track, 2)['euler'], [0, 0, expected/2])
        arithmetic = clip(last='0 0 ${360 * 2}')
        self.assertEqual(to_glb([mesh()], animation_source=arithmetic),
                         to_glb([mesh()], animation_source=clip(last='0 0 720')))
        self.assertEqual(to_usdz([mesh()], animation_source=arithmetic),
                         to_usdz([mesh()], animation_source=clip(last='0 0 720')))

    def test_invalid_euler_expressions(self):
        for expression in ('1/0', '1e308*10', '360**2', '0x168', 'Math.sin(0)',
                           '__import__("os")', 'turns*360', '(360', '${360',
                           '360)', '(360 +)', '()','(' * 34 + '360' + ')' * 34,
                           '(' + '+'.join(['0'] * 257) + ')'):
            with self.subTest(expression=expression), self.assertRaisesRegex(ValueError, 'Animation line 5:'):
                parse_clip(clip(last=f'0 0 {expression}'))

    def test_short_keys_repeat_with_remainder_in_preview_and_exports(self):
        source = ('animation loop 5\ntrack rotor\n'
                  'key 0 position 0 0 0\nkey 2 position 20 0 0\n'
                  'key 0 euler 0 0 0\nkey 3 euler 0 0 90\nend\nend')
        track = parse_clip(source)['tracks'][0]
        self.assertEqual(sample_track(track, 2)['position'], [0, 0, 0])
        self.assertEqual(sample_track(track, 3)['euler'], [0, 0, 0])
        self.assertEqual(sample_track(track, 5)['position'], [10, 0, 0])
        self.assertEqual(sample_track(track, 5)['euler'], [0, 0, 60])
        self.assertEqual(parse_clip(resolve_animation_source(source)), parse_clip(source))

        doc, read = decode_glb(to_glb([mesh()], animation_source=source))
        animation = doc['animations'][0]
        channel = next(c for c in animation['channels'] if c['target']['path'] == 'translation')
        sampler = animation['samplers'][channel['sampler']]
        times = read(sampler['input'])
        values = read(sampler['output'])[::3]
        seam = times.index(2)
        self.assertTrue(1.99999 < times[seam-1] < 2)
        self.assertAlmostEqual(values[seam-1], 20, places=5)
        self.assertEqual(values[seam], 0)
        self.assertEqual((times[-1], values[-1]), (5, 10))

        with zipfile.ZipFile(io.BytesIO(to_usdz([mesh()], animation_source=source))) as archive:
            stage = archive.read('model.usda').decode()
        self.assertIn('120: (0, 0, 0)', stage)
        self.assertIn('300: (10, 0, 0)', stage)
        self.assertIn('300: (0, 0, 60)', stage)

        explicit = source.replace('track rotor', 'track rotor\ncycle euler 3')
        self.assertEqual(sample_track(parse_clip(explicit)['tracks'][0], 5)['euler'], [0, 0, 150])

    def test_decimal_implicit_cycles_land_on_exact_boundaries(self):
        source = ('animation loop 0.6\ntrack rotor\n'
                  'key 0 position 0 0 0\nkey 0.1 position 10 0 0\n'
                  'key 0 scale 1 1 1\nkey 0.3 scale 2 2 2\nend\nend')
        track = parse_clip(source)['tracks'][0]
        for time in (0.3, 0.6):
            self.assertEqual(sample_track(track, time)['position'], [0, 0, 0])
            self.assertEqual(sample_track(track, time)['scale'], [1, 1, 1])
        # The independently repeated channels share seams such as 0.1*3 and 0.3.
        self.assertTrue(to_glb([mesh()], animation_source=source))

    def test_open_loop_endpoints(self):
        for channel, first, last in [('position', '0 0 0', '12 0 0'),
                                     ('euler', '0 0 0', '0 0 180'),
                                     ('scale', '1 1 1', '2 3 4')]:
            with self.subTest(channel=channel):
                source = clip(channel, first=first, last=last)
                animation = parse_clip(resolve_animation_source(source))
                track = animation['tracks'][0]
                self.assertEqual(sample_track(track, 4)[channel], list(map(float, last.split())))
                self.assertEqual(sample_track(track, 0)[channel], list(map(float, first.split())))
                self.assertTrue(to_glb([mesh()], animation_source=source))
                self.assertTrue(to_usdz([mesh()], animation_source=source))
                cyclic = source.replace('track rotor', f'track rotor\ncycle {channel} 4').replace('loop 4', 'loop 8')
                track = parse_clip(cyclic)['tracks'][0]
                if channel != 'euler':
                    self.assertGreater(sample_track(track, 3.999)[channel][0], 0.99 * float(last.split()[0]))
                    self.assertEqual(sample_track(track, 4)[channel], list(map(float, first.split())))
                else:
                    self.assertEqual(sample_track(track, 8)[channel], [0, 0, 360])

    def test_invalid(self):
        invalid = [None, 1, 'x'*100001, 'animation main loop 0\nend', 'animation main loop 601\nend',
                   clip('scale',last='1 1 1',first='0 1 1'), clip(first='NaN 0 0'),
                   clip(middle='key 0 euler 0 0 90'), clip(middle='key 5 euler 0 0 90'),
                   clip().replace('key 0','key 1'), clip().replace('key 4','key 0'),
                   clip()+'\nend', clip().removesuffix('\nend'), 'animation main loop 4\nend',
                   clip(last='0 0 1000000080')]
        for source in invalid:
            with self.subTest(source=str(source)[:80]), self.assertRaises(ValueError):
                parse_clip(source)

    def test_bounds(self):
        # A valid whole number of revolutions, exceeding the generated sample budget.
        with self.assertRaisesRegex(ValueError,'samples'):
            parse_clip(clip(last='0 0 360000000'))

    def test_bind_missing_ambiguous_and_full_paths(self):
        a=mesh([dict(name='a',position=[0]*3,euler=[0]*3,scale=[1]*3), *mesh()['groupPath']])
        b=mesh([dict(name='b',position=[0]*3,euler=[0]*3,scale=[1]*3), *mesh()['groupPath']])
        with self.assertRaises(ValueError):
            bind_animation(parse_clip(clip()),[a,b])
        self.assertEqual(list(bind_animation(parse_clip(clip(target='a/rotor')),[a,b])),[('a','rotor')])
        with self.assertRaises(ValueError):
            to_glb([mesh()],animation_source=clip(target='missing'))
        with self.assertRaises(ValueError):
            to_glb([],animation_source=clip())
        double=clip().rsplit('\nend',1)[0]+'\ntrack a/rotor\nkey 0 euler 0 0 0\nkey 4 euler 0 0 360\nend\nend'
        with self.assertRaisesRegex(ValueError,'duplicate'):
            bind_animation(parse_clip(double),[a])

    def test_glb_rotation_values_and_structure(self):
        doc,read=decode_glb(to_glb([mesh()],scale=.001,animation_source=clip(last='0 0 720')))
        animation=doc['animations'][0]
        self.assertTrue(animation['extras']['loop'])
        rotation=next(c for c in animation['channels'] if c['target']['path']=='rotation')
        sampler=animation['samplers'][rotation['sampler']]
        times,values=read(sampler['input']),read(sampler['output'])
        self.assertEqual((times[0],times[-1]),(0,4))
        self.assertTrue(all(a<b for a,b in zip(times,times[1:])))
        self.assertEqual(len(values),len(times)*4)
        # One second of a two-revolution/four-second loop = 180 degrees, mapped Z -> Y.
        index=times.index(1.)*4
        self.assertAlmostEqual(abs(values[index+1]),1,places=6)
        self.assertAlmostEqual(values[index+3],0,places=6)
        for i in range(0,len(values),4):
            self.assertAlmostEqual(sum(v*v for v in values[i:i+4]),1,places=6)
            if i:
                self.assertGreater(sum(a*b for a,b in zip(values[i-4:i],values[i:i+4])),0)
        target=rotation['target']['node']
        static=next(n for n in doc['nodes'] if n['name']=='rotor')
        self.assertEqual(target,doc['nodes'].index(static))
        self.assertEqual(static['translation'],[.01,0,0])
        self.assertNotIn('target',doc['bufferViews'][doc['accessors'][sampler['input']]['bufferView']])

    def test_export_translation_units_and_first_pose(self):
        source=clip('position',last='2 0 0',first='2 0 0')
        data=to_glb([mesh()],scale=.5,animation_source=source)
        # Static position 10 plus animated local offset 2, then export scale .5.
        self.assertEqual(glb_world(glb_first_pose(data))[1]['blade'][0][:3],[1,0,0])
        stage=zipfile.ZipFile(io.BytesIO(to_usdz([mesh()],scale=.5,animation_source=source))).read('model.usda').decode()
        self.assertIn('double3 xformOp:translate = (1, 0, 0)',stage)
        self.assertIn('xformOp:translate.timeSamples',stage)

    def test_usdz_samples_and_packaging(self):
        data=to_usdz([mesh()],animation_source=clip())
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info=archive.getinfo('model.usda')
            self.assertEqual((info.header_offset+30+len(info.filename)+len(info.extra))%64,0)
            self.assertEqual(info.compress_type,zipfile.ZIP_STORED)
            stage=archive.read(info).decode()
        self.assertIn('timeCodesPerSecond = 60',stage)
        self.assertIn('endTimeCode = 240',stage)
        self.assertIn('    autoPlay = true',stage.split('def Xform', 1)[0])
        self.assertIn('    playbackMode = "loop"',stage.split('def Xform', 1)[0])
        self.assertIn('120: (0, 0, 180)',stage)
        self.assertIn('240: (0, 0, 360)',stage)
        self.assertEqual(stage.count('def Mesh '),1)
        self.assertEqual(stage.count('xformOp:rotateXYZ.timeSamples'),1)
        paths, _ = usd_world(data)
        self.assertEqual(paths['blade'], ['Model', 'Geometry', 'ModelContent', 'rotor'])
        self.assertNotIn('def Xform "Scene"', stage)
        self.assertNotIn('timeSamples', stage.split('def Xform "rotor"', 1)[0])

    def test_non_identity_defaults_for_all_usd_channels(self):
        source='animation main loop 4\ntrack rotor\n'
        for channel,value in [('position','1 2 3'),('euler','10 20 30'),('scale','2 3 4')]:
            source+=f'key 0 {channel} {value}\nkey 4 {channel} {value}\n'
        source+='end\nend'
        stage=zipfile.ZipFile(io.BytesIO(to_usdz([mesh()],animation_source=source))).read('model.usda').decode()
        for op,value in [('translate','1, 2, 3'),('rotateXYZ','10, 20, 30'),('scale','2, 3, 4')]:
            self.assertIn(f'double3 xformOp:{op} = ({value})',stage)

    def test_animation_targets_existing_groups_with_repeated_leaf_names(self):
        def group(name):
            return dict(name=name, position=[0,0,0], euler=[0,0,0], scale=[1,1,1])
        a = mesh([group('a'), group('detail')]); a['name'] = 'first'
        b = mesh([group('b'), group('detail')]); b['name'] = 'second'
        source = clip(target='a/detail') + '\n' + clip(target='b/detail').replace('animation main', 'animation other')
        doc, _ = decode_glb(to_glb([a,b], animation_source=source))
        self.assertEqual([c['name'] for c in doc['animations']], ['main','other'])
        self.assertEqual(len(doc['nodes']), 6)
        targets = [c['channels'][0]['target']['node'] for c in doc['animations']]
        self.assertNotEqual(*targets)
        self.assertEqual([doc['nodes'][i]['name'] for i in targets], ['detail','detail'])
        self.assertFalse(any(n['name'].startswith('Animation_') for n in doc['nodes']))

    def test_nested_static_and_animated_frames_match_world_geometry(self):
        parent = dict(name='parent', position=[10,20,30], euler=[15,25,35], scale=[2,3,4])
        child = dict(name='child', position=[3,4,5], euler=[-10,20,40], scale=[1,2,3])
        pa = dict(position=[1,2,3], euler=[20,10,5], scale=[1.1,1.2,1.3])
        ca = dict(position=[2,1,0], euler=[30,40,50], scale=[1.3,1.2,1.1])

        def forward(point, frames):
            v = list(point)
            for frame in reversed(frames):
                v = [x*s for x,s in zip(v,frame['scale'])]
                for axis, degrees in enumerate(frame['euler']):
                    j,k = (axis+1)%3,(axis+2)%3
                    c,s = math.cos(math.radians(degrees)),math.sin(math.radians(degrees))
                    v[j],v[k] = c*v[j]-s*v[k],s*v[j]+c*v[k]
                v = [x+t for x,t in zip(v,frame['position'])]
            return v

        points = [[0,0,0],[1,0,0],[0,1,0]]
        m = mesh([parent,child])
        m['positions'] = [v for point in points for v in forward(point,[parent,child])]
        source = 'animation main loop 4\n'
        for name, pose in [('parent',pa),('parent/child',ca)]:
            source += f'track {name}\n'
            for channel,value in pose.items():
                text = ' '.join(map(str,value))
                source += f'key 0 {channel} {text}\nkey 4 {channel} {text}\n'
            source += 'end\n'
        source += 'end'
        expected = [v*.01 for point in points for v in forward(point,[pa,ca])]
        for _, world in [glb_world(glb_first_pose(to_glb([m],scale=.01,animation_source=source))),
                         usd_world(to_usdz([m],scale=.01,animation_source=source))]:
            for actual,value in zip(world['blade'][0],expected):
                self.assertAlmostEqual(actual,value,places=6)

    def test_document_roundtrip_and_validation(self):
        doc=json.loads((Path(__file__).parents[1]/'examples/animation_loop.json').read_text())
        validate_document(doc)
        doc['animationSource']='not valid'
        with self.assertRaises(ValueError):
            validate_document(doc)
        del doc['animationSource']
        validate_document(doc)


if __name__=='__main__':
    unittest.main()
